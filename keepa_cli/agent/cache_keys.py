"""
keepa_cli/agent/cache_keys.py
文件说明：生成 Agent 会话缓存键。
主要职责：对命令参数做稳定、脱敏、去运行时字段的规范化。
依赖边界：无业务层依赖，可被 session 与 MCP resources 共同复用。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


RUNTIME_KEYS = {"from_cache", "yes"}
SECRET_KEY_PARTS = ("key", "api_key", "apikey", "token", "authorization", "password", "secret")


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def _safe_for_cache_key(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("[REDACTED]" if _is_secret_key(str(key)) else _safe_for_cache_key(item))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in RUNTIME_KEYS
        }
    if isinstance(value, list):
        return [_safe_for_cache_key(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_for_cache_key(item) for item in value]
    return value


def build_cache_key(command: str, params: Mapping[str, Any] | None = None) -> str:
    normalized = _safe_for_cache_key(dict(params or {}))
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{command}:{digest}"
