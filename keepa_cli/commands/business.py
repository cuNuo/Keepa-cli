"""
keepa_cli/commands/business.py
文件说明：业务别名与指标命令族 service 路由。
主要职责：把 Agent 友好的业务场景入口映射到本地 metrics/profile 计算。
依赖边界：不访问真实 Keepa API，不处理 argparse。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.agent_profile import build_agent_profile
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.metrics import build_business_metrics


BUSINESS_COMMANDS = {
    "business.find-fast-movers",
    "business.inventory-audit",
    "business.market-opportunity",
    "seller-metrics.summary",
    "velocity.research",
    "inventory.audit",
    "agent.profile.generate",
}


def can_handle(command: str) -> bool:
    return command in BUSINESS_COMMANDS


def handle_business_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    if command == "agent.profile.generate":
        data = build_agent_profile(
            server_name=str(_param(params, "server_name", "server-name", default="keepa")),
            profile=str(_param(params, "profile", default="dry_run_default")),
            toolset=str(_param(params, "toolset", default="research")),
            python_command=_param(params, "python_command", "python-command"),
        )
        return success_envelope(command=command, data=data, request={"transport": "service"}, token_bucket={})

    payload = _load_payload(params, fixture_dir=fixture_dir)
    if payload is None:
        return error_envelope(
            command=command,
            kind="invalid_argument",
            message="business metrics commands require one of payload, input, or fixture",
            details={"supported_commands": sorted(BUSINESS_COMMANDS)},
        )
    data = build_business_metrics(
        payload,
        alias=command,
        target_days=int(_param(params, "target_days", "target-days", default=30) or 30),
        fast_mover_threshold=int(_param(params, "threshold_monthly_sold", "threshold-monthly-sold", default=500) or 500),
        max_results=_optional_int(_param(params, "max_results", "max-results")),
    )
    return success_envelope(
        command=command,
        data=data,
        request={
            "transport": "service",
            "source": _source_label(params),
            "local_only": True,
        },
        token_bucket={},
    )


def _param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _load_payload(params: Mapping[str, Any], *, fixture_dir: Path | str | None) -> Mapping[str, Any] | list[Any] | None:
    inline = _param(params, "payload", "data")
    if isinstance(inline, (Mapping, list)):
        return inline
    input_path = _param(params, "input", "input_path", "input-path")
    if input_path:
        return _read_json(Path(str(input_path)))
    fixture = _param(params, "fixture")
    if fixture:
        base = Path(fixture_dir) if fixture_dir is not None else Path("tests/fixtures")
        path = Path(str(fixture))
        if not path.is_absolute():
            path = base / path
        return _read_json(path)
    return None


def _read_json(path: Path) -> Mapping[str, Any] | list[Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_label(params: Mapping[str, Any]) -> str:
    if _param(params, "payload", "data") is not None:
        return "inline_payload"
    if _param(params, "input", "input_path", "input-path"):
        return "input_file"
    if _param(params, "fixture"):
        return "fixture"
    return "unknown"
