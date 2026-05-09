"""
keepa_cli/analysis.py
文件说明：提供 Keepa 历史序列的轻量趋势分析。
主要职责：按序列统计点数、均价/均排名、最高最低、最新值和变化幅度。
依赖边界：只处理已展开的 history rows，不读取文件、不访问网络。
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Any


def _round_value(value: float | int) -> float | int:
    if isinstance(value, int):
        return value
    return round(value, 4)


def _point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": row["timestamp"],
        "keepa_minute": row["keepa_minute"],
        "value": row["value"],
        "raw_value": row["raw_value"],
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [row for row in sorted(rows, key=lambda item: item["keepa_minute"]) if row.get("value") is not None]
    if not valid_rows:
        return {"points": 0}

    values = [row["value"] for row in valid_rows]
    oldest = valid_rows[0]
    latest = valid_rows[-1]
    min_row = min(valid_rows, key=lambda item: item["value"])
    max_row = max(valid_rows, key=lambda item: item["value"])
    absolute = round(float(latest["value"]) - float(oldest["value"]), 4)
    percent = round((absolute / float(oldest["value"])) * 100, 4) if oldest["value"] else None
    average = mean(float(value) for value in values)
    volatility = pstdev(float(value) for value in values) if len(values) > 1 else 0.0

    return {
        "points": len(valid_rows),
        "unit": valid_rows[0]["unit"],
        "oldest": _point(oldest),
        "latest": _point(latest),
        "min": _point(min_row),
        "max": _point(max_row),
        "average": round(average, 4),
        "volatility": round(volatility, 4),
        "change": {
            "absolute": _round_value(absolute),
            "percent": percent,
        },
    }


def analyze_history_rows(rows: list[dict[str, Any]], *, window_days: list[int] | None = None) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["series"])].append(row)

    windows = window_days or [30, 90, 180]
    result: dict[str, Any] = {"series": {}}
    for series, series_rows in sorted(grouped.items()):
        sorted_rows = sorted(series_rows, key=lambda item: item["keepa_minute"])
        latest_minute = max(row["keepa_minute"] for row in sorted_rows)
        series_result = {"all_time": _metrics(sorted_rows), "windows": {}}
        for days in windows:
            cutoff = latest_minute - int(days) * 1440
            window_rows = [row for row in sorted_rows if row["keepa_minute"] >= cutoff]
            series_result["windows"][str(days)] = _metrics(window_rows)
        result["series"][series] = series_result
    return result
