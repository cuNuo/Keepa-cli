"""
keepa_cli/redaction.py
文件说明：提供 stdout、stderr 与 envelope 输出前的敏感信息打码能力。
主要职责：按敏感字段名和显式 secret 值递归清理输出数据。
依赖边界：纯函数模块，不读取环境变量或文件。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


SECRET_PARAM_NAMES = {"key", "api_key", "apikey", "token", "authorization"}


def redact_text(value: str, secret_values: Sequence[str] | None = None) -> str:
    redacted = value
    for secret in secret_values or ():
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def redact_value(value: object, secret_values: Sequence[str] | None = None) -> object:
    if isinstance(value, str):
        return redact_text(value, secret_values)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SECRET_PARAM_NAMES:
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = redact_value(item, secret_values)
        return result
    if isinstance(value, list):
        return [redact_value(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, secret_values) for item in value]
    return value
