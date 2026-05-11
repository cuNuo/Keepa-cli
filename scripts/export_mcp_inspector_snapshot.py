"""
scripts/export_mcp_inspector_snapshot.py
文件说明：导出可复现的 MCP Inspector/SDK typed 协议快照。
主要职责：用官方 Python MCP SDK ClientSession 记录 initialize、list_* 首页与分页、错误映射和 ping。
依赖边界：只连接本地隔离 SDK adapter，不访问真实 Keepa API，不持久化 secret。
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
from typing import Any, Awaitable, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent.mcp_sdk_adapter import (
    SDK_DEFAULT_PROMPT_PAGE_SIZE,
    SDK_DEFAULT_RESOURCE_PAGE_SIZE,
    SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE,
    SDK_DEFAULT_TOOL_PAGE_SIZE,
    adapter_status,
)


def _dump_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [_dump_model(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump_model(item) for key, item in value.items()}
    return value


def _contains_text(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return expected in value
    if isinstance(value, dict):
        return any(_contains_text(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_text(item, expected) for item in value)
    return False


def _item_name(item: Any) -> str:
    if hasattr(item, "uriTemplate"):
        return str(getattr(item, "uriTemplate"))
    if hasattr(item, "uri"):
        return str(getattr(item, "uri"))
    return str(getattr(item, "name", ""))


async def _collect_pages(list_func: Callable[..., Awaitable[Any]], result_attr: str) -> tuple[list[Any], list[dict[str, Any]]]:
    items: list[Any] = []
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = await list_func(cursor=cursor)
        page_items = list(getattr(page, result_attr))
        items.extend(page_items)
        pages.append(
            {
                "count": len(page_items),
                "next_cursor": page.nextCursor,
                "names": [_item_name(item) for item in page_items],
                "meta": page.meta,
            }
        )
        cursor = page.nextCursor
        if not cursor:
            break
    return items, pages


def _summarize_pages(items: list[Any], pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_count": len(items),
        "page_count": len(pages),
        "first_page_count": pages[0]["count"],
        "first_page_names": pages[0]["names"],
        "first_page_meta": pages[0]["meta"],
        "last_page_count": pages[-1]["count"],
    }


async def _build_snapshot() -> dict[str, Any]:
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
                tools, tool_pages = await _collect_pages(session.list_tools, "tools")
                resources, resource_pages = await _collect_pages(session.list_resources, "resources")
                templates, template_pages = await _collect_pages(session.list_resource_templates, "resourceTemplates")
                prompts, prompt_pages = await _collect_pages(session.list_prompts, "prompts")
                policy = await session.read_resource(AnyUrl("keepa://context/policy"))
                invalid = await session.call_tool("keepa.categories_search", {})
                ping = await session.send_ping()

    invalid_payload = _dump_model(invalid)
    return {
        "ok": True,
        "kind": "mcp_inspector_sdk_snapshot",
        "adapter_status": adapter_status(),
        "server_info": {
            "name": initialize.serverInfo.name,
            "version": initialize.serverInfo.version,
        },
        "initialize": _dump_model(initialize),
        "lists": {
            "tools": _summarize_pages(tools, tool_pages),
            "resources": _summarize_pages(resources, resource_pages),
            "resource_templates": _summarize_pages(templates, template_pages),
            "prompts": _summarize_pages(prompts, prompt_pages),
        },
        "resource_probe": {
            "uri": "keepa://context/policy",
            "content_count": len(policy.contents),
            "text_bytes": len(policy.contents[0].text),
        },
        "tool_error_probe": {
            "name": "keepa.categories_search",
            "is_error": bool(invalid.isError),
            "contains_invalid_arguments": _contains_text(invalid_payload, "invalid_arguments"),
            "contains_missing_term": _contains_text(invalid_payload, "missing required argument: term"),
        },
        "ping": _dump_model(ping),
    }


def _validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot["server_info"]["name"] != "keepa_mcp":
        raise AssertionError("snapshot serverInfo.name must be keepa_mcp")
    lists = snapshot["lists"]
    if lists["tools"]["first_page_names"][0] != "keepa.context_policy":
        raise AssertionError("tools snapshot must start with keepa.context_policy")
    if lists["tools"]["first_page_count"] > SDK_DEFAULT_TOOL_PAGE_SIZE or lists["tools"]["page_count"] < 2:
        raise AssertionError("tools snapshot must be paginated with a bounded first page")
    if lists["resources"]["first_page_names"][0] != "keepa://context/policy":
        raise AssertionError("resources snapshot must start with keepa://context/policy")
    if lists["resources"]["first_page_count"] > SDK_DEFAULT_RESOURCE_PAGE_SIZE or lists["resources"]["page_count"] < 2:
        raise AssertionError("resources snapshot must be paginated with a bounded first page")
    if lists["resource_templates"]["first_page_names"][0] != "keepa://toolsets/{toolset}":
        raise AssertionError("resource template snapshot must start with keepa://toolsets/{toolset}")
    if (
        lists["resource_templates"]["first_page_count"] > SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE
        or lists["resource_templates"]["page_count"] < 2
    ):
        raise AssertionError("resource template snapshot must be paginated with a bounded first page")
    if lists["prompts"]["first_page_names"][0] != "keepa.product_research":
        raise AssertionError("prompt snapshot must start with keepa.product_research")
    if lists["prompts"]["first_page_count"] > SDK_DEFAULT_PROMPT_PAGE_SIZE or lists["prompts"]["page_count"] < 2:
        raise AssertionError("prompt snapshot must be paginated with a bounded first page")
    if snapshot["resource_probe"]["text_bytes"] <= 100:
        raise AssertionError("context policy resource snapshot is unexpectedly small")
    error_probe = snapshot["tool_error_probe"]
    if not error_probe["is_error"] or not error_probe["contains_invalid_arguments"] or not error_probe["contains_missing_term"]:
        raise AssertionError("tool error snapshot lost invalid_arguments detail")
    if snapshot["ping"] != {}:
        raise AssertionError("ping snapshot must be empty result")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出或校验 MCP Inspector/SDK typed 协议快照。")
    parser.add_argument("--json", action="store_true", help="向 stdout 输出 JSON 快照。")
    parser.add_argument("--out", type=Path, help="把 JSON 快照写入指定路径。")
    parser.add_argument("--check", action="store_true", help="只校验快照形状和关键协议字段。")
    parser.add_argument("--skip-if-missing", action="store_true", help="缺少可选 mcp 包时返回成功。")
    args = parser.parse_args(argv)

    if importlib.util.find_spec("mcp") is None:
        message = "official mcp package is not installed"
        if args.skip_if_missing:
            payload = {"ok": True, "skipped": True, "reason": message}
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"mcp inspector snapshot skipped: {message}")
            return 0
        print(message, file=sys.stderr)
        return 1

    snapshot = asyncio.run(_build_snapshot())
    if args.check:
        _validate_snapshot(snapshot)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.check:
        print("mcp inspector sdk snapshot check ok")
    elif args.out:
        print(f"mcp inspector sdk snapshot written: {args.out}")
    else:
        print("mcp inspector sdk snapshot ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
