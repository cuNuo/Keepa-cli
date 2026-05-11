"""
scripts/mcp_agent_workflow_example.py
文件说明：演示 Agent 如何通过 MCP stdio 串联 Keepa-cli 离线调研工作流。
主要职责：执行 workflow.plan -> resource_uri -> risk schema validation -> graph/brief/report。
依赖边界：仅使用 Python 标准库和本地 fixture，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from mcp_example_support import (
    RISK_SCHEMA_URI,
    KeepaMcpClient,
    add_common_example_args,
    emit_summary,
    graph_counts,
    research_resource_uri,
    risk_schema_summary,
    tool_names,
    validate_risk_taxonomy,
)


def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    client = KeepaMcpClient([args.python, "-m", "keepa_cli", "--mcp"])
    try:
        initialize = client.request("initialize", {"clientInfo": {"name": "keepa-mcp-agent-workflow-example", "version": "1"}})
        tool_list = client.request(
            "tools/list",
            {
                "toolset": "all",
                "profile": "offline_fixture_only",
                "allow_tools": [
                    "keepa.workflow_plan",
                    "keepa.categories_products",
                    "keepa.products_compare",
                    "keepa.research_graph_merge",
                    "keepa.research_brief_export",
                    "keepa.reports_build",
                ],
            },
        )
        workflow_plan = client.call_tool(
            "keepa.workflow_plan",
            {"name": "category-research", "term": args.term, "domain": args.domain, "goal": args.goal, "hydrate_top": 0},
        )
        risk_schema = client.read_resource_json(RISK_SCHEMA_URI)
        category_products = client.call_tool(
            "keepa.categories_products",
            {
                "category": args.category,
                "domain": args.domain,
                "fixture": args.category_fixture,
                "limit": args.limit,
                "yes": True,
            },
        )
        category_resource_uri = research_resource_uri(str(category_products["cache_key"]))
        compare = client.call_tool(
            "keepa.products_compare",
            {
                "resource_uri": category_resource_uri,
                "domain": args.domain,
                "fixture": args.compare_fixture,
                "full": True,
                "view": "deal",
            },
        )
        risk_validation = validate_risk_taxonomy([compare], risk_schema)
        compare_graph_uri = research_resource_uri(str(compare["cache_key"]), "/graph")
        merged = client.call_tool(
            "keepa.research_graph_merge",
            {"resource_uri": compare_graph_uri, "root": args.graph_root, "label": "MCP client example research graph"},
        )
        merged_resource_uri = research_resource_uri(str(merged["cache_key"]))
        merged_graph_uri = research_resource_uri(str(merged["cache_key"]), "/graph")
        brief = client.call_tool(
            "keepa.research_brief_export",
            {"resource_uri": merged_resource_uri, "title": args.report_title},
        )
        brief_resource_uri = research_resource_uri(str(brief["cache_key"]), "/brief")
        report = client.call_tool(
            "keepa.reports_build",
            {"resource_uri": merged_resource_uri, "format": "json", "title": args.report_title},
        )
        return {
            "ok": True,
            "mcp": {
                "server": initialize.get("serverInfo"),
                "tool_count": len(tool_names(tool_list)),
                "tools": tool_names(tool_list),
            },
            "steps": {
                "workflow_plan": {
                    "cache_key": workflow_plan["cache_key"],
                    "recommended_profile": workflow_plan["data"]["workflow_policy"]["recommended_profile"],
                    "estimated_tokens": workflow_plan["data"]["totals"]["estimated_tokens"],
                    "root_next_actions": len(workflow_plan["data"].get("next_actions") or []),
                    "resource_templates": workflow_plan["data"].get("resource_templates") or [],
                },
                "category_products": {
                    "cache_key": category_products["cache_key"],
                    "resource_uri": category_resource_uri,
                    "asins": category_products["data"].get("asins", []),
                },
                "products_compare": {
                    "cache_key": compare["cache_key"],
                    "resource_uri": research_resource_uri(str(compare["cache_key"])),
                    "graph_resource_uri": compare_graph_uri,
                    "product_count": compare["data"].get("product_count"),
                    "resolved_asins": compare["data"].get("workflow_resolution", {}).get("derived_values", {}).get("asins", []),
                },
                "graph_merge": {
                    "cache_key": merged["cache_key"],
                    "resource_uri": merged_resource_uri,
                    "graph_resource_uri": merged_graph_uri,
                    "entity_counts": graph_counts(merged),
                    "diagnostics": merged["data"].get("summary", {}).get("diagnostics", {}),
                },
                "brief": {
                    "cache_key": brief["cache_key"],
                    "resource_uri": brief_resource_uri,
                    "one_line": brief["data"]["brief"]["decision_summary"]["one_line"],
                    "risk_summary": brief["data"]["brief"].get("risk_summary", {}),
                },
                "report": {
                    "cache_key": report["cache_key"],
                    "format": report["data"].get("format"),
                    "research_graph_counts": report["data"].get("research_graph", {}).get("entity_counts", {}),
                },
            },
            "risk_schema": risk_schema_summary(risk_schema),
            "risk_validation": risk_validation,
            "budget_ledger": report.get("budget_ledger", {}),
        }
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an offline Keepa MCP Agent workflow example.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary. Default output is JSON as well for copy/paste.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to start `python -m keepa_cli --mcp`.")
    parser.add_argument("--domain", default="US")
    parser.add_argument("--term", default="home kitchen")
    parser.add_argument("--category", default="1055398")
    parser.add_argument("--goal", default="deal")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--category-fixture", default="bestsellers_home.json")
    parser.add_argument("--compare-fixture", default="products_compare_agent_eval.json")
    parser.add_argument("--graph-root", default="mcp-client-example-research")
    parser.add_argument("--report-title", default="MCP Agent Workflow Example")
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
