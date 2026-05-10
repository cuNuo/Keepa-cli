"""
keepa_cli/cli_builders/categories.py
文件说明：categories 命令族 argparse 构造与分发。
主要职责：注册分类查询命令，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.service import run_command


def add_categories_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    categories = subparsers.add_parser("categories", help="分类查询命令。")
    categories_subparsers = categories.add_subparsers(dest="categories_command")
    categories_get = categories_subparsers.add_parser("get", help="按 category id 查询分类。")
    categories_get.add_argument("category", nargs="+", help="一个或多个 category id，0 表示 root categories。")
    categories_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    categories_get.add_argument("--parents", action="store_true", help="包含父级分类树。")
    categories_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    categories_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(categories_get)

    categories_search = categories_subparsers.add_parser("search", help="分类关键词搜索。")
    categories_search.add_argument("term", help="搜索词，多个关键词需全部匹配。")
    categories_search.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    categories_search.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    categories_search.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(categories_search)

    categories_finder = categories_subparsers.add_parser("finder-selection", help="从 category id 生成本地 Finder selection 草稿。")
    categories_finder.add_argument("category", help="Keepa category id。")
    categories_finder.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    categories_finder.add_argument("--per-page", type=int, default=50, help="Finder perPage 草稿值。")
    categories_finder.add_argument("--sales-rank-max", type=int, default=20000, help="current_SALES_lte 草稿值。")
    categories_finder.add_argument("--min-reviews", type=int, default=50, help="current_COUNT_REVIEWS_gte 草稿值。")
    categories_finder.add_argument("--out", help="把 selection JSON 写入文件。")

    categories_products = categories_subparsers.add_parser("products", help="按 category id 取相关商品候选。")
    categories_products.add_argument("category", help="Keepa category id。")
    categories_products.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    categories_products.add_argument("--limit", type=int, default=25, help="返回候选 ASIN 上限。")
    categories_products.add_argument("--hydrate-top", type=int, default=0, help="显式拉取前 N 个商品的 Agent summary；默认 0 不额外耗 token。")
    categories_products.add_argument("--product-fixture", help="hydrate-top 使用的产品 fixture，用于离线测试。")
    categories_products.add_argument("--history-limit", type=int, default=3, help="hydrate 产品摘要中每个历史序列保留的最近点数。")
    categories_products.add_argument("--temporal-window-days", action="append", default=[], help="hydrate 产品摘要的 Agent 时序窗口，可重复或逗号分隔。")
    categories_products.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    categories_products.add_argument("--out", help="把原始 body 写入 JSON 文件。")
    categories_products.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(categories_products)


def maybe_run_categories_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "categories" and args.categories_command == "get":
        payload = run_command(
            "categories.get",
            {
                "category": args.category,
                "domain": args.domain,
                "parents": bool(args.parents),
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "categories" and args.categories_command == "search":
        payload = run_command(
            "categories.search",
            {
                "term": args.term,
                "domain": args.domain,
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "categories" and args.categories_command == "finder-selection":
        payload = run_command(
            "categories.finder-selection",
            {
                "category": args.category,
                "domain": args.domain,
                "per_page": args.per_page,
                "sales_rank_max": args.sales_rank_max,
                "min_reviews": args.min_reviews,
                "out": args.out,
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "categories" and args.categories_command == "products":
        payload = run_command(
            "categories.products",
            {
                "category": args.category,
                "domain": args.domain,
                "limit": args.limit,
                "hydrate_top": args.hydrate_top,
                "product_fixture": args.product_fixture,
                "history_limit": args.history_limit,
                "temporal_windows": args.temporal_window_days,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
