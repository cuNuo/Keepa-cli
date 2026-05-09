"""
keepa_cli/cache.py
文件说明：生成可审计的缓存与数据来源 provenance。
主要职责：为 Agent 输出 endpoint、参数哈希、来源、fixture 与缓存状态。
依赖边界：不实现持久缓存，只生成稳定元数据。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _stable_params_hash(params: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(params), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_cache_provenance(
    *,
    endpoint: str,
    params: Mapping[str, Any],
    source: str,
    fixture: str | None = None,
    out: str | None = None,
    cache_hit: bool = False,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "source": source,
        "endpoint": endpoint,
        "params_hash": _stable_params_hash(params),
        "cache_hit": cache_hit,
    }
    if fixture:
        provenance["fixture"] = fixture
    if out:
        provenance["out"] = out
    return provenance
