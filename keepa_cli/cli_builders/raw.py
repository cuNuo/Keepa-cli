"""
keepa_cli/cli_builders/raw.py
文件说明：raw request 命令族 argparse 构造与分发。
主要职责：注册原始 Keepa API 请求逃生口，并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.envelope import error_envelope
from keepa_cli.service import run_command


def add_raw_request_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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
        add_live_cache_options(request_method)


def maybe_run_raw_request_command(
    args: argparse.Namespace,
    *,
    parse_params: Callable[[list[str]], dict[str, str]],
) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "request" and args.request_method in {"get", "post"}:
        try:
            params = parse_params(args.param)
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
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
