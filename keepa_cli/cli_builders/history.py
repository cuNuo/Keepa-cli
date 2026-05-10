"""
keepa_cli/cli_builders/history.py
文件说明：history 命令族 argparse 构造与分发。
主要职责：注册历史导出和趋势分析命令，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.service import run_command


def add_history_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    history = subparsers.add_parser("history", help="历史导出与趋势分析命令。")
    history_subparsers = history.add_subparsers(dest="history_command")

    history_export = history_subparsers.add_parser("export", help="展开 Keepa Product csv 历史。")
    history_export.add_argument("asin", help="一个 ASIN。")
    history_export.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    history_export.add_argument("--series", default="amazon,new,used,sales_rank", help="逗号分隔序列，例如 amazon,new,sales_rank。")
    history_export.add_argument("--format", choices=("json", "jsonl", "csv"), default="json", help="导出格式。")
    history_export.add_argument("--out", help="写入文件路径；不提供时写入 JSON envelope data。")
    history_export.add_argument("--include-missing", action="store_true", help="保留 Keepa -1 缺失值。")
    history_export.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    history_export.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(history_export)

    history_trend = history_subparsers.add_parser("trend", help="分析 Keepa Product csv 趋势。")
    history_trend.add_argument("asin", help="一个 ASIN。")
    history_trend.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    history_trend.add_argument("--series", default="amazon,new,used,sales_rank", help="逗号分隔序列，例如 amazon,new,sales_rank。")
    history_trend.add_argument("--window-days", action="append", type=int, default=[], help="趋势窗口天数，可重复。")
    history_trend.add_argument("--include-missing", action="store_true", help="保留 Keepa -1 缺失值。")
    history_trend.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    history_trend.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(history_trend)


def maybe_run_history_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "history" and args.history_command == "export":
        payload = run_command(
            "history.export",
            {
                "asin": args.asin,
                "domain": args.domain,
                "series": args.series,
                "format": args.format,
                "out": args.out,
                "include_missing": bool(args.include_missing),
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "history" and args.history_command == "trend":
        payload = run_command(
            "history.trend",
            {
                "asin": args.asin,
                "domain": args.domain,
                "series": args.series,
                "window_days": args.window_days,
                "include_missing": bool(args.include_missing),
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
