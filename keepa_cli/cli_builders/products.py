"""
keepa_cli/cli_builders/products.py
文件说明：products 命令族 argparse 构造与分发。
主要职责：注册产品查询命令，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.service import run_command


def add_products_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    products = subparsers.add_parser("products", help="产品查询命令。")
    products_subparsers = products.add_subparsers(dest="products_command")
    products_get = products_subparsers.add_parser("get", help="按 ASIN 或 code 查询产品。")
    products_get.add_argument("asin", nargs="*", help="一个或多个 ASIN。")
    products_get.add_argument("--code", action="append", default=[], help="UPC、EAN 或 ISBN-13，可重复。")
    products_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_get.add_argument("--full", action="store_true", help="低成本完整详情预设：history=1、stats=0、videos=1、aplus=1。")
    products_get.add_argument("--stats-window", default="0", help="--full 使用的 stats 天数窗口；0 表示全历史/最大窗口。")
    products_get.add_argument("--history", help="0 表示排除历史字段，1 表示包含。")
    products_get.add_argument("--stats", help="统计窗口，例如 90 或日期区间。")
    products_get.add_argument("--days", help="限制历史数据天数，降低响应体大小。")
    products_get.add_argument("--update", help="刷新阈值小时；0 可能额外消耗 token。")
    products_get.add_argument("--offers", help="请求 offer 数，官方范围 20-100，会显著消耗 token。")
    products_get.add_argument("--code-limit", help="按 code 查询时限制返回商品数量。")
    products_get.add_argument("--only-live-offers", help="配合 --offers 使用，仅返回 live offers。")
    products_get.add_argument("--videos", help="1 表示包含视频信息。")
    products_get.add_argument("--aplus", help="1 表示包含 A+ 内容信息。")
    products_get.add_argument("--rating", help="1 表示包含 rating 与 review count 历史。")
    products_get.add_argument("--buybox", help="1 表示包含 Buy Box 历史。")
    products_get.add_argument("--stock", help="1 表示包含 stock 信息，通常需配合 offers。")
    products_get.add_argument("--historical-variations", help="1 表示包含历史 variation 数据。")
    products_get.add_argument("--agent-view", action="store_true", help="返回 Agent 友好的稳定摘要视图，省略原始大 body。")
    products_get.add_argument(
        "--view",
        choices=("raw", "agent", "summary", "research", "deal", "audit"),
        default="raw",
        help="输出视图；raw 为默认原始 Keepa body，其余为 Agent profile。",
    )
    products_get.add_argument("--fields", help="逗号分隔 Agent 视图字段，例如 identity,pricing,demand,rating。")
    products_get.add_argument("--history-limit", type=int, default=10, help="Agent 视图中每个历史序列保留的最近点数。")
    products_get.add_argument("--temporal-window-days", action="append", default=[], help="Agent 时序特征窗口天数，可重复或逗号分隔。")
    products_get.add_argument("--chunks-dir", help="把 Agent 视图关键 section 分块写入目录。")
    products_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_get.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    products_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(products_get)

    products_compare = products_subparsers.add_parser("compare", help="横向对比一个或多个 ASIN 的 Agent-safe 选品字段。")
    products_compare.add_argument("asin", nargs="+", help="一个或多个 ASIN。")
    products_compare.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_compare.add_argument("--full", action="store_true", help="低成本完整详情预设：history=1、stats=0、videos=1、aplus=1。")
    products_compare.add_argument("--stats-window", default="0", help="--full 使用的 stats 天数窗口；0 表示全历史/最大窗口。")
    products_compare.add_argument("--view", choices=("summary", "research", "deal", "audit"), default="deal", help="对比前使用的 Agent profile。")
    products_compare.add_argument("--fields", help="逗号分隔 Agent 视图字段。")
    products_compare.add_argument("--history-limit", type=int, default=5, help="每个历史序列保留的最近点数。")
    products_compare.add_argument(
        "--keep-history-points",
        action="store_true",
        help="在每个 ASIN 对比行中保留 bounded history points，便于离线多 ASIN 时序图。",
    )
    products_compare.add_argument("--temporal-window-days", action="append", default=[], help="Agent 时序特征窗口天数，可重复或逗号分隔。")
    products_compare.add_argument("--offers", help="请求 offer 数，官方范围 20-100，会显著消耗 token。")
    products_compare.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_compare.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    products_compare.add_argument("--chunks-dir", help="把 Agent 视图关键 section 分块写入目录。")
    products_compare.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(products_compare)

    products_search = products_subparsers.add_parser("search", help="产品关键词搜索。")
    products_search.add_argument("term", help="搜索词。")
    products_search.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_search.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_search.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(products_search)

    products_by_code = products_subparsers.add_parser("by-code", help="按 UPC、EAN 或 ISBN-13 查询产品。")
    products_by_code.add_argument("code", nargs="+", help="一个或多个 UPC、EAN 或 ISBN-13。")
    products_by_code.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_by_code.add_argument("--code-limit", help="限制按 code 查询返回的商品数量。")
    products_by_code.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_by_code.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    products_by_code.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(products_by_code)

    products_summary = products_subparsers.add_parser("summary", help="返回 Agent-safe 产品摘要。")
    products_summary.add_argument("asin", nargs="+", help="一个或多个 ASIN。")
    products_summary.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_summary.add_argument("--view", choices=("summary", "research", "deal", "audit"), default="summary", help="摘要 profile。")
    products_summary.add_argument("--fields", help="逗号分隔 Agent 视图字段。")
    products_summary.add_argument("--history-limit", type=int, default=10, help="每个历史序列保留的最近点数。")
    products_summary.add_argument("--temporal-window-days", action="append", default=[], help="Agent 时序特征窗口天数，可重复或逗号分隔。")
    products_summary.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_summary.add_argument("--chunks-dir", help="把 Agent 视图关键 section 分块写入目录。")
    products_summary.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(products_summary)


def maybe_run_products_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "products" and args.products_command == "get":
        payload = run_command(
            "products.get",
            {
                "asin": args.asin,
                "code": args.code,
                "domain": args.domain,
                "full": bool(args.full),
                "stats_window": args.stats_window,
                "history": args.history,
                "stats": args.stats,
                "days": args.days,
                "update": args.update,
                "offers": args.offers,
                "code_limit": args.code_limit,
                "only_live_offers": args.only_live_offers,
                "videos": args.videos,
                "aplus": args.aplus,
                "rating": args.rating,
                "buybox": args.buybox,
                "stock": args.stock,
                "historical_variations": args.historical_variations,
                "agent_view": bool(args.agent_view),
                "view": args.view,
                "fields": args.fields,
                "history_limit": args.history_limit,
                "temporal_windows": args.temporal_window_days,
                "chunks_dir": args.chunks_dir,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "products" and args.products_command == "compare":
        payload = run_command(
            "products.compare",
            {
                "asin": args.asin,
                "domain": args.domain,
                "full": bool(args.full),
                "stats_window": args.stats_window,
                "view": args.view,
                "fields": args.fields,
                "history_limit": args.history_limit,
                "keep_history_points": bool(args.keep_history_points),
                "temporal_windows": args.temporal_window_days,
                "offers": args.offers,
                "fixture": args.fixture,
                "out": args.out,
                "chunks_dir": args.chunks_dir,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "products" and args.products_command == "search":
        payload = run_command(
            "products.search",
            {
                "term": args.term,
                "domain": args.domain,
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "products" and args.products_command == "by-code":
        payload = run_command(
            "products.get",
            {
                "code": args.code,
                "domain": args.domain,
                "code_limit": args.code_limit,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "products" and args.products_command == "summary":
        payload = run_command(
            "products.get",
            {
                "asin": args.asin,
                "domain": args.domain,
                "agent_view": True,
                "view": args.view,
                "fields": args.fields,
                "history_limit": args.history_limit,
                "temporal_windows": args.temporal_window_days,
                "fixture": args.fixture,
                "chunks_dir": args.chunks_dir,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
