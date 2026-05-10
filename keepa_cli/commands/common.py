"""
keepa_cli/commands/common.py
文件说明：命令族 service handler 共享工具。
主要职责：集中参数读取、bool 解析、client 构造和 live cache 控制透传。
依赖边界：不处理 argparse，不直接访问网络。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepa_cli.client import KeepaClient
from keepa_cli.envelope import error_envelope
from keepa_cli.token_budget import estimate_request_budget


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def bool_param(value: Any) -> str:
    return "1" if value is True or str(value).lower() in {"1", "true", "yes", "on"} else "0"


def optional_params(params: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        if name in params and params[name] is not None:
            result[name] = params[name]
    return result


def param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


def bool_option(params: Mapping[str, Any], *names: str) -> bool:
    value = param(params, *names)
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def product_query_options(params: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if bool_option(params, "full", "full_detail", "full-detail"):
        stats_window = param(params, "stats_window", "stats-window", default="0")
        result.update({"history": "1", "stats": str(stats_window), "videos": "1", "aplus": "1"})

    for canonical in (
        "stats",
        "update",
        "history",
        "days",
        "offers",
        "code-limit",
        "only-live-offers",
        "videos",
        "aplus",
        "rating",
        "buybox",
        "stock",
        "historical-variations",
    ):
        value = param(params, canonical, canonical.replace("-", "_"))
        if value is not None:
            result[canonical] = value
    return result


def client(fixture_dir: Path | str | None = None) -> KeepaClient:
    selected_fixture_dir = Path(fixture_dir) if fixture_dir is not None else DEFAULT_FIXTURE_DIR
    return KeepaClient(fixture_dir=selected_fixture_dir)


def live_cache_options(params: Mapping[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    cache_ttl = param(params, "cache_ttl", "cache-ttl", "cache_ttl_seconds", "cache-ttl-seconds")
    if cache_ttl is not None:
        options["cache_ttl_seconds"] = int(cache_ttl)
    if bool_option(params, "no_cache", "no-cache"):
        options["no_cache"] = True
    return options


def confirmation_required(command: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    budget = estimate_request_budget(command, dict(params)).to_dict()
    if not budget["requires_confirmation"]:
        return None
    if bool_option(params, "dry_run", "dry-run") or params.get("fixture") or bool_option(params, "yes"):
        return None
    return error_envelope(
        command=command,
        kind="confirmation_required",
        message="request requires explicit confirmation because it may consume significant Keepa tokens",
        details={
            "resume_with": "--yes",
            "estimated_tokens": budget["estimated_tokens"],
            "worst_case_tokens": budget["worst_case_tokens"],
        },
        token_bucket={"estimated": budget},
    )
