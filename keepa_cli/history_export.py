"""
keepa_cli/history_export.py
文件说明：展开 Keepa Product Object 中的 csv 历史数组。
主要职责：把常用价格/排名序列转换为 JSON、JSONL 或 CSV 可读行。
依赖边界：不发起 Keepa 请求；调用方负责提供 Product Object。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from keepa_cli.keepa_time import keepa_minutes_to_iso


HISTORY_FIELDS = ["asin", "series", "timestamp", "keepa_minute", "value", "raw_value", "unit"]

SERIES_DEFINITIONS = {
    "amazon": {"index": 0, "unit": "currency", "scale": 100},
    "new": {"index": 1, "unit": "currency", "scale": 100},
    "used": {"index": 2, "unit": "currency", "scale": 100},
    "sales_rank": {"index": 3, "unit": "rank", "scale": 1},
}

SERIES_ALIASES = {
    "amazon": "amazon",
    "new": "new",
    "used": "used",
    "sales": "sales_rank",
    "rank": "sales_rank",
    "salesrank": "sales_rank",
    "sales_rank": "sales_rank",
}

DEFAULT_SERIES = ["amazon", "new", "used", "sales_rank"]


def normalize_series_names(value: Any) -> list[str]:
    if value is None or value == "":
        return list(DEFAULT_SERIES)

    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(str(item).split(","))
        raw_items = [item.strip() for item in raw_items if item.strip()]
    else:
        raw_items = [str(value).strip()]

    normalized: list[str] = []
    for item in raw_items:
        key = item.lower().replace("-", "_")
        series = SERIES_ALIASES.get(key)
        if series is None:
            supported = ", ".join(sorted(SERIES_DEFINITIONS))
            raise ValueError(f"unsupported history series: {item}; supported: {supported}")
        if series not in normalized:
            normalized.append(series)
    return normalized or list(DEFAULT_SERIES)


def _convert_value(raw_value: int, *, unit: str, scale: int, include_missing: bool) -> float | int | None:
    if raw_value == -1:
        return None if include_missing else None
    if unit == "currency":
        return round(raw_value / scale, 2)
    return raw_value


def extract_history_rows(
    product: dict[str, Any],
    series_names: Any = None,
    *,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    asin = str(product.get("asin", ""))
    csv_history = product.get("csv")
    if not isinstance(csv_history, list):
        raise ValueError("product does not contain csv history")

    rows: list[dict[str, Any]] = []
    for series in normalize_series_names(series_names):
        definition = SERIES_DEFINITIONS[series]
        index = int(definition["index"])
        if index >= len(csv_history) or not isinstance(csv_history[index], list):
            continue

        values = csv_history[index]
        if len(values) % 2 != 0:
            raise ValueError(f"history series has odd value count: {series}")

        unit = str(definition["unit"])
        scale = int(definition["scale"])
        for offset in range(0, len(values), 2):
            keepa_minute = int(values[offset])
            raw_value = int(values[offset + 1])
            if raw_value == -1 and not include_missing:
                continue
            rows.append(
                {
                    "asin": asin,
                    "series": series,
                    "timestamp": keepa_minutes_to_iso(keepa_minute),
                    "keepa_minute": keepa_minute,
                    "value": _convert_value(raw_value, unit=unit, scale=scale, include_missing=include_missing),
                    "raw_value": raw_value,
                    "unit": unit,
                }
            )
    return rows


def history_rows_to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=HISTORY_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in HISTORY_FIELDS})
    return buffer.getvalue()


def history_rows_to_jsonl(rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + ("\n" if rows else "")


def write_history_export(rows: list[dict[str, Any]], output_path: Path | str, output_format: str) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "csv":
        content = history_rows_to_csv(rows)
    elif output_format == "jsonl":
        content = history_rows_to_jsonl(rows)
    elif output_format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    else:
        raise ValueError(f"unsupported history export format: {output_format}")
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "row_count": len(rows), "fields": list(HISTORY_FIELDS), "format": output_format}


def build_history_export_data(
    *,
    asin: str,
    domain: str,
    rows: list[dict[str, Any]],
    output_format: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "asin": asin,
        "domain": domain,
        "format": output_format,
        "row_count": len(rows),
        "fields": list(HISTORY_FIELDS),
    }
    if output_path:
        data["output"] = write_history_export(rows, output_path, output_format)
    elif output_format == "json":
        data["rows"] = rows
    elif output_format == "csv":
        data["content"] = history_rows_to_csv(rows)
    elif output_format == "jsonl":
        data["content"] = history_rows_to_jsonl(rows)
    else:
        raise ValueError(f"unsupported history export format: {output_format}")
    return data
