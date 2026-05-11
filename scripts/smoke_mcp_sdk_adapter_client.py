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


async def _collect_tool_pages(session: Any) -> tuple[list[Any], list[dict[str, Any]]]:
    tools: list[Any] = []
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(cursor=cursor)
        page_tools = list(page.tools)
        tools.extend(page_tools)
        pages.append(
            {
                "count": len(page_tools),
                "next_cursor": page.nextCursor,
                "tool_names": [tool.name for tool in page_tools],
                "meta": page.meta,
            }
        )
        cursor = page.nextCursor
        if not cursor:
            break
    return tools, pages


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
                tool_list, tool_pages = await _collect_tool_pages(session)
                tool_names = [tool.name for tool in tool_list]
                if "keepa.context_policy" not in tool_names:
                    raise AssertionError("SDK adapter did not expose keepa.context_policy")
                if not tool_pages or tool_pages[0]["tool_names"][0] != "keepa.context_policy":
                    raise AssertionError("SDK adapter first tool page did not prioritize keepa.context_policy")
                if len(tool_pages[0]["tool_names"]) > 8:
                    raise AssertionError("SDK adapter first tool page is too large for Agent startup")
                tool_result = await session.call_tool("keepa.context_policy", {})
                if tool_result.isError or not tool_result.structuredContent:
                    raise AssertionError("keepa.context_policy did not return structuredContent")
                resources = await session.list_resources()
                resource_uris = [str(resource.uri) for resource in resources.resources]
                if "keepa://context/policy" not in resource_uris:
                    raise AssertionError("SDK adapter did not expose keepa://context/policy")
                resource = await session.read_resource(AnyUrl("keepa://context/policy"))
                prompts = await session.list_prompts()
                prompt_names = [prompt.name for prompt in prompts.prompts]
                if "keepa.product_research" not in prompt_names:
                    raise AssertionError("SDK adapter did not expose keepa.product_research")

    return {
        "ok": True,
        "server_info": {
            "name": initialize.serverInfo.name,
            "version": initialize.serverInfo.version,
        },
        "tools": {
            "count": len(tool_names),
            "page_count": len(tool_pages),
            "first_page_names": tool_pages[0]["tool_names"],
            "first_page_meta": tool_pages[0]["meta"],
            "has_context_policy": "keepa.context_policy" in tool_names,
        },
        "resources": {
            "count": len(resource_uris),
            "context_policy_bytes": len(resource.contents[0].text),
        },
        "prompts": {
            "count": len(prompt_names),
            "has_product_research": "keepa.product_research" in prompt_names,
        },
        "tool_call": {
            "is_error": tool_result.isError,
            "has_structured_content": bool(tool_result.structuredContent),
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
        print(f"mcp sdk adapter client smoke ok: {result['tools']['count']} tools, {result['resources']['count']} resources, {result['prompts']['count']} prompts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
