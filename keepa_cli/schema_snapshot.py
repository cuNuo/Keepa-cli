"""
keepa_cli/schema_snapshot.py
文件说明：生成 Agent 输出的 schema snapshot 形状。
主要职责：把 envelope/event 的字段和类型转为稳定可比较结构。
依赖边界：不读取文件、不调用网络，只处理调用方传入的 Python 数据。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _shape(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    if isinstance(value, tuple):
        return [_shape(item) for item in value]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def build_agent_schema_snapshot(payloads: Mapping[str, Any]) -> dict[str, Any]:
    return {str(name): _shape(payload) for name, payload in sorted(payloads.items())}
