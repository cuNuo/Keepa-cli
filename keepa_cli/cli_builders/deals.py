"""
keepa_cli/cli_builders/deals.py
文件说明：deals 命令族 argparse 构造与分发。
主要职责：注册 Keepa deals 查询命令，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.service import run_command


def add_deals_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    deals = subparsers.add_parser("deals", help="Keepa deals 查询命令。")
    deals_subparsers = deals.add_subparsers(dest="deals_command")
    deals_query = deals_subparsers.add_parser("query", help="按 selection JSON 查询 deals。")
    deals_query.add_argument("--selection-file", required=True, help="Keepa deals selection JSON 文件。")
    deals_query.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    deals_query.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    deals_query.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    deals_query.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(deals_query)


def maybe_run_deals_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "deals" and args.deals_command == "query":
        payload = run_command(
            "deals.query",
            {
                "selection_file": args.selection_file,
                "domain": args.domain,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
