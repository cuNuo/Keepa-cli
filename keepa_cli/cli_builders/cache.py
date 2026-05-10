"""
keepa_cli/cli_builders/cache.py
文件说明：缓存命令族 argparse 构造与分发。
主要职责：注册 cache explain/stats/clear，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.service import run_command


def add_cache_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cache = subparsers.add_parser("cache", help="缓存与 provenance 审计命令。")
    cache_subparsers = cache.add_subparsers(dest="cache_command")
    cache_explain = cache_subparsers.add_parser("explain", help="解释 JSON envelope 中的缓存来源和节省估算。")
    cache_explain.add_argument("--input", help="包含 cache_provenance 的 JSON 文件。")
    cache_explain.add_argument("--command", dest="target_command", help="用于估算 token 成本的命令名。")
    cache_explain.add_argument("--endpoint", help="覆盖 endpoint 显示。")
    cache_stats = cache_subparsers.add_parser("stats", help="显示 SQLite 持久响应缓存状态。")
    cache_stats.add_argument("--cache-path", help="覆盖 SQLite cache 文件路径。")
    cache_clear = cache_subparsers.add_parser("clear", help="清理 SQLite 持久响应缓存。")
    cache_clear.add_argument("--cache-path", help="覆盖 SQLite cache 文件路径。")
    cache_clear.add_argument("--dry-run", action="store_true", help="只展示将执行的清理动作。")


def maybe_run_cache_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "cache" and args.cache_command == "explain":
        payload = run_command(
            "cache.explain",
            {"input": args.input, "target_command": args.target_command, "endpoint": args.endpoint},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "cache" and args.cache_command == "stats":
        payload = run_command("cache.stats", {"cache_path": args.cache_path})
        return 0 if payload["ok"] else 1, payload

    if args.command == "cache" and args.cache_command == "clear":
        payload = run_command("cache.clear", {"dry_run": bool(args.dry_run), "cache_path": args.cache_path})
        return 0 if payload["ok"] else 1, payload

    return None
