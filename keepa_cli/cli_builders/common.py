"""
keepa_cli/cli_builders/common.py
文件说明：CLI builder 共享 argparse 工具。
主要职责：集中注册 live cache 控制参数，避免各命令族重复定义。
依赖边界：只操作 argparse parser，不访问 service 或网络。
"""

from __future__ import annotations

import argparse


def add_live_cache_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache-ttl", type=int, help="本次 live GET JSON 响应缓存 TTL 秒数，优先级高于环境变量。")
    parser.add_argument("--no-cache", action="store_true", help="本次 live 请求禁用 SQLite response cache。")


def live_cache_params(args: argparse.Namespace) -> dict[str, object]:
    return {
        "cache_ttl": getattr(args, "cache_ttl", None),
        "no_cache": bool(getattr(args, "no_cache", False)),
    }
