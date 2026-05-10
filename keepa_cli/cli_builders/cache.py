"""
keepa_cli/cli_builders/cache.py
文件说明：缓存命令族 argparse 构造与分发。
主要职责：注册 cache explain/stats/clear，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from keepa_cli.service import run_command


def add_cache_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cache = subparsers.add_parser("cache", help="缓存与 provenance 审计命令。")
    cache_subparsers = cache.add_subparsers(dest="cache_command")
    cache_explain = cache_subparsers.add_parser("explain", help="解释 JSON envelope 中的缓存来源和节省估算。")
    cache_explain.add_argument("--input", help="包含 cache_provenance 的 JSON 文件。")
    cache_explain.add_argument("--command", dest="target_command", help="用于估算 token 成本的命令名。")
    cache_explain.add_argument("--endpoint", help="覆盖 endpoint 显示。")
    cache_explain_key = cache_subparsers.add_parser("explain-key", help="按请求参数反查 SQLite response cache key。")
    cache_explain_key.add_argument("--method", default="GET", help="HTTP method，默认 GET。")
    cache_explain_key.add_argument("--endpoint", required=True, help="Keepa API endpoint，例如 /product。")
    cache_explain_key.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="添加请求参数，可重复。")
    cache_explain_key.add_argument("--json-body", help="可选 JSON body；用于 POST key 审计。")
    cache_stats = cache_subparsers.add_parser("stats", help="显示 SQLite 持久响应缓存状态。")
    cache_stats.add_argument("--cache-path", help="覆盖 SQLite cache 文件路径。")
    cache_inspect = cache_subparsers.add_parser("inspect", help="审计单条 SQLite cache key 元数据。")
    cache_inspect.add_argument("cache_key", help="来自 cache_provenance.cache_key 的缓存 key。")
    cache_inspect.add_argument("--cache-path", help="覆盖 SQLite cache 文件路径。")
    cache_prune = cache_subparsers.add_parser("prune-expired", help="清理已过期 SQLite cache 条目。")
    cache_prune.add_argument("--cache-path", help="覆盖 SQLite cache 文件路径。")
    cache_prune.add_argument("--dry-run", action="store_true", help="只统计将清理的过期条目。")
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

    if args.command == "cache" and args.cache_command == "explain-key":
        try:
            params = _parse_key_value_params(args.param)
            json_body = json.loads(args.json_body) if args.json_body else None
        except (json.JSONDecodeError, ValueError) as exc:
            return 2, {"ok": False, "command": "cache.explain-key", "error": {"kind": "invalid_argument", "message": str(exc)}}
        payload = run_command(
            "cache.explain-key",
            {"method": args.method, "endpoint": args.endpoint, "params": params, "json_body": json_body},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "cache" and args.cache_command == "stats":
        payload = run_command("cache.stats", {"cache_path": args.cache_path})
        return 0 if payload["ok"] else 1, payload

    if args.command == "cache" and args.cache_command == "inspect":
        payload = run_command("cache.inspect", {"cache_key": args.cache_key, "cache_path": args.cache_path})
        return 0 if payload["ok"] else 1, payload

    if args.command == "cache" and args.cache_command == "prune-expired":
        payload = run_command("cache.prune-expired", {"dry_run": bool(args.dry_run), "cache_path": args.cache_path})
        return 0 if payload["ok"] else 1, payload

    if args.command == "cache" and args.cache_command == "clear":
        payload = run_command("cache.clear", {"dry_run": bool(args.dry_run), "cache_path": args.cache_path})
        return 0 if payload["ok"] else 1, payload

    return None


def _parse_key_value_params(raw_params: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for raw in raw_params:
        key, separator, value = raw.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid --param, expected KEY=VALUE: {raw}")
        params[key.strip()] = value
    return params
