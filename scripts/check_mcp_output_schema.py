"""
scripts/check_mcp_output_schema.py
文件说明：MCP outputSchema 离线门禁。
主要职责：校验代表性 tools/call 成功与错误响应的 structuredContent 符合对应 outputSchema。
依赖边界：只使用本地 fixture/dry-run，不访问真实 Keepa API；不在热路径执行 schema 校验。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent.mcp import handle_mcp_message
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import _validate_json_schema, get_tool_definition


CASES: tuple[dict[str, Any], ...] = (
    {"name": "context_policy", "arguments": {}},
    {"name": "products_get", "arguments": {"asin": "B001", "domain": "US", "fixture": "product_B001GZ6QEC.json", "view": "summary"}},
    {"name": "categories_search", "arguments": {"domain": "US", "extra": True}, "expect_error_kind": "invalid_arguments"},
)


def _call_tool(name: str, arguments: Mapping[str, Any], *, session: AgentSession) -> dict[str, Any]:
    response = handle_mcp_message(
        json.dumps({"jsonrpc": "2.0", "id": name, "method": "tools/call", "params": {"name": name, "arguments": dict(arguments)}}),
        env={},
        session=session,
    )
    if response is None:
        raise AssertionError(f"{name} returned no response")
    if response.get("error"):
        raise AssertionError(f"{name} returned JSON-RPC error: {response['error']}")
    return response


def run_check() -> dict[str, Any]:
    session = AgentSession(env={})
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in CASES:
        name = str(case["name"])
        tool = get_tool_definition(name)
        if tool is None:
            failures.append(f"unknown tool in output schema check: {name}")
            continue
        response = _call_tool(name, case.get("arguments") or {}, session=session)
        structured = response.get("result", {}).get("structuredContent")
        errors = _validate_json_schema(tool.output_schema, structured)
        error_kind = None
        if isinstance(structured, Mapping):
            error = structured.get("error")
            if isinstance(error, Mapping):
                error_kind = error.get("kind")
        expected_error_kind = case.get("expect_error_kind")
        if expected_error_kind and error_kind != expected_error_kind:
            errors.append(f"expected error.kind={expected_error_kind}, got {error_kind}")
        if errors:
            failures.extend(f"{name}: {error}" for error in errors)
        results.append(
            {
                "tool": name,
                "isError": response.get("result", {}).get("isError"),
                "error_kind": error_kind,
                "schema_errors": errors,
            }
        )
    return {"ok": not failures, "cases": results, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 MCP tools/call outputSchema。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    args = parser.parse_args(argv)
    payload = run_check()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif payload["ok"]:
        print(f"mcp output schema ok: {len(payload['cases'])} cases")
    else:
        for failure in payload["failures"]:
            print(failure, file=sys.stderr)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
