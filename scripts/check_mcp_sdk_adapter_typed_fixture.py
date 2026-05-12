"""
scripts/check_mcp_sdk_adapter_typed_fixture.py
文件说明：用官方 Python MCP SDK typed client 映射 Inspector 协议 fixture。
主要职责：验证 SDK adapter 的真实 ClientSession 调用与现有 Inspector fixture 语义一致。
依赖边界：只连接本地 stdio adapter，不访问真实 Keepa API；SDK 不支持的 Keepa 扩展 list 参数只记录降级映射。
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
)

DEFAULT_FIXTURE = REPO_ROOT / "tests" / "agent_eval_fixtures" / "mcp_inspector_protocol_fixture.json"


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


async def _collect_pages(list_func: Callable[..., Awaitable[Any]], result_attr: str) -> tuple[list[Any], list[dict[str, Any]]]:
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


async def _run_fixture(spec: dict[str, Any]) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

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
                responses: list[dict[str, Any]] = []
                initialized = False
                for step in spec["steps"]:
                    method = step["method"]
                    params = step.get("params") or {}
                    if method == "initialize":
                        result = await session.initialize()
                        initialized = True
                        responses.append({"id": step["id"], "method": method, "result": _dump_model(result)})
                    elif method == "tools/list":
                        if not initialized:
                            raise AssertionError("fixture must initialize before typed list_tools")
                        tools, pages = await _collect_pages(session.list_tools, "tools")
                        responses.append(
                            {
                                "id": step["id"],
                                "method": method,
                                "result": {
                                    "total_count": len(tools),
                                    "page_count": len(pages),
                                    "first_page_count": pages[0]["count"],
                                    "first_page_names": pages[0]["names"],
                                    "first_page_meta": pages[0]["meta"],
                                    "unsupported_fixture_params": sorted(set(params) - {"cursor"}),
                                },
                            }
                        )
                    elif method == "resources/list":
                        resources, pages = await _collect_pages(session.list_resources, "resources")
                        responses.append(
                            {
                                "id": step["id"],
                                "method": method,
                                "result": {
                                    "total_count": len(resources),
                                    "page_count": len(pages),
                                    "first_page_count": pages[0]["count"],
                                    "first_page_names": pages[0]["names"],
                                    "first_page_meta": pages[0]["meta"],
                                    "unsupported_fixture_params": sorted(set(params) - {"cursor"}),
                                },
                            }
                        )
                    elif method == "prompts/list":
                        prompts, pages = await _collect_pages(session.list_prompts, "prompts")
                        responses.append(
                            {
                                "id": step["id"],
                                "method": method,
                                "result": {
                                    "total_count": len(prompts),
                                    "page_count": len(pages),
                                    "first_page_count": pages[0]["count"],
                                    "first_page_names": pages[0]["names"],
                                    "first_page_meta": pages[0]["meta"],
                                    "unsupported_fixture_params": sorted(set(params) - {"cursor"}),
                                },
                            }
                        )
                    elif method == "resources/templates/list":
                        templates, pages = await _collect_pages(session.list_resource_templates, "resourceTemplates")
                        responses.append(
                            {
                                "id": step["id"],
                                "method": method,
                                "result": {
                                    "total_count": len(templates),
                                    "page_count": len(pages),
                                    "first_page_count": pages[0]["count"],
                                    "first_page_names": pages[0]["names"],
                                    "first_page_meta": pages[0]["meta"],
                                    "unsupported_fixture_params": sorted(set(params) - {"cursor"}),
                                },
                            }
                        )
                    elif method == "tools/call":
                        result = await session.call_tool(str(params["name"]), dict(params.get("arguments") or {}))
                        responses.append({"id": step["id"], "method": method, "result": _dump_model(result)})
                    elif method == "ping":
                        result = await session.send_ping()
                        responses.append({"id": step["id"], "method": method, "result": _dump_model(result)})
                    else:
                        raise AssertionError(f"unsupported typed SDK fixture method: {method}")
    return {"ok": True, "kind": "mcp_sdk_typed_fixture", "fixture": spec["id"], "responses": responses}


def _assert_typed_payload(payload: dict[str, Any], spec: dict[str, Any]) -> None:
    responses = {response["method"]: response for response in payload["responses"]}
    initialize = responses["initialize"]["result"]
    if initialize["serverInfo"]["name"] != "keepa_mcp":
        raise AssertionError("SDK initialize serverInfo.name mismatch")
    tools = responses["tools/list"]["result"]
    if tools["total_count"] < 30:
        raise AssertionError("SDK typed list_tools did not expose the full all-toolset inventory through pagination")
    if tools["page_count"] < 2:
        raise AssertionError("SDK typed list_tools should require pagination for the full inventory")
    if tools["first_page_count"] > SDK_DEFAULT_TOOL_PAGE_SIZE:
        raise AssertionError("SDK typed list_tools first page is too large for Agent startup")
    if tools["first_page_names"][0] != "context_policy":
        raise AssertionError("SDK typed list_tools must start with context_policy")
    if "limit" not in tools["unsupported_fixture_params"] or "toolset" not in tools["unsupported_fixture_params"]:
        raise AssertionError("SDK typed fixture mapping must record unsupported list_tools extension params")
    resources = responses["resources/list"]["result"]
    if resources["total_count"] < 2 or "keepa://context/policy" not in resources["first_page_names"]:
        raise AssertionError("SDK typed list_resources lost context policy resource")
    if resources["page_count"] < 2 or resources["first_page_count"] > SDK_DEFAULT_RESOURCE_PAGE_SIZE:
        raise AssertionError("SDK typed list_resources must expose a bounded first page with pagination")
    if resources["first_page_names"][0] != "keepa://context/policy":
        raise AssertionError("SDK typed list_resources must start with keepa://context/policy")
    prompts = responses["prompts/list"]["result"]
    if prompts["total_count"] < 2 or "product_research" not in prompts["first_page_names"]:
        raise AssertionError("SDK typed list_prompts lost product research prompt")
    if prompts["page_count"] < 2 or prompts["first_page_count"] > SDK_DEFAULT_PROMPT_PAGE_SIZE:
        raise AssertionError("SDK typed list_prompts must expose a bounded first page with pagination")
    if prompts["first_page_names"][0] != "product_research":
        raise AssertionError("SDK typed list_prompts must start with product_research")
    templates = responses["resources/templates/list"]["result"]
    if templates["total_count"] < 1:
        raise AssertionError("SDK typed list_resource_templates returned no templates")
    if templates["page_count"] < 2 or templates["first_page_count"] > SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE:
        raise AssertionError("SDK typed list_resource_templates must expose a bounded first page with pagination")
    if templates["first_page_names"][0] != "keepa://toolsets/{toolset}":
        raise AssertionError("SDK typed list_resource_templates must start with keepa://toolsets/{toolset}")
    tool_call = responses["tools/call"]["result"]
    if not tool_call.get("isError"):
        raise AssertionError("SDK typed invalid tools/call should return isError=true")
    if not _contains_text(tool_call.get("structuredContent"), "invalid_arguments"):
        raise AssertionError("SDK typed invalid tools/call lost invalid_arguments error kind")
    if not _contains_text(tool_call.get("structuredContent"), "missing required argument: term"):
        raise AssertionError("SDK typed invalid tools/call lost validation detail")
    if responses["ping"]["result"] != {}:
        raise AssertionError("SDK typed ping should return an empty result")

    fixture_methods = [step["method"] for step in spec["steps"]]
    mapped_methods = [response["method"] for response in payload["responses"]]
    if fixture_methods != mapped_methods:
        raise AssertionError(f"typed fixture methods mismatch: {mapped_methods!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用官方 MCP SDK typed client 映射 Inspector fixture。")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="Inspector MCP fixture JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    parser.add_argument("--skip-if-missing", action="store_true", help="Return success when the optional mcp package is missing.")
    args = parser.parse_args(argv)

    if importlib.util.find_spec("mcp") is None:
        message = "official mcp package is not installed"
        if args.skip_if_missing:
            payload = {"ok": True, "skipped": True, "reason": message}
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"mcp sdk typed fixture skipped: {message}")
            return 0
        print(message, file=sys.stderr)
        return 1

    spec = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    if spec.get("kind") != "mcp_session":
        raise SystemExit("typed SDK fixture mapping only supports mcp_session fixtures")
    payload = asyncio.run(_run_fixture(spec))
    _assert_typed_payload(payload, spec)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        tools = next(response for response in payload["responses"] if response["method"] == "tools/list")["result"]
        print(f"mcp sdk typed fixture ok: {tools['total_count']} tools over {tools['page_count']} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
