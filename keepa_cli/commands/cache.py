"""
keepa_cli/commands/cache.py
文件说明：cache 命令族 service 路由。
主要职责：把 cache explain/stats/clear 封装为稳定 envelope。
依赖边界：不访问真实 Keepa API，不处理 argparse。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from keepa_cli.envelope import success_envelope
from keepa_cli.cache import default_cache_path
from keepa_cli.workflows import cache_stats, clear_cache, explain_cache


CACHE_COMMANDS = {
    "cache.explain",
    "cache.stats",
    "cache.clear",
}


def _param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


def _bool_option(params: Mapping[str, Any], *names: str) -> bool:
    value = _param(params, *names)
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def can_handle(command: str) -> bool:
    return command in CACHE_COMMANDS


def _cache_path(params: Mapping[str, Any], env: Mapping[str, str] | None) -> str | None:
    explicit = _param(params, "cache_path", "cache-path")
    if explicit:
        return str(explicit)
    if env is not None:
        return str(default_cache_path(env))
    return None


def handle_cache_command(command: str, params: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if command == "cache.explain":
        data = explain_cache(
            input_path=_param(params, "input", "input_path"),
            command=_param(params, "target_command", "command"),
            endpoint=_param(params, "endpoint"),
        )
    elif command == "cache.stats":
        data = cache_stats(cache_path=_cache_path(params, env))
    elif command == "cache.clear":
        data = clear_cache(
            dry_run=_bool_option(params, "dry_run", "dry-run"),
            cache_path=_cache_path(params, env),
        )
    else:
        raise ValueError(f"unsupported cache command: {command}")

    return success_envelope(
        command=command,
        data=data,
        request={"transport": "service"},
        token_bucket={},
    )
