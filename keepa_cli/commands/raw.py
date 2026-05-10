"""
keepa_cli/commands/raw.py
文件说明：raw request 命令族 service 路由。
主要职责：提供受控原始 Keepa API 请求逃生口。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.commands.common import client, live_cache_options


RAW_COMMANDS = {"request.get", "request.post"}


def can_handle(command: str) -> bool:
    return command in RAW_COMMANDS


def handle_raw_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    method = command.rsplit(".", 1)[1].upper()
    return client(fixture_dir).request(
        command=command,
        method=method,
        path=str(params.get("path", "")),
        params=dict(params.get("params") or {}),
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
