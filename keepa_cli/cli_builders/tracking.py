"""
keepa_cli/cli_builders/tracking.py
文件说明：tracking 命令族 argparse 构造与分发。
主要职责：注册 tracking 查询/写入命令，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.service import run_command


def add_tracking_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    tracking = subparsers.add_parser("tracking", help="Keepa tracking 请求命令。")
    tracking_subparsers = tracking.add_subparsers(dest="tracking_command")
    tracking_list = tracking_subparsers.add_parser("list", help="列出当前 tracking。")
    tracking_list.add_argument("--asins-only", action="store_true", help="只返回被跟踪 ASIN 列表。")
    tracking_list.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_list.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    tracking_list.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(tracking_list)

    tracking_list_names = tracking_subparsers.add_parser("list-names", help="列出 tracking ASIN 名称入口，等价 asins-only list。")
    tracking_list_names.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_list_names.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    tracking_list_names.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(tracking_list_names)

    tracking_get = tracking_subparsers.add_parser("get", help="查询单个 ASIN 的 tracking。")
    tracking_get.add_argument("asin", help="一个 ASIN。")
    tracking_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(tracking_get)

    tracking_add = tracking_subparsers.add_parser("add", help="添加一个或一批 tracking。")
    tracking_add.add_argument("--tracking-json", dest="tracking", help="Tracking JSON object/list。")
    tracking_add.add_argument("--tracking-file", help="包含 Tracking JSON object/list 的文件。")
    tracking_add.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_add.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    tracking_add.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    tracking_remove = tracking_subparsers.add_parser("remove", help="移除单个 ASIN 的 tracking。")
    tracking_remove.add_argument("asin", help="一个 ASIN。")
    tracking_remove.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_remove.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    tracking_remove_all = tracking_subparsers.add_parser("remove-all", help="移除所有 tracking。")
    tracking_remove_all.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_remove_all.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")

    tracking_notifications = tracking_subparsers.add_parser("notifications", help="查询 tracking 通知。")
    tracking_notifications.add_argument("--since", default=0, help="Keepa minute；0 表示全部。")
    tracking_notifications.add_argument("--revise", action="store_true", help="包含已读通知。")
    tracking_notifications.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_notifications.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(tracking_notifications)

    tracking_webhook = tracking_subparsers.add_parser("webhook", help="更新 tracking webhook URL。")
    tracking_webhook.add_argument("url", help="Webhook URL。")
    tracking_webhook.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tracking_webhook.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")


def maybe_run_tracking_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "tracking" and args.tracking_command == "list":
        payload = run_command(
            "tracking.list",
            {
                "asins_only": bool(args.asins_only),
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "list-names":
        payload = run_command(
            "tracking.list-names",
            {
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "get":
        payload = run_command(
            "tracking.get",
            {
                "asin": args.asin,
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "add":
        payload = run_command(
            "tracking.add",
            {
                "tracking": args.tracking,
                "tracking_file": args.tracking_file,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "remove":
        payload = run_command(
            "tracking.remove",
            {
                "asin": args.asin,
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "remove-all":
        payload = run_command(
            "tracking.remove-all",
            {
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "notifications":
        payload = run_command(
            "tracking.notifications",
            {
                "since": args.since,
                "revise": bool(args.revise),
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tracking" and args.tracking_command == "webhook":
        payload = run_command(
            "tracking.webhook",
            {
                "url": args.url,
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
