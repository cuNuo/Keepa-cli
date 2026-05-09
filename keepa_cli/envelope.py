"""
keepa_cli/envelope.py
文件说明：定义 Agent 稳定 JSON 成功与错误 envelope。
主要职责：统一命令输出结构，并在错误细节中执行凭据打码。
依赖边界：不包含业务请求逻辑，只依赖 redaction 工具函数。
"""

from __future__ import annotations

from typing import Any

from keepa_cli.redaction import redact_text, redact_value


def success_envelope(
    *,
    command: str,
    data: dict[str, Any] | list[Any],
    request: dict[str, Any] | None = None,
    token_bucket: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "request": request or {},
        "token_bucket": token_bucket or {},
        "data": data,
    }


def error_envelope(
    *,
    command: str,
    kind: str,
    message: str,
    status_code: int | None = None,
    details: dict[str, Any] | None = None,
    token_bucket: dict[str, Any] | None = None,
    secret_values: list[str] | None = None,
) -> dict[str, Any]:
    error = {
        "kind": kind,
        "message": redact_text(message, secret_values),
    }
    if status_code is not None:
        error["status_code"] = status_code
    if details:
        error["details"] = redact_value(details, secret_values)

    return {
        "ok": False,
        "command": command,
        "error": error,
        "token_bucket": token_bucket or {},
    }
