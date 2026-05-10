"""
keepa_cli/cli_builders/research_graph.py
文件说明：注册 research_graph 本地处理 CLI 命令。
主要职责：提供 graph merge 命令参数与执行分发。
依赖边界：只解析本地 JSON 文件，不访问 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.service import run_command


def add_research_graph_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    research_graph = subparsers.add_parser("research-graph", help="Agent research_graph 本地处理命令。")
    graph_subparsers = research_graph.add_subparsers(dest="research_graph_command")
    merge = graph_subparsers.add_parser("merge", help="合并多个 JSON 输出中的 research_graph。")
    merge.add_argument("input", nargs="+", help="包含 research_graph 字段的 JSON 文件，可传多个。")
    merge.add_argument("--root", default="merged_research_graph", help="合并后 graph root id。")
    merge.add_argument("--label", default="merged research graph", help="合并 graph 标签。")
    merge.add_argument("--out", help="只把合并后的 graph 写入 JSON 文件。")


def maybe_run_research_graph_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "research-graph" and args.research_graph_command == "merge":
        payload = run_command(
            "research_graph.merge",
            {"input": list(args.input), "root": args.root, "label": args.label, "out": args.out},
        )
        return 0 if payload["ok"] else 1, payload
    return None
