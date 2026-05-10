"""
keepa_cli/commands/deals.py
文件说明：deals 命令族 service 路由。
主要职责：把 deals selection 查询转换为 Keepa /deal 请求。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.commands.selection import selection_query


DEALS_COMMANDS = {"deals.query"}


def can_handle(command: str) -> bool:
    return command in DEALS_COMMANDS


def handle_deals_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    if command == "deals.query":
        return selection_query("deals.query", "/deal", params, fixture_dir)
    raise ValueError(f"unsupported deals command: {command}")
