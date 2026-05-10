"""
keepa_cli/agent/stdio.py
文件说明：实现 Agent 使用的 JSON Lines stdio 协议。
主要职责：解析单行请求、输出事件流，并把高成本请求转成确认错误。
依赖边界：不直接访问网络，业务执行统一委托 Agent-safe command service。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from keepa_cli.agent.session import AgentSession
from keepa_cli.envelope import error_envelope
from keepa_cli.token_budget import estimate_request_budget


def _event(message_id: str | None, event: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": message_id, "event": event}
    payload.update(fields)
    return payload


def handle_stdio_message(
    raw_message: str,
    *,
    env: Mapping[str, str] | None = None,
    session: AgentSession | None = None,
) -> list[dict[str, Any]]:
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        return [
            _event(
                None,
                "response",
                payload=error_envelope(
                    command="stdio",
                    kind="invalid_json",
                    message=str(exc),
                ),
            ),
            _event(None, "done"),
        ]

    message_id = str(message.get("id", ""))
    method = str(message.get("method", ""))
    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    events: list[dict[str, Any]] = [_event(message_id, "started", method=method)]
    budget = estimate_request_budget(method, params).to_dict()
    events.append(_event(message_id, "budget_estimated", **budget))

    active_session = session or AgentSession(env=env)
    payload = active_session.execute(method, params)

    events.append(_event(message_id, "response", payload=payload))
    events.append(_event(message_id, "done"))
    return events


def iter_stdio_output(input_text: str, *, env: Mapping[str, str] | None = None) -> list[str]:
    lines: list[str] = []
    session = AgentSession(env=env)
    for raw_line in input_text.splitlines():
        if not raw_line.strip():
            continue
        for event in handle_stdio_message(raw_line, env=env, session=session):
            lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return lines
