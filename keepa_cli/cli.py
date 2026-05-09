"""
keepa_cli/cli.py
文件说明：提供 keepa-cli 与 kc 共用的命令行入口。
主要职责：解析参数、输出 JSON envelope，并把业务调用委托给 Agent-safe service。
依赖边界：仅依赖包内稳定模块和 Python 标准库，不直接保存凭据。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from keepa_cli import __version__
from keepa_cli.agent.stdio import iter_stdio_output
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.service import run_command
from keepa_cli.ui.tui import run_interactive_tui


def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keepa-cli",
        description="Agent-first Keepa API CLI. kc is an equivalent short entry point.",
    )
    parser.add_argument("--version", action="version", version=f"keepa-cli {__version__}")
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON envelope，供 Agent 调用。")
    parser.add_argument("--stdio", action="store_true", help="启用 JSON Lines 长会话协议。")
    parser.add_argument("--yes", action="store_true", help="确认执行可能消耗较高 token 的请求。")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="检查认证、fixture/offline 与双入口配置。")

    config = subparsers.add_parser("config", help="查看或初始化本地配置。")
    config_subparsers = config.add_subparsers(dest="config_command")
    config_show = config_subparsers.add_parser("show", help="显示当前有效配置。")
    config_show.add_argument("--path", help="指定配置文件路径。")
    config_init = config_subparsers.add_parser("init", help="生成默认配置文件。")
    config_init.add_argument("--path", help="指定配置文件路径。")
    config_init.add_argument("--dry-run", action="store_true", help="只输出将写入的配置，不落盘。")

    domains = subparsers.add_parser("domains", help="Keepa domain 发现命令。")
    domains_subparsers = domains.add_subparsers(dest="domains_command")
    domains_subparsers.add_parser("list", help="列出 Keepa 支持的 Amazon domain。")

    products = subparsers.add_parser("products", help="产品查询命令。")
    products_subparsers = products.add_subparsers(dest="products_command")
    products_get = products_subparsers.add_parser("get", help="按 ASIN 或 code 查询产品。")
    products_get.add_argument("asin", nargs="*", help="一个或多个 ASIN。")
    products_get.add_argument("--code", action="append", default=[], help="UPC、EAN 或 ISBN-13，可重复。")
    products_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_get.add_argument("--history", help="0 表示排除历史字段，1 表示包含。")
    products_get.add_argument("--stats", help="统计窗口，例如 90 或日期区间。")
    products_get.add_argument("--update", help="刷新阈值小时；0 可能额外消耗 token。")
    products_get.add_argument("--offers", help="请求 offer 数，官方范围 20-100，会显著消耗 token。")
    products_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    products_search = products_subparsers.add_parser("search", help="产品关键词搜索。")
    products_search.add_argument("term", help="搜索词。")
    products_search.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    products_search.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    products_search.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    categories = subparsers.add_parser("categories", help="分类查询命令。")
    categories_subparsers = categories.add_subparsers(dest="categories_command")
    categories_get = categories_subparsers.add_parser("get", help="按 category id 查询分类。")
    categories_get.add_argument("category", nargs="+", help="一个或多个 category id，0 表示 root categories。")
    categories_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    categories_get.add_argument("--parents", action="store_true", help="包含父级分类树。")
    categories_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    categories_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    categories_search = categories_subparsers.add_parser("search", help="分类关键词搜索。")
    categories_search.add_argument("term", help="搜索词，多个关键词需全部匹配。")
    categories_search.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    categories_search.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    categories_search.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

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
    history_trend = history_subparsers.add_parser("trend", help="分析 Keepa Product csv 趋势。")
    history_trend.add_argument("asin", help="一个 ASIN。")
    history_trend.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    history_trend.add_argument("--series", default="amazon,new,used,sales_rank", help="逗号分隔序列，例如 amazon,new,sales_rank。")
    history_trend.add_argument("--window-days", action="append", type=int, default=[], help="趋势窗口天数，可重复。")
    history_trend.add_argument("--include-missing", action="store_true", help="保留 Keepa -1 缺失值。")
    history_trend.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    history_trend.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    finder = subparsers.add_parser("finder", help="Product Finder 高价值查询命令。")
    finder_subparsers = finder.add_subparsers(dest="finder_command")
    finder_query = finder_subparsers.add_parser("query", help="按 selection JSON 查询 ASIN 列表。")
    finder_query.add_argument("--selection-file", required=True, help="Keepa Product Finder selection JSON 文件。")
    finder_query.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    finder_query.add_argument("--max-tokens", type=int, default=10, help="Agent 预算上限提示。")
    finder_query.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    finder_query.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    finder_query.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    deals = subparsers.add_parser("deals", help="Keepa deals 查询命令。")
    deals_subparsers = deals.add_subparsers(dest="deals_command")
    deals_query = deals_subparsers.add_parser("query", help="按 selection JSON 查询 deals。")
    deals_query.add_argument("--selection-file", required=True, help="Keepa deals selection JSON 文件。")
    deals_query.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    deals_query.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    deals_query.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    deals_query.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    sellers = subparsers.add_parser("sellers", help="卖家查询命令。")
    sellers_subparsers = sellers.add_subparsers(dest="sellers_command")
    sellers_get = sellers_subparsers.add_parser("get", help="按 seller id 查询卖家。")
    sellers_get.add_argument("seller", nargs="+", help="一个或多个 seller id。")
    sellers_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    sellers_get.add_argument("--storefront", action="store_true", help="请求卖家 storefront ASIN 列表。")
    sellers_get.add_argument("--update", help="刷新阈值小时。")
    sellers_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    sellers_get.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    sellers_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    bestsellers = subparsers.add_parser("bestsellers", help="Best Sellers 榜单命令。")
    bestsellers_subparsers = bestsellers.add_subparsers(dest="bestsellers_command")
    bestsellers_get = bestsellers_subparsers.add_parser("get", help="按 category id 查询 Best Sellers。")
    bestsellers_get.add_argument("category", help="Keepa category id。")
    bestsellers_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    bestsellers_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    bestsellers_get.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    bestsellers_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    topsellers = subparsers.add_parser("topsellers", help="Top Sellers 榜单命令。")
    topsellers_subparsers = topsellers.add_subparsers(dest="topsellers_command")
    topsellers_list = topsellers_subparsers.add_parser("list", help="查询 Most Rated Sellers 列表。")
    topsellers_list.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    topsellers_list.add_argument("--category", help="可选 Keepa category id。")
    topsellers_list.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    topsellers_list.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    topsellers_list.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    request = subparsers.add_parser("request", help="原始 Keepa API dry-run 逃生口。")
    request_subparsers = request.add_subparsers(dest="request_method")
    for method in ("get", "post"):
        request_method = request_subparsers.add_parser(method, help=f"构建 {method.upper()} 请求规格。")
        request_method.add_argument("path", help="Keepa API path，例如 /product。")
        request_method.add_argument(
            "--param",
            action="append",
            default=[],
            metavar="KEY=VALUE",
            help="添加 query 参数，可重复。",
        )
        request_method.add_argument("--dry-run", action="store_true", help="只输出 redacted request spec。")

    return parser


def _parse_params(raw_params: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for raw in raw_params:
        key, separator, value = raw.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid --param, expected KEY=VALUE: {raw}")
        params[key.strip()] = value
    return params


def _run_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str]:
    if args.command == "doctor":
        payload = run_command("doctor")
        return 0 if payload["ok"] else 1, payload

    if args.command == "domains" and args.domains_command == "list":
        payload = run_command("domains.list")
        return 0 if payload["ok"] else 1, payload

    if args.command == "config" and args.config_command == "show":
        payload = run_command("config.show", {"path": args.path})
        return 0 if payload["ok"] else 1, payload

    if args.command == "config" and args.config_command == "init":
        payload = run_command("config.init", {"path": args.path, "dry_run": bool(args.dry_run)})
        return 0 if payload["ok"] else 1, payload

    if args.command == "products" and args.products_command == "get":
        payload = run_command(
            "products.get",
            {
                "asin": args.asin,
                "code": args.code,
                "domain": args.domain,
                "history": args.history,
                "stats": args.stats,
                "update": args.update,
                "offers": args.offers,
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
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
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "categories" and args.categories_command == "get":
        payload = run_command(
            "categories.get",
            {
                "category": args.category,
                "domain": args.domain,
                "parents": bool(args.parents),
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
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
            },
        )
        return 0 if payload["ok"] else 1, payload

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
            },
        )
        return 0 if payload["ok"] else 1, payload

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
            },
        )
        return 0 if payload["ok"] else 1, payload

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
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "sellers" and args.sellers_command == "get":
        payload = run_command(
            "sellers.get",
            {
                "seller": args.seller,
                "domain": args.domain,
                "storefront": bool(args.storefront),
                "update": args.update,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "bestsellers" and args.bestsellers_command == "get":
        payload = run_command(
            "bestsellers.get",
            {
                "category": args.category,
                "domain": args.domain,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "topsellers" and args.topsellers_command == "list":
        payload = run_command(
            "topsellers.list",
            {
                "domain": args.domain,
                "category": args.category,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "request" and args.request_method in {"get", "post"}:
        try:
            params = _parse_params(args.param)
        except ValueError as exc:
            return 2, error_envelope(
                command="request",
                kind="invalid_argument",
                message=str(exc),
            )
        payload = run_command(
            f"request.{args.request_method}",
            {
                "path": args.path,
                "params": params,
                "dry_run": bool(args.dry_run),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return 2, error_envelope(
        command=args.command or "cli",
        kind="unsupported_command",
        message="unsupported or incomplete command",
    )


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.stdio:
        input_text = sys.stdin.read()
        for line in iter_stdio_output(input_text, env=os.environ):
            sys.stdout.write(line + "\n")
        return 0

    if args.command is None:
        if args.json:
            _write_json(
                error_envelope(
                    command="cli",
                    kind="missing_command",
                    message="a command is required in --json mode",
                )
            )
            return 2
        return run_interactive_tui()

    exit_code, payload = _run_command(args)
    if args.json:
        if isinstance(payload, str):
            payload = success_envelope(command=args.command, data={"message": payload})
        _write_json(payload)
        return exit_code

    if isinstance(payload, str):
        sys.stdout.write(payload + "\n")
    elif payload.get("ok"):
        sys.stdout.write(json.dumps(payload["data"], ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stderr.write(payload["error"]["message"] + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
