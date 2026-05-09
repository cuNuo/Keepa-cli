"""
keepa_cli/high_value.py
文件说明：支撑 Phase 8 高价值 API 命令的本地数据处理。
主要职责：读取 selection JSON、序列化 Keepa 查询参数，并把大响应写入文件。
依赖边界：不访问网络、不读取凭据，真实请求仍由 KeepaClient 统一处理。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def load_selection(selection: Any = None, selection_file: Path | str | None = None) -> dict[str, Any]:
    if isinstance(selection, Mapping):
        return dict(selection)
    if isinstance(selection, str) and selection.strip():
        try:
            parsed = json.loads(selection)
        except json.JSONDecodeError as exc:
            raise ValueError(f"selection must be valid JSON: {exc}") from exc
        if isinstance(parsed, Mapping):
            return dict(parsed)
        raise ValueError("selection JSON must be an object")

    if selection_file is None or not str(selection_file).strip():
        raise ValueError("selection_file is required")

    path = Path(selection_file)
    if not path.is_file():
        raise ValueError(f"selection file not found: {selection_file}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"selection file must contain valid JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("selection file JSON must be an object")
    return dict(parsed)


def selection_to_query_value(selection: Mapping[str, Any]) -> str:
    return json.dumps(dict(selection), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _body_from_payload_data(data: dict[str, Any]) -> dict[str, Any] | list[Any]:
    body = data.get("body")
    if isinstance(body, (dict, list)):
        return body
    return data


def _result_count(body: dict[str, Any] | list[Any]) -> int:
    if isinstance(body, list):
        return len(body)
    for key in ("products", "asinList", "deals", "topSellers"):
        value = body.get(key)
        if isinstance(value, list):
            return len(value)
    sellers = body.get("sellers")
    if isinstance(sellers, dict):
        return len(sellers)
    bestsellers = body.get("bestSellersList")
    if isinstance(bestsellers, dict):
        asin_list = bestsellers.get("asinList")
        if isinstance(asin_list, list):
            return len(asin_list)
    return 1 if body else 0


def write_body_output(data: dict[str, Any], output_path: Path | str) -> dict[str, Any]:
    body = _body_from_payload_data(data)
    path = Path(output_path)
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(content + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "format": "json",
        "size_bytes": path.stat().st_size,
        "result_count": _result_count(body),
    }


def attach_output_if_requested(payload: dict[str, Any], output_path: Path | str | None) -> dict[str, Any]:
    if not output_path or not payload.get("ok"):
        return payload
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("dry_run"):
        return payload
    data["output"] = write_body_output(data, output_path)
    return payload
