"""
keepa_cli/cli_builders/finder.py
文件说明：finder 命令族 argparse 构造与分发。
主要职责：注册 Product Finder 查询命令，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.service import run_command


def add_finder_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    finder = subparsers.add_parser("finder", help="Product Finder 高价值查询命令。")
    finder_subparsers = finder.add_subparsers(dest="finder_command")
    finder_query = finder_subparsers.add_parser("query", help="按 selection JSON 查询 ASIN 列表。")
    finder_query.add_argument("--selection-file", required=True, help="Keepa Product Finder selection JSON 文件。")
    finder_query.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    finder_query.add_argument("--max-tokens", type=int, default=10, help="Agent 预算上限提示。")
    finder_query.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    finder_query.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    finder_query.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(finder_query)


def maybe_run_finder_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "finder" and args.finder_command == "query":
        payload = run_command(
            "finder.query",
            {
                "selection_file": args.selection_file,
                "domain": args.domain,
                "max_tokens": args.max_tokens,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
