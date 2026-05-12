"""
scripts/smoke_mcp_sdk_adapter_client.py
文件说明：用官方 Python MCP SDK ClientSession 验证隔离 adapter。
主要职责：启动 low-level SDK stdio server，检查 initialize、tools/resources/prompts 与只读工具调用。
依赖边界：只访问本地 MCP adapter 和离线资源，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent.mcp_sdk_adapter import (
    SDK_DEFAULT_PROMPT_PAGE_SIZE,
    SDK_DEFAULT_RESOURCE_PAGE_SIZE,
    SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE,
    SDK_DEFAULT_TOOL_PAGE_SIZE,
)


async def _collect_pages(list_func: Any, result_attr: str) -> tuple[list[Any], list[dict[str, Any]]]:
    items: list[Any] = []
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = await list_func(cursor=cursor)
        page_items = list(getattr(page, result_attr))
        items.extend(page_items)
        names = [
            str(getattr(item, "uriTemplate"))
            if hasattr(item, "uriTemplate")
            else str(getattr(item, "uri"))
            if hasattr(item, "uri")
            else str(getattr(item, "name", ""))
            for item in page_items
        ]
        pages.append(
            {
                "count": len(page_items),
                "next_cursor": page.nextCursor,
                "names": names,
                "meta": page.meta,
            }
        )
        cursor = page.nextCursor
        if not cursor:
            break
    return items, pages


def _contains_text(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return expected in value
    if isinstance(value, dict):
        return any(_contains_text(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_text(item, expected) for item in value)
    return False


async def _run_smoke() -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from pydantic import AnyUrl

    with tempfile.TemporaryDirectory() as temp_dir:
        env = {**os.environ, "KEEPA_CLI_CONFIG": str(Path(temp_dir) / "config.toml")}
        env.pop("KEEPA_API_KEY", None)
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "keepa_cli.agent.mcp_sdk_adapter", "--stdio"],
            cwd=REPO_ROOT,
            env=env,
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialize = await session.initialize()
                tool_list, tool_pages = await _collect_pages(session.list_tools, "tools")
                tool_names = [tool.name for tool in tool_list]
                if "context_policy" not in tool_names:
                    raise AssertionError("SDK adapter did not expose context_policy")
                if not tool_pages or tool_pages[0]["names"][0] != "context_policy":
                    raise AssertionError("SDK adapter first tool page did not prioritize context_policy")
                if len(tool_pages[0]["names"]) > SDK_DEFAULT_TOOL_PAGE_SIZE:
                    raise AssertionError("SDK adapter first tool page is too large for Agent startup")
                tool_result = await session.call_tool("context_policy", {})
                if tool_result.isError or not tool_result.structuredContent:
                    raise AssertionError("context_policy did not return structuredContent")
                invalid_schema_result = await session.call_tool("categories_search", {"domain": "US", "term": 123})
                if not invalid_schema_result.isError:
                    raise AssertionError("SDK adapter did not map JSON Schema validation failure to isError=true")
                if not _contains_text(invalid_schema_result.structuredContent, "invalid_arguments"):
                    raise AssertionError("SDK adapter JSON Schema validation lost invalid_arguments error kind")
                if not _contains_text(invalid_schema_result.structuredContent, "term: expected string"):
                    raise AssertionError("SDK adapter JSON Schema validation lost field type detail")
                resources, resource_pages = await _collect_pages(session.list_resources, "resources")
                resource_uris = [str(resource.uri) for resource in resources]
                if "keepa://context/policy" not in resource_uris:
                    raise AssertionError("SDK adapter did not expose keepa://context/policy")
                if len(resource_pages[0]["names"]) > SDK_DEFAULT_RESOURCE_PAGE_SIZE:
                    raise AssertionError("SDK adapter first resource page is too large for Agent startup")
                if resource_pages[0]["names"][0] != "keepa://context/policy":
                    raise AssertionError("SDK adapter first resource page did not prioritize context policy")
                resource = await session.read_resource(AnyUrl("keepa://context/policy"))
                templates, template_pages = await _collect_pages(session.list_resource_templates, "resourceTemplates")
                template_names = [str(template.uriTemplate) for template in templates]
                if "keepa://toolsets/{toolset}" not in template_names:
                    raise AssertionError("SDK adapter did not expose toolset resource template")
                if len(template_pages[0]["names"]) > SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE:
                    raise AssertionError("SDK adapter first template page is too large for Agent startup")
                prompts, prompt_pages = await _collect_pages(session.list_prompts, "prompts")
                prompt_names = [prompt.name for prompt in prompts]
                if "product_research" not in prompt_names:
                    raise AssertionError("SDK adapter did not expose product_research")
                if len(prompt_pages[0]["names"]) > SDK_DEFAULT_PROMPT_PAGE_SIZE:
                    raise AssertionError("SDK adapter first prompt page is too large for Agent startup")
                if prompt_pages[0]["names"][0] != "product_research":
                    raise AssertionError("SDK adapter first prompt page did not prioritize product research")

    return {
        "ok": True,
        "server_info": {
            "name": initialize.serverInfo.name,
            "version": initialize.serverInfo.version,
        },
        "tools": {
            "count": len(tool_names),
            "page_count": len(tool_pages),
            "first_page_names": tool_pages[0]["names"],
            "first_page_meta": tool_pages[0]["meta"],
            "has_context_policy": "context_policy" in tool_names,
        },
        "resources": {
            "count": len(resource_uris),
            "page_count": len(resource_pages),
            "first_page_names": resource_pages[0]["names"],
            "first_page_meta": resource_pages[0]["meta"],
            "context_policy_bytes": len(resource.contents[0].text),
        },
        "resource_templates": {
            "count": len(template_names),
            "page_count": len(template_pages),
            "first_page_names": template_pages[0]["names"],
            "first_page_meta": template_pages[0]["meta"],
        },
        "prompts": {
            "count": len(prompt_names),
            "page_count": len(prompt_pages),
            "first_page_names": prompt_pages[0]["names"],
            "first_page_meta": prompt_pages[0]["meta"],
            "has_product_research": "product_research" in prompt_names,
        },
        "tool_call": {
            "is_error": tool_result.isError,
            "has_structured_content": bool(tool_result.structuredContent),
            "schema_error_is_error": invalid_schema_result.isError,
            "schema_error_contains_type_detail": _contains_text(invalid_schema_result.structuredContent, "term: expected string"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test the official Python MCP SDK adapter with ClientSession.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    parser.add_argument("--skip-if-missing", action="store_true", help="Return success when the optional mcp package is missing.")
    args = parser.parse_args(argv)

    if importlib.util.find_spec("mcp") is None:
        message = "official mcp package is not installed"
        if args.skip_if_missing:
            payload = {"ok": True, "skipped": True, "reason": message}
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"mcp sdk adapter smoke skipped: {message}")
            return 0
        print(message, file=sys.stderr)
        return 1

    result = asyncio.run(_run_smoke())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "mcp sdk adapter client smoke ok: "
            f"{result['tools']['count']} tools, "
            f"{result['resources']['count']} resources, "
            f"{result['resource_templates']['count']} templates, "
            f"{result['prompts']['count']} prompts"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
