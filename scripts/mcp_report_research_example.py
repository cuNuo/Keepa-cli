"""
scripts/mcp_report_research_example.py
文件说明：演示 Agent 如何通过 MCP 执行纯本地 report-research 工作流。
主要职责：把本地 fixture 图谱合并为 graph，再导出 brief、browse snapshot 和 report。
依赖边界：仅读取本地 fixture，报告和浏览快照写入临时目录，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mcp_example_support import KeepaMcpClient, add_common_example_args, emit_summary, graph_counts, research_resource_uri, tool_names


def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    client = KeepaMcpClient([args.python, "-m", "keepa_cli", "--mcp"])
    try:
        initialize = client.request("initialize", {"clientInfo": {"name": "keepa-mcp-report-research-example", "version": "1"}})
        tool_list = client.request("tools/list", {"toolset": "reports", "profile": "offline_fixture_only"})
        workflow_plan = client.call_tool("keepa.workflow_plan", {"name": "report-research", "domain": args.domain, "goal": args.goal})
        with tempfile.TemporaryDirectory(prefix="keepa-report-example-") as temp_dir:
            graph_path = str(Path(temp_dir) / "merged-research-graph.json")
            browse_dir = str(Path(temp_dir) / "browse")
            figures_dir = str(Path(temp_dir) / "figures")
            merged = client.call_tool(
                "keepa.research_graph_merge",
                {
                    "input": args.input,
                    "root": args.graph_root,
                    "label": "MCP report research example graph",
                    "out": graph_path,
                },
            )
            merged_resource_uri = research_resource_uri(str(merged["cache_key"]))
            merged_graph_uri = research_resource_uri(str(merged["cache_key"]), "/graph")
            brief = client.call_tool("keepa.research_brief_export", {"resource_uri": merged_resource_uri, "title": args.title})
            browse = client.call_tool(
                "keepa.browse_snapshot",
                {
                    "resource_uri": merged_resource_uri,
                    "out_dir": browse_dir,
                    "title": f"{args.title} Browse",
                },
            )
            figures_result = client.call_tool_result(
                "keepa.figures_research",
                {
                    "resource_uri": merged_resource_uri,
                    "out_dir": figures_dir,
                    "title": f"{args.title} Figures",
                },
            )
            figures = figures_result["structuredContent"]
            report = client.call_tool(
                "keepa.reports_build",
                {
                    "workflow_context": {
                        "steps": {"merge": {"artifact": merged}},
                        "outputs": {"merged_graph": {"output": {"path": graph_path}}},
                    },
                    "format": "json",
                    "title": args.title,
                },
            )
            graph_file = Path(graph_path)
            browse_index = Path(browse["data"]["index"])
            svg_resource = _first_svg_resource(figures_result)
            return {
                "ok": True,
                "mcp": {
                    "server": initialize.get("serverInfo"),
                    "toolset": tool_list.get("toolset"),
                    "profile": tool_list.get("profile"),
                    "tools": tool_names(tool_list),
                },
                "workflow_plan": {
                    "cache_key": workflow_plan["cache_key"],
                    "recommended_toolset": workflow_plan["data"]["workflow_policy"]["recommended_toolset"],
                    "recommended_profile": workflow_plan["data"]["workflow_policy"]["recommended_profile"],
                    "estimated_tokens": workflow_plan["data"]["totals"]["estimated_tokens"],
                    "root_next_actions": len(workflow_plan["data"].get("next_actions") or []),
                },
                "steps": {
                    "graph_merge": {
                        "cache_key": merged["cache_key"],
                        "resource_uri": merged_resource_uri,
                        "graph_resource_uri": merged_graph_uri,
                        "entity_counts": graph_counts(merged),
                        "output_path": graph_path,
                        "output_exists_during_run": graph_file.exists(),
                    },
                    "brief": {
                        "cache_key": brief["cache_key"],
                        "resource_uri": research_resource_uri(str(brief["cache_key"]), "/brief"),
                        "one_line": brief["data"]["brief"]["decision_summary"]["one_line"],
                        "recommended_read_order": brief["data"]["brief"].get("recommended_read_order", []),
                    },
                    "browse": {
                        "cache_key": browse["cache_key"],
                        "index": browse["data"]["index"],
                        "row_count": browse["data"].get("row_count"),
                        "index_exists_during_run": browse_index.exists(),
                    },
                    "figures": {
                        "cache_key": figures["cache_key"],
                        "figure_count": len(figures["data"].get("figures", [])),
                        "svg_path": figures["data"].get("figures", [{}])[0].get("path"),
                        "svg_resource_uri": svg_resource.get("uri"),
                        "svg_mime_type": svg_resource.get("mimeType"),
                        "data_summary": figures["data"].get("data_summary", {}),
                    },
                    "report": {
                        "cache_key": report["cache_key"],
                        "format": report["data"].get("format"),
                        "research_graph_counts": report["data"].get("research_graph", {}).get("entity_counts", {}),
                        "workflow_resolution_temp_paths": report["data"].get("workflow_resolution", {}).get("temp_paths", []),
                    },
                },
                "budget_ledger": report.get("budget_ledger", {}),
            }
    finally:
        client.close()


def _first_svg_resource(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content") if isinstance(result.get("content"), list) else []
    if not content or not isinstance(content[0], dict):
        return {}
    try:
        text_payload = json.loads(str(content[0].get("text") or "{}"))
    except json.JSONDecodeError:
        return {}
    manifest = text_payload.get("mcp_resource_manifest") if isinstance(text_payload, dict) else {}
    resources = manifest.get("resources") if isinstance(manifest, dict) and isinstance(manifest.get("resources"), list) else []
    for resource in resources:
        if isinstance(resource, dict) and resource.get("mimeType") == "image/svg+xml":
            return resource
    return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local report-research MCP example.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary. Default output is JSON as well.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to start `python -m keepa_cli --mcp`.")
    parser.add_argument("--domain", default="US")
    parser.add_argument("--goal", default="deal")
    parser.add_argument("--input", default="tests/fixtures/agent_eval_products_compare_output.json")
    parser.add_argument("--graph-root", default="mcp-report-example-research")
    parser.add_argument("--title", default="MCP Report Research Example")
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
