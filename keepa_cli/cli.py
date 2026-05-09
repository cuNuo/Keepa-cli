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
from keepa_cli.client import KeepaClient
from keepa_cli.config import build_config_report, init_config
from keepa_cli.doctor import build_doctor_report
from keepa_cli.domains import list_domains
from keepa_cli.envelope import error_envelope, success_envelope


def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


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
        return 0, success_envelope(
            command="doctor",
            data=build_doctor_report(env=os.environ),
            request={"transport": "cli"},
            token_bucket={},
        )

    if args.command == "domains" and args.domains_command == "list":
        return 0, success_envelope(
            command="domains.list",
            data={"domains": list_domains()},
            request={"transport": "cli"},
            token_bucket={},
        )

    if args.command == "config" and args.config_command == "show":
        return 0, success_envelope(
            command="config.show",
            data=build_config_report(path=args.path, env=os.environ),
            request={"transport": "cli"},
            token_bucket={},
        )

    if args.command == "config" and args.config_command == "init":
        return 0, success_envelope(
            command="config.init",
            data=init_config(path=args.path, env=os.environ, dry_run=bool(args.dry_run)),
            request={"transport": "cli", "dry_run": bool(args.dry_run)},
            token_bucket={},
        )

    if args.command == "request" and args.request_method in {"get", "post"}:
        try:
            params = _parse_params(args.param)
        except ValueError as exc:
            return 2, error_envelope(
                command="request",
                kind="invalid_argument",
                message=str(exc),
            )
        payload = KeepaClient().request(
            command=f"request.{args.request_method}",
            method=args.request_method.upper(),
            path=args.path,
            params=params,
            dry_run=bool(args.dry_run),
        )
        return 0 if payload["ok"] else 1, payload

    return 2, error_envelope(
        command=args.command or "cli",
        kind="unsupported_command",
        message="unsupported or incomplete command",
    )


def main(argv: Sequence[str] | None = None) -> int:
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
        parser.print_help()
        return 0

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
