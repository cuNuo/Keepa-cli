"""
keepa_cli/commands/finder.py
文件说明：finder 命令族 service 路由。
主要职责：把 Product Finder selection 查询转换为 Keepa /query 请求。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.commands.selection import selection_query


FINDER_COMMANDS = {"finder.query"}


def can_handle(command: str) -> bool:
    return command in FINDER_COMMANDS


def handle_finder_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    if command == "finder.query":
        return selection_query("finder.query", "/query", params, fixture_dir)
    raise ValueError(f"unsupported finder command: {command}")
