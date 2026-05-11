"""
scripts/mcp_tracking_audit_example.py
文件说明：演示 Agent 如何通过 MCP 执行只读 tracking-audit 工作流。
主要职责：展示 tracking-readonly toolset、tracking_readonly profile 与只读参数质量。
依赖边界：仅使用本地 fixture 和 dry-run，不访问真实 Keepa API，不暴露 tracking 写工具。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from mcp_example_support import KeepaMcpClient, McpClientError, add_common_example_args, emit_summary, research_resource_uri, tool_names


def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    client = KeepaMcpClient([args.python, "-m", "keepa_cli", "--mcp"])
    try:
        initialize = client.request("initialize", {"clientInfo": {"name": "keepa-mcp-tracking-audit-example", "version": "1"}})
        tool_list = client.request("tools/list", {"toolset": "tracking-readonly", "profile": "tracking_readonly"})
        tools = tool_names(tool_list)
        workflow_plan = client.call_tool(
            "keepa.workflow_plan",
            {"name": "tracking-audit", "domain": args.domain, "asin": args.asin},
        )
        tracking_list = client.call_tool(
            "keepa.tracking_list",
            {
                "domain": args.domain,
                "asins_only": True,
                "fixture": args.fixture,
                "profile": "tracking_readonly",
            },
        )
        tracking_resource_uri = research_resource_uri(str(tracking_list["cache_key"]))
        tracking_detail = client.call_tool(
            "keepa.tracking_get",
            {
                "resource_uri": tracking_resource_uri,
                "domain": args.domain,
                "dry_run": True,
                "profile": "tracking_readonly",
            },
        )
        notifications = client.call_tool(
            "keepa.tracking_notifications",
            {
                "domain": args.domain,
                "since": 0,
                "revise": True,
                "dry_run": True,
                "profile": "tracking_readonly",
            },
        )
        cost = client.call_tool(
            "keepa.audit_cost",
            {
                "resource_uri": tracking_resource_uri,
                "target_command": "tracking.get",
                "params": {"domain": args.domain},
                "profile": "tracking_readonly",
            },
        )
        blocked_error = None
        try:
            client.call_tool("keepa.tracking_add", {"tracking": [{"asin": args.asin, "domain": 1}], "dry_run": True})
        except McpClientError as exc:
            blocked_error = str(exc)
        return {
            "ok": True,
            "mcp": {
                "server": initialize.get("serverInfo"),
                "toolset": tool_list.get("toolset"),
                "profile": tool_list.get("profile"),
                "tools": tools,
                "write_tools_exposed": sorted(name for name in tools if name in {"keepa.tracking_add", "keepa.tracking_remove", "keepa.tracking_webhook"}),
            },
            "workflow_plan": {
                "cache_key": workflow_plan["cache_key"],
                "recommended_toolset": workflow_plan["data"]["workflow_policy"]["recommended_toolset"],
                "recommended_profile": workflow_plan["data"]["workflow_policy"]["recommended_profile"],
                "confirmation_steps": workflow_plan["data"]["workflow_policy"]["confirmation_policy"]["step_ids"],
                "estimated_tokens": workflow_plan["data"]["totals"]["estimated_tokens"],
            },
            "steps": {
                "tracking_list": {
                    "cache_key": tracking_list["cache_key"],
                    "resource_uri": tracking_resource_uri,
                    "asins": [item.get("asin") for item in tracking_list["data"].get("body", {}).get("trackings", []) if item.get("asin")],
                    "request_type": tracking_list.get("request", {}).get("params_redacted", {}).get("type"),
                },
                "tracking_get": {
                    "cache_key": tracking_detail["cache_key"],
                    "derived_asin": tracking_detail["data"].get("workflow_resolution", {}).get("derived_values", {}).get("tracking_asins", [None])[0],
                    "request_type": tracking_detail.get("request", {}).get("params_redacted", {}).get("type"),
                    "dry_run": bool(tracking_detail.get("request", {}).get("dry_run")),
                },
                "notifications": {
                    "cache_key": notifications["cache_key"],
                    "request_type": notifications.get("request", {}).get("params_redacted", {}).get("type"),
                    "revise": notifications.get("request", {}).get("params_redacted", {}).get("revise"),
                    "dry_run": bool(notifications.get("request", {}).get("dry_run")),
                },
                "cost": {
                    "cache_key": cost["cache_key"],
                    "target_command": cost["data"].get("items", [{}])[0].get("command"),
                    "estimated_tokens": cost["data"].get("totals", {}).get("estimated_tokens"),
                    "derived_asin": cost["data"].get("workflow_resolution", {}).get("derived_values", {}).get("tracking_asins", [None])[0],
                },
                "write_boundary": {
                    "attempted_tool": "keepa.tracking_add",
                    "blocked": bool(blocked_error),
                    "error": blocked_error,
                },
            },
            "budget_ledger": cost.get("budget_ledger", {}),
        }
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an offline tracking-audit MCP example.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary. Default output is JSON as well.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to start `python -m keepa_cli --mcp`.")
    parser.add_argument("--domain", default="US")
    parser.add_argument("--asin", default="B09YNQCQKR")
    parser.add_argument("--fixture", default="tracking_list.json")
    add_common_example_args(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_workflow(args)
    except Exception as exc:
        emit_summary({"ok": False, "error": {"kind": type(exc).__name__, "message": str(exc)}}, args.save_summary)
        return 1
    emit_summary(summary, args.save_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
