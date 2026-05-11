"""
keepa_cli/figures.py
文件说明：生成 Agent 报告可插入的本地 SVG 科学图。
主要职责：从产品对比、Agent 视图或 research_graph 输出中提取指标并绘制多面板 SVG。
依赖边界：仅使用 Python 标准库，不访问真实 Keepa API，不依赖浏览器或绘图库。
"""

from __future__ import annotations

import html
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from keepa_cli.product_view import _history_summary, _temporal_features
from keepa_cli.research_graph import extract_research_graphs


FIGURE_SCHEMA_VERSION = "2026-05-11.4"

FONT_FAMILY = "'Times New Roman', 'SimSun', '宋体', serif"

FIGURE_SET_CHOICES = ("all", "history", "compare", "audit")
FIGURE_SET_FIGURES = {
    "history": {"history-lines", "window-change-heatmap"},
    "compare": {"product-metric-comparison", "small-multiples"},
    "audit": {"risk-graph-summary"},
}

HISTORY_SERIES_LIMIT = 36
HISTORY_METRICS = ("new", "buy_box_shipping", "sales_rank", "review_count")


PALETTE = {
    "ink": "#1f2933",
    "muted": "#667085",
    "grid": "#d8dee8",
    "grid_light": "#eef2f7",
    "panel": "#ffffff",
    "teal": "#087f73",
    "blue": "#2f5fb3",
    "yellow": "#b7791f",
    "red": "#b42318",
    "green": "#18794e",
    "purple": "#6f4eb2",
    "orange": "#c05621",
}

SERIES_LABELS = {
    "new": "New price",
    "buy_box_shipping": "Buy box",
    "sales_rank": "Sales rank",
    "review_count": "Reviews",
    "rating": "Rating",
    "new_offer_count": "New offers",
    "new_fba_offer_count": "FBA offers",
}

SERIES_COLORS = {
    "new": PALETTE["teal"],
    "buy_box_shipping": PALETTE["blue"],
    "sales_rank": PALETTE["orange"],
    "review_count": PALETTE["purple"],
    "rating": PALETTE["green"],
    "new_offer_count": PALETTE["yellow"],
    "new_fba_offer_count": PALETTE["yellow"],
}

ASIN_COLORS = (
    PALETTE["teal"],
    PALETTE["blue"],
    PALETTE["orange"],
    PALETTE["purple"],
    PALETTE["green"],
    PALETTE["red"],
)


def build_research_figures(*, input_path: str, out_dir: str, title: str, figure_set: str = "all") -> dict[str, Any]:
    payload = _load_json_file(input_path)
    return build_research_figures_from_payload(payload, out_dir=out_dir, title=title, source_label=input_path, figure_set=figure_set)


def build_research_figures_from_payload(
    payload: Any,
    *,
    out_dir: str,
    title: str,
    source_label: str,
    figure_set: str = "all",
) -> dict[str, Any]:
    selected_figure_set = _normalize_figure_set(figure_set)
    figure_data = _figure_data(payload)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_path = out / "agent-research-summary.source.json"
    _write_text(source_path, json.dumps({"schema_version": FIGURE_SCHEMA_VERSION, **figure_data}, ensure_ascii=False, indent=2) + "\n")

    figure_items: list[dict[str, Any]] = []
    if selected_figure_set == "all":
        svg_path = out / "agent-research-summary.svg"
        svg_text = _summary_svg(figure_data, title=title)
        _write_text(svg_path, svg_text)
        figure_items.append(
            {
                "name": "agent-research-summary",
                "kind": "multi_panel_svg",
                "path": str(svg_path),
                "format": "svg",
                "size_bytes": svg_path.stat().st_size,
                "source_data_path": str(source_path),
                "source_data_bytes": source_path.stat().st_size,
                "panels": [
                    "product_metric_comparison",
                    "price_rank_history",
                    "window_change_heatmap",
                    "multi_asin_small_multiples",
                    "risk_and_graph_summary",
                ],
                "caption": "Overview page combining all Agent research figure panels for backward-compatible reports.",
            }
        )
    for spec in _filter_figure_specs(_single_figure_specs(figure_data, title=title), selected_figure_set):
        path = out / f"{spec['name']}.svg"
        _write_text(path, str(spec["svg"]))
        figure_items.append(
            {
                "name": spec["name"],
                "kind": spec["kind"],
                "path": str(path),
                "format": "svg",
                "size_bytes": path.stat().st_size,
                "source_data_path": str(source_path),
                "source_data_bytes": source_path.stat().st_size,
                "panels": [spec["panel"]],
                "x_axis": spec.get("x_axis"),
                "y_axis": spec.get("y_axis"),
                "caption": spec.get("caption"),
            }
        )
    return {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "title": title,
        "format": "svg",
        "figure_set": selected_figure_set,
        "available_figure_sets": list(FIGURE_SET_CHOICES),
        "figures": figure_items,
        "data_summary": {
            "product_count": len(figure_data["products"]),
            "risk_code_count": len(figure_data["risk_codes"]),
            "graph_entity_types": len(figure_data["entity_counts"]),
            "temporal_signal_count": len(figure_data["temporal_signals"]),
            "history_series_count": len(figure_data["history_series"]),
            "window_heatmap_cell_count": len(figure_data["window_heatmap"]),
            "small_multiple_count": len(figure_data["small_multiples"]),
        },
        "provenance": {
            "source": "local",
            "endpoint": "local://figures.research",
            "input": source_label,
            "generated_at": utc_now_iso(),
        },
    }


def _normalize_figure_set(value: str | None) -> str:
    figure_set = str(value or "all").strip().lower()
    if figure_set not in FIGURE_SET_CHOICES:
        choices = ", ".join(FIGURE_SET_CHOICES)
        raise ValueError(f"figure_set must be one of: {choices}")
    return figure_set


def _filter_figure_specs(specs: list[dict[str, Any]], figure_set: str) -> list[dict[str, Any]]:
    if figure_set == "all":
        return specs
    names = FIGURE_SET_FIGURES[figure_set]
    return [spec for spec in specs if str(spec.get("name") or "") in names]


def _figure_data(payload: Any) -> dict[str, Any]:
    products = _product_rows_for_figures(payload)
    history_series = _history_series_for_figures(payload)
    risk_codes = _risk_code_counts(payload)
    graphs = extract_research_graphs(payload)
    entity_counter: Counter[str] = Counter()
    for graph in graphs:
        counts = graph.get("entity_counts") if isinstance(graph.get("entity_counts"), Mapping) else {}
        for key, value in counts.items():
            entity_counter[str(key)] += int(value or 0)
    temporal = _temporal_signals(payload)
    return {
        "products": products,
        "risk_codes": [{"code": key, "count": value} for key, value in sorted(risk_codes.items())],
        "entity_counts": [{"type": key, "count": value} for key, value in sorted(entity_counter.items())],
        "temporal_signals": temporal,
        "history_series": history_series,
        "window_heatmap": _window_heatmap_for_figures(payload),
        "small_multiples": _small_multiples_for_figures(products, history_series),
    }


def _product_rows_for_figures(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        data = value.get("data") if isinstance(value.get("data"), Mapping) else {}
        compare_rows = data.get("rows") if isinstance(data.get("rows"), list) else value.get("rows")
        if isinstance(compare_rows, list):
            for row in compare_rows:
                if isinstance(row, Mapping):
                    rows.append(_product_metric_row(row))
        products = data.get("products") if isinstance(data.get("products"), list) else value.get("products")
        if isinstance(products, list):
            for product in products:
                if isinstance(product, Mapping):
                    rows.append(_product_metric_row(product))
        if not rows:
            for graph in extract_research_graphs(value):
                nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
                for node in nodes:
                    if not isinstance(node, Mapping) or node.get("type") != "product":
                        continue
                    attributes = node.get("attributes") if isinstance(node.get("attributes"), Mapping) else {}
                    rows.append(
                        _product_metric_row(
                            {
                                "asin": attributes.get("asin") or str(node.get("id") or "").removeprefix("product:"),
                                "title": node.get("label"),
                                "brand": attributes.get("brand"),
                                "monthly_sold": attributes.get("monthly_sold"),
                                "review_count": attributes.get("review_count"),
                                "sales_rank": attributes.get("sales_rank"),
                            }
                        )
                    )
        if not rows:
            body = data.get("body") if isinstance(data.get("body"), Mapping) else value.get("body")
            raw_products = body.get("products") if isinstance(body, Mapping) and isinstance(body.get("products"), list) else []
            for product in raw_products:
                if isinstance(product, Mapping):
                    rows.append(_product_metric_row(product))
        if not rows:
            raw_products = value.get("products") if isinstance(value.get("products"), list) else []
            for product in raw_products:
                if isinstance(product, Mapping):
                    rows.append(_product_metric_row(product))
    return _dedupe_products(rows)[:8]


def _product_metric_row(value: Mapping[str, Any]) -> dict[str, Any]:
    identity = value.get("identity") if isinstance(value.get("identity"), Mapping) else {}
    pricing = value.get("pricing") if isinstance(value.get("pricing"), Mapping) else {}
    demand = value.get("demand") if isinstance(value.get("demand"), Mapping) else {}
    rating = value.get("rating") if isinstance(value.get("rating"), Mapping) else {}
    return {
        "asin": str(value.get("asin") or identity.get("asin") or ""),
        "title": str(value.get("title") or identity.get("title") or "(untitled)"),
        "brand": str(value.get("brand") or identity.get("brand") or ""),
        "price": _first_number(value, "new_price", "buy_box_price") or _first_number(pricing, "new_price", "buy_box_price", "current"),
        "rank": _first_number(value, "sales_rank") or _first_number(demand, "sales_rank", "current_sales_rank"),
        "monthly_sold": _first_number(value, "monthly_sold") or _first_number(demand, "monthly_sold"),
        "review_count": _first_number(value, "review_count") or _first_number(rating, "review_count"),
    }


def _risk_code_counts(value: Any) -> Counter[str]:
    counter: Counter[str] = Counter()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            taxonomy = item.get("risk_taxonomy")
            if isinstance(taxonomy, Mapping):
                codes = taxonomy.get("codes") if isinstance(taxonomy.get("codes"), list) else []
                counter.update(str(code) for code in codes if code)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return counter


def _temporal_signals(value: Any) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key in ("temporal_features", "temporal_by_window", "history_features"):
                feature = item.get(key)
                if isinstance(feature, Mapping):
                    _collect_temporal_mapping(feature, signals, path=f"{path}.{key}")
            for key, child in item.items():
                visit(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "$")
    return signals[:16]


def _history_series_for_figures(value: Any) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    preferred = ("new", "buy_box_shipping", "sales_rank", "review_count", "rating", "new_offer_count")

    def visit(item: Any, path: str, asin: str | None) -> None:
        if isinstance(item, Mapping):
            identity = item.get("identity") if isinstance(item.get("identity"), Mapping) else {}
            current_asin = str(item.get("asin") or identity.get("asin") or asin or "")
            history = item.get("history_summary") if isinstance(item.get("history_summary"), Mapping) else {}
            if not history and isinstance(item.get("csv"), list):
                history = _history_summary(item, 120)
            bounded = item.get("bounded_history_points") if isinstance(item.get("bounded_history_points"), Mapping) else {}
            bounded_series = bounded.get("series") if isinstance(bounded.get("series"), Mapping) else {}
            history_series = history.get("series") if isinstance(history.get("series"), Mapping) else {}
            for name in preferred:
                entry = history_series.get(name) if isinstance(history_series.get(name), Mapping) else {}
                if not entry and isinstance(bounded_series.get(name), Mapping):
                    entry = bounded_series[name]
                points = _history_points(entry.get("last_points"))
                if len(points) >= 2:
                    series.append(
                        {
                            "asin": current_asin,
                            "name": name,
                            "unit": entry.get("unit"),
                            "path": f"{path}.history_summary.series.{name}.last_points",
                            "point_count": entry.get("point_count"),
                            "shown_points": len(points),
                            "data_basis": "bounded_history_points" if bounded_series else "history_summary.last_points",
                            "points": points[-60:],
                        }
                    )
            for key, child in item.items():
                visit(child, f"{path}.{key}", current_asin)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]", asin)

    visit(value, "$", None)
    return _dedupe_history_series(series)[:HISTORY_SERIES_LIMIT]


def _history_points(value: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return points
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        number = _num(item.get("value"))
        if number is None:
            continue
        points.append(
            {
                "x": index,
                "timestamp": item.get("timestamp"),
                "keepa_minute": item.get("keepa_minute"),
                "value": number,
            }
        )
    return points


def _dedupe_history_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in series:
        key = (str(item.get("asin") or ""), str(item.get("name") or ""), str(item.get("path") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _window_heatmap_for_figures(value: Any) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []

    def collect_from_windows(windows: Mapping[str, Any], *, path: str, asin: str | None) -> None:
        for window_name, bucket in windows.items():
            if not isinstance(bucket, Mapping):
                continue
            series_map = bucket.get("series") if isinstance(bucket.get("series"), Mapping) else bucket
            for series_name, series in series_map.items():
                if not isinstance(series, Mapping):
                    continue
                change = _num(series.get("change_pct"))
                if change is None:
                    continue
                cells.append(
                    {
                        "asin": asin,
                        "window": str(window_name),
                        "series": str(series_name),
                        "change_pct": change,
                        "direction": series.get("direction"),
                        "observed_days": series.get("observed_days"),
                        "path": f"{path}.{window_name}.series.{series_name}",
                    }
                )

    def visit(item: Any, path: str, asin: str | None) -> None:
        if isinstance(item, Mapping):
            identity = item.get("identity") if isinstance(item.get("identity"), Mapping) else {}
            current_asin = str(item.get("asin") or identity.get("asin") or asin or "")
            direct = item.get("temporal_by_window")
            if isinstance(direct, Mapping):
                collect_from_windows(direct, path=f"{path}.temporal_by_window", asin=current_asin)
            if not isinstance(direct, Mapping) and isinstance(item.get("csv"), list):
                direct = _raw_temporal_windows(item)
                if direct:
                    collect_from_windows(direct, path=f"{path}.csv.temporal_features", asin=current_asin)
            brief = item.get("agent_brief") if isinstance(item.get("agent_brief"), Mapping) else {}
            brief_windows = brief.get("temporal_by_window") if isinstance(brief.get("temporal_by_window"), Mapping) else {}
            if brief_windows:
                collect_from_windows(brief_windows, path=f"{path}.agent_brief.temporal_by_window", asin=current_asin)
            temporal = item.get("temporal_features") if isinstance(item.get("temporal_features"), Mapping) else {}
            series_map = temporal.get("series") if isinstance(temporal.get("series"), Mapping) else {}
            for series_name, series in series_map.items():
                windows = series.get("windows") if isinstance(series, Mapping) and isinstance(series.get("windows"), Mapping) else {}
                for window_name, window in windows.items():
                    if not isinstance(window, Mapping):
                        continue
                    change = _num(window.get("change_pct"))
                    if change is None:
                        continue
                    cells.append(
                        {
                            "asin": current_asin,
                            "window": str(window_name),
                            "series": str(series_name),
                            "change_pct": change,
                            "direction": window.get("trend_direction"),
                            "observed_days": window.get("observed_days"),
                            "path": f"{path}.temporal_features.series.{series_name}.windows.{window_name}",
                        }
                    )
            for key, child in item.items():
                visit(child, f"{path}.{key}", current_asin)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]", asin)

    visit(value, "$", None)
    return _dedupe_heatmap_cells(cells)[:80]


def _dedupe_heatmap_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for cell in cells:
        key = (str(cell.get("asin") or ""), str(cell.get("window") or ""), str(cell.get("series") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(cell)
    return result


def _raw_temporal_windows(product: Mapping[str, Any]) -> dict[str, Any]:
    temporal = _temporal_features(product, windows=(7, 30, 90, 180, 365))
    series_map = temporal.get("series") if isinstance(temporal.get("series"), Mapping) else {}
    windows: dict[str, dict[str, Any]] = {}
    for series_name, series in series_map.items():
        if not isinstance(series, Mapping):
            continue
        window_map = series.get("windows") if isinstance(series.get("windows"), Mapping) else {}
        for window_name, window in window_map.items():
            if not isinstance(window, Mapping):
                continue
            windows.setdefault(str(window_name), {"series": {}})["series"][str(series_name)] = window
    return windows


def _small_multiples_for_figures(products: list[Mapping[str, Any]], history_series: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    history_rows = _history_small_multiples(history_series)
    if history_rows:
        return history_rows
    metrics = [
        ("price", "Price", False),
        ("rank", "Rank", True),
        ("monthly_sold", "Sold", False),
        ("review_count", "Reviews", False),
    ]
    rows: list[dict[str, Any]] = []
    for product in products[:8]:
        points: list[dict[str, Any]] = []
        for key, label, lower_is_better in metrics:
            value = _num(product.get(key))
            if value is None:
                continue
            points.append({"metric": key, "label": label, "value": value, "lower_is_better": lower_is_better})
        if points:
            rows.append(
                {
                    "asin": product.get("asin"),
                    "label": product.get("asin") or product.get("title"),
                    "points": points,
                    "data_basis": "normalized_current_metrics",
                }
            )
    return _normalize_small_multiples(rows, metrics)


def _history_small_multiples(history_series: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    priority = HISTORY_METRICS
    for item in history_series:
        if not isinstance(item, Mapping):
            continue
        asin = str(item.get("asin") or "")
        name = str(item.get("name") or "")
        if not asin or name not in priority:
            continue
        points = item.get("points") if isinstance(item.get("points"), list) else []
        values = [_num(point.get("value")) for point in points if isinstance(point, Mapping)]
        numeric = [value for value in values if value is not None]
        if len(numeric) < 2:
            continue
        first = numeric[0]
        last = numeric[-1]
        if first == 0:
            change_pct = None
        else:
            change_pct = (last - first) / abs(first) * 100
        normalized_points = _normalize_series_points(numeric[-40:], invert=name == "sales_rank")
        grouped.setdefault(
            asin,
            {
                "asin": asin,
                "label": asin,
                "series": [],
                "data_basis": "bounded_history_points" if item.get("data_basis") == "bounded_history_points" else "history_summary.last_points",
            },
        )["series"].append(
            {
                "metric": name,
                "label": SERIES_LABELS.get(name, name),
                "color": SERIES_COLORS.get(name, PALETTE["blue"]),
                "unit": item.get("unit"),
                "point_count": len(normalized_points),
                "start": first,
                "end": last,
                "change_pct": change_pct,
                "normalized_points": normalized_points,
            }
        )
    rows = list(grouped.values())
    rows.sort(key=lambda row: str(row.get("asin") or ""))
    for row in rows:
        row["series"].sort(key=lambda entry: priority.index(str(entry.get("metric"))) if entry.get("metric") in priority else 99)
    return rows[:6]


def _normalize_series_points(values: list[float], *, invert: bool = False) -> list[dict[str, float]]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    span = high - low or 1
    count = len(values)
    points: list[dict[str, float]] = []
    for index, value in enumerate(values):
        score = 0.5 if high == low else (value - low) / span
        if invert:
            score = 1 - score
        points.append(
            {
                "x": round(index / max(count - 1, 1), 4),
                "y": round(max(0.0, min(1.0, score)), 4),
                "value": value,
            }
        )
    return points


def _normalize_small_multiples(rows: list[dict[str, Any]], metrics: list[tuple[str, str, bool]]) -> list[dict[str, Any]]:
    ranges: dict[str, tuple[float, float]] = {}
    for key, _, _ in metrics:
        values = [_num(point.get("value")) for row in rows for point in row.get("points", []) if point.get("metric") == key]
        numeric = [value for value in values if value is not None]
        if numeric:
            ranges[key] = (min(numeric), max(numeric))
    for row in rows:
        for point in row.get("points", []):
            key = str(point.get("metric") or "")
            value = _num(point.get("value")) or 0
            low, high = ranges.get(key, (0, 1))
            score = 0.5 if high == low else (value - low) / (high - low)
            if point.get("lower_is_better"):
                score = 1 - score
            point["normalized_score"] = round(max(0.0, min(1.0, score)), 4)
    return rows


def _collect_temporal_mapping(value: Mapping[str, Any], signals: list[dict[str, Any]], *, path: str) -> None:
    for key, item in value.items():
        if isinstance(item, Mapping):
            flat = {str(k): v for k, v in item.items() if isinstance(v, (int, float, str, bool)) or v is None}
            numeric = {k: v for k, v in flat.items() if isinstance(v, (int, float))}
            if numeric:
                primary_key = next(iter(numeric))
                signals.append({"name": str(key), "path": path, "metric": primary_key, "value": numeric[primary_key]})
            _collect_temporal_mapping(item, signals, path=f"{path}.{key}")


def _summary_svg(data: Mapping[str, Any], *, title: str) -> str:
    width = 1280
    height = 1260
    panels = [
        _panel_product_comparison(data.get("products") or [], x=44, y=92, w=372, h=320),
        _panel_history_lines(data.get("history_series") or [], x=454, y=92, w=782, h=360),
        _panel_window_heatmap(data.get("window_heatmap") or [], x=44, y=490, w=590, h=320),
        _panel_small_multiples(data.get("small_multiples") or [], x=680, y=490, w=556, h=360),
        _panel_risk_graph_summary(
            data.get("risk_codes") or [],
            data.get("entity_counts") or [],
            data.get("temporal_signals") or [],
            x=44,
            y=890,
            w=1192,
            h=260,
        ),
    ]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
  <rect width="{width}" height="{height}" fill="#f7f8fb"/>
  <text x="44" y="46" font-family="{FONT_FAMILY}" font-size="24" font-weight="700" fill="{PALETTE['ink']}">{_esc(title)}</text>
  <text x="44" y="70" font-family="{FONT_FAMILY}" font-size="12" fill="{PALETTE['muted']}">Agent-ready SVG generated from local Keepa evidence; history, windows, comparison metrics, risk, and graph entities stay linked to source JSON.</text>
  {''.join(panels)}
</svg>
"""


def _single_figure_specs(data: Mapping[str, Any], *, title: str) -> list[dict[str, Any]]:
    return [
        {
            "name": "product-metric-comparison",
            "kind": "product_metric_bar_svg",
            "panel": "product_metric_comparison",
            "x_axis": "Product ASIN",
            "y_axis": "Primary metric value",
            "caption": "Current product metric comparison; monthlySold is preferred when present, otherwise review count.",
            "svg": _single_svg(
                _panel_product_comparison(data.get("products") or [], x=56, y=92, w=760, h=430),
                title=f"{title}: product metric comparison",
                subtitle="Current product-level signal; monthlySold is preferred when available.",
                caption="Bars encode the selected current metric. Values are copied from the Agent view source JSON.",
                width=880,
                height=620,
            ),
        },
        {
            "name": "history-lines",
            "kind": "history_line_svg",
            "panel": "price_rank_history",
            "x_axis": "Recent Keepa history point index",
            "y_axis": "Series value",
            "caption": "Bounded recent Keepa history points for price, rank, and review series.",
            "svg": _single_svg(
                _panel_history_lines(data.get("history_series") or [], x=60, y=96, w=1040, h=560),
                title=f"{title}: bounded history lines",
                subtitle="Recent Keepa samples retained for Agent-safe inspection, normalized per metric.",
                caption="Each row is one metric; each color is one ASIN. Sales rank is inverted so upward means better.",
                width=1160,
                height=760,
            ),
        },
        {
            "name": "window-change-heatmap",
            "kind": "window_heatmap_svg",
            "panel": "window_change_heatmap",
            "x_axis": "Temporal window",
            "y_axis": "Keepa series",
            "caption": "Percent changes across configured temporal windows.",
            "svg": _single_svg(
                _panel_window_heatmap(data.get("window_heatmap") or [], x=56, y=92, w=780, h=430),
                title=f"{title}: window change heatmap",
                subtitle="Percent change by series and window; green means lower, red means higher.",
                caption="Cells use the Agent temporal_by_window / temporal_features fields, not a new Keepa request.",
                width=900,
                height=620,
            ),
        },
        {
            "name": "small-multiples",
            "kind": "small_multiples_svg",
            "panel": "multi_asin_small_multiples",
            "x_axis": "Recent history timeline",
            "y_axis": "Normalized value",
            "caption": "Multi-ASIN recent history curves; rank is inverted so higher means better. Falls back to current metrics when history is absent.",
            "svg": _single_svg(
                _panel_small_multiples(data.get("small_multiples") or [], x=60, y=96, w=1040, h=560),
                title=f"{title}: multi-ASIN small multiples",
                subtitle="Comparable recent history curves normalized within each metric.",
                caption="Each card is one ASIN with shared metric colors; lines use bounded history points retained in the Agent-safe compare output.",
                width=1160,
                height=760,
            ),
        },
        {
            "name": "risk-graph-summary",
            "kind": "risk_graph_bar_svg",
            "panel": "risk_and_graph_summary",
            "x_axis": "Audit category",
            "y_axis": "Count or signal magnitude",
            "caption": "Risk taxonomy, research graph entity counts, and fallback temporal signals.",
            "svg": _single_svg(
                _panel_risk_graph_summary(
                    data.get("risk_codes") or [],
                    data.get("entity_counts") or [],
                    data.get("temporal_signals") or [],
                    x=56,
                    y=92,
                    w=900,
                    h=430,
                ),
                title=f"{title}: risk and graph audit",
                subtitle="Structured audit signals for Agent follow-up decisions.",
                caption="Risk codes and graph entities come from local Agent output; no live request is made during figure generation.",
                width=1020,
                height=620,
            ),
        },
    ]


def _single_svg(panel: str, *, title: str, subtitle: str, caption: str, width: int, height: int) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
  <rect width="{width}" height="{height}" fill="#ffffff"/>
  <rect x="28" y="24" width="{width - 56}" height="{height - 48}" rx="10" fill="#ffffff" stroke="#eef2f7" stroke-width="1"/>
  <text x="56" y="42" font-family="{FONT_FAMILY}" font-size="21" font-weight="700" fill="{PALETTE['ink']}">{_esc(title)}</text>
  <text x="56" y="66" font-family="{FONT_FAMILY}" font-size="12" fill="{PALETTE['muted']}">{_esc(subtitle)}</text>
  {panel}
  <text x="56" y="{height - 38}" font-family="{FONT_FAMILY}" font-size="11" fill="{PALETTE['muted']}">{_esc(caption)}</text>
</svg>
"""


def _panel_product_comparison(products: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    metric = "monthly_sold" if any(_num(p.get("monthly_sold")) is not None for p in products) else "review_count"
    visible = products[:6]
    values = [_num(product.get(metric)) or 0 for product in visible]
    max_value = max(values, default=1) or 1
    plot_x = x + 142
    plot_y = y + 82
    plot_w = max(140, w - 220)
    rows: list[str] = []
    if visible:
        rows.extend(_axis_ticks(x=plot_x, y=plot_y + len(visible) * 34 + 8, w=plot_w, max_value=max_value, label=metric.replace("_", " ")))
        for index, product in enumerate(visible):
            row_y = plot_y + index * 34
            value = _num(product.get(metric)) or 0
            bar_w = int(plot_w * value / max_value)
            label = product.get("asin") or product.get("title")
            rows.append(
                f'<text x="{x + 20}" y="{row_y + 14}" font-family="{FONT_FAMILY}" font-size="11" fill="{PALETTE["ink"]}">{_esc(label)}</text>'
                f'<rect x="{plot_x}" y="{row_y}" width="{max(bar_w, 2)}" height="18" rx="3" fill="{PALETTE["blue"]}"/>'
                f'<text x="{plot_x + 8 + bar_w}" y="{row_y + 14}" font-family="{FONT_FAMILY}" font-size="10" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
            )
    else:
        rows.append(_empty_panel_text(x, y, "No product metric rows found"))
    return (
        _panel_frame(x, y, w, h, "A  Product comparison", f"Primary metric: {metric.replace('_', ' ')}")
        + "".join(rows)
        + _axis_label(plot_x + plot_w / 2, y + h - 18, metric.replace("_", " "), anchor="middle")
        + "</g>"
    )


def _panel_history_lines(series: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    elements: list[str] = []
    selected = _select_history_series(series)
    if selected:
        compact = h < 460
        plot_x = x + 118
        plot_y = y + (82 if compact else 96)
        plot_w = w - 182
        metric_names = _history_metric_order(selected)
        row_gap = 16 if compact else 22
        min_row_h = 38 if compact else 64
        row_h = max(min_row_h, int((h - 172 - row_gap * (len(metric_names) - 1)) / max(len(metric_names), 1)))
        asin_colors = _asin_color_map(selected)
        for row_index, metric in enumerate(metric_names):
            top = plot_y + row_index * (row_h + row_gap)
            metric_series = [item for item in selected if item.get("name") == metric]
            axis_label = SERIES_LABELS.get(metric, metric)
            elements.extend(
                _normalized_axes(
                    plot_x,
                    top,
                    plot_w,
                    row_h,
                    x_label="",
                    y_label="",
                    y_ticks=False,
                    x_ticks=False,
                )
            )
            elements.append(
                f'<text x="{x + 26}" y="{top + 18}" font-family="{FONT_FAMILY}" font-size="10.5" font-weight="700" fill="{PALETTE["ink"]}">{_esc(axis_label)}</text>'
            )
            elements.append(
                f'<text x="{plot_x - 10:.1f}" y="{top + 3:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["muted"]}">1</text>'
            )
            elements.append(
                f'<text x="{plot_x - 10:.1f}" y="{top + row_h + 3:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["muted"]}">0</text>'
            )
            for item in metric_series[:6]:
                values = _numeric_history_values(item)
                if len(values) < 2:
                    continue
                points = _normalize_series_points(values[-60:], invert=metric == "sales_rank")
                coords = [
                    f"{plot_x + point['x'] * plot_w:.1f},{top + row_h - point['y'] * row_h:.1f}"
                    for point in points
                ]
                asin = str(item.get("asin") or "product")
                color = asin_colors.get(asin, PALETTE["blue"])
                elements.append(
                    f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
                )
                elements.append(
                    f'<circle cx="{coords[-1].split(",")[0]}" cy="{coords[-1].split(",")[1]}" r="2.7" fill="#ffffff" stroke="{color}" stroke-width="1.5"/>'
                )
            if row_index == len(metric_names) - 1 and not compact:
                elements.append(f'<text x="{plot_x:.1f}" y="{top + row_h + 18:.1f}" font-family="{FONT_FAMILY}" font-size="8.5" fill="{PALETTE["muted"]}">oldest retained point</text>')
                elements.append(f'<text x="{plot_x + plot_w:.1f}" y="{top + row_h + 18:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="8.5" fill="{PALETTE["muted"]}">latest retained point</text>')
        legend_y = y + h - (18 if compact else 30)
        legend_x = plot_x
        for index, asin in enumerate(list(asin_colors)[:6]):
            lx = legend_x + index * 142
            color = asin_colors[asin]
            elements.append(f'<line x1="{lx:.1f}" y1="{legend_y - 4:.1f}" x2="{lx + 22:.1f}" y2="{legend_y - 4:.1f}" stroke="{color}" stroke-width="2.2"/>')
            elements.append(f'<text x="{lx + 28:.1f}" y="{legend_y:.1f}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["ink"]}">{_esc(asin[:14])}</text>')
    if not elements:
        elements.append(_empty_panel_text(x, y, "No history_summary.last_points with numeric values found"))
    return _panel_frame(x, y, w, h, "B  Price / rank history", "One row per metric; colors compare ASINs on normalized retained history") + "".join(elements) + "</g>"


def _select_history_series(series: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    priority = {name: index for index, name in enumerate(HISTORY_METRICS)}
    return sorted(
        [item for item in series if isinstance(item, Mapping) and item.get("name") in priority],
        key=lambda item: (str(item.get("asin") or ""), priority.get(str(item.get("name") or ""), 99)),
    )[:24]


def _history_metric_order(series: list[Mapping[str, Any]]) -> list[str]:
    present = {str(item.get("name") or "") for item in series if isinstance(item, Mapping)}
    return [name for name in HISTORY_METRICS if name in present]


def _asin_color_map(series: list[Mapping[str, Any]]) -> dict[str, str]:
    asins: list[str] = []
    for item in series:
        asin = str(item.get("asin") or "product")
        if asin and asin not in asins:
            asins.append(asin)
    return {asin: ASIN_COLORS[index % len(ASIN_COLORS)] for index, asin in enumerate(asins)}


def _numeric_history_values(item: Mapping[str, Any]) -> list[float]:
    points = item.get("points") if isinstance(item.get("points"), list) else []
    numeric = [_num(point.get("value")) for point in points if isinstance(point, Mapping)]
    return [value for value in numeric if value is not None]


def _normalized_axes(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    x_label: str,
    y_label: str,
    y_ticks: bool = True,
    x_ticks: bool = True,
) -> list[str]:
    elements: list[str] = []
    for index, value in enumerate((1.0, 0.5, 0.0)):
        ty = y + h - value * h
        stroke = PALETTE["grid"] if index in (0, 2) else PALETTE["grid_light"]
        elements.append(f'<line x1="{x:.1f}" y1="{ty:.1f}" x2="{x + w:.1f}" y2="{ty:.1f}" stroke="{stroke}" stroke-width="1"/>')
        if y_ticks:
            elements.append(
                f'<text x="{x - 9:.1f}" y="{ty + 3:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="8.5" fill="{PALETTE["muted"]}">{value:g}</text>'
            )
    elements.extend(
        [
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y + h:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>',
            f'<line x1="{x:.1f}" y1="{y + h:.1f}" x2="{x + w:.1f}" y2="{y + h:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>',
        ]
    )
    if x_ticks:
        elements.extend(
            [
                f'<text x="{x:.1f}" y="{y + h + 19:.1f}" font-family="{FONT_FAMILY}" font-size="8.5" fill="{PALETTE["muted"]}">oldest</text>',
                f'<text x="{x + w:.1f}" y="{y + h + 19:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="8.5" fill="{PALETTE["muted"]}">latest</text>',
            ]
        )
    if x_label:
        elements.append(_axis_label(x + w / 2, y + h + 38, x_label, anchor="middle"))
    if y_label:
        elements.append(_rotated_axis_label(x - 50, y + h / 2, y_label))
    return elements


def _panel_window_heatmap(cells: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    wanted_series = ["new", "buy_box_shipping", "sales_rank", "review_count", "rating", "new_offer_count"]
    windows = sorted({str(cell.get("window") or "") for cell in cells if cell.get("window")}, key=_window_sort_key)
    series = [name for name in wanted_series if any(cell.get("series") == name for cell in cells)]
    if not series:
        series = sorted({str(cell.get("series") or "") for cell in cells if cell.get("series")})[:6]
    windows = windows[:6]
    series = series[:6]
    if not windows or not series:
        return _panel_frame(x, y, w, h, "C  Window change heatmap", "Percent change by official Keepa history windows") + _empty_panel_text(
            x, y, "No temporal windows found; run with --agent-view --view research"
        ) + "</g>"
    cell_w = min(76, max(38, int((w - 170) / max(len(windows), 1))))
    cell_h = min(30, max(20, int((h - 120) / max(len(series), 1))))
    start_x = x + 140
    start_y = y + 78
    lookup = {(str(cell.get("window")), str(cell.get("series"))): cell for cell in cells}
    elements: list[str] = [
        _axis_label(start_x + max(len(windows), 1) * cell_w / 2, start_y - 34, "window", anchor="middle"),
        _rotated_axis_label(x + 32, start_y + max(len(series), 1) * cell_h / 2, "series"),
    ]
    for col, window in enumerate(windows):
        elements.append(
            f'<text x="{start_x + col * cell_w + cell_w / 2:.1f}" y="{start_y - 12}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["muted"]}">{_esc(window.replace("recent_", ""))}</text>'
        )
    for row, name in enumerate(series):
        y0 = start_y + row * cell_h
        elements.append(f'<text x="{x + 20}" y="{y0 + 18}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["ink"]}">{_esc(name[:18])}</text>')
        for col, window in enumerate(windows):
            cell = lookup.get((window, name))
            change = _num(cell.get("change_pct")) if isinstance(cell, Mapping) else None
            color = _heat_color(change)
            label = "" if change is None else _fmt(change)
            x0 = start_x + col * cell_w
            elements.append(f'<rect x="{x0}" y="{y0}" width="{cell_w - 4}" height="{cell_h - 4}" rx="4" fill="{color}" stroke="#ffffff" stroke-width="1"/>')
            if label:
                elements.append(
                    f'<text x="{x0 + (cell_w - 4) / 2:.1f}" y="{y0 + 17}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["ink"]}">{_esc(label)}%</text>'
                )
    legend_x = start_x
    legend_y = y + h - 44
    legend = [(-30, "lower"), (0, "flat"), (30, "higher")]
    for index, (value, label) in enumerate(legend):
        lx = legend_x + index * 82
        elements.append(f'<rect x="{lx}" y="{legend_y}" width="24" height="12" rx="3" fill="{_heat_color(value)}" stroke="#ffffff" stroke-width="1"/>')
        elements.append(f'<text x="{lx + 30}" y="{legend_y + 10}" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["muted"]}">{label}</text>')
    return _panel_frame(x, y, w, h, "C  Window change heatmap", "Percent change by official Keepa history windows") + "".join(elements) + "</g>"


def _heat_color(value: float | None) -> str:
    if value is None:
        return "#edf1f7"
    if value < -20:
        return "#b7e4d8"
    if value < -5:
        return "#d9f1e9"
    if value > 20:
        return "#f3b6b1"
    if value > 5:
        return "#f8d8ca"
    return "#eef2f7"


def _axis_ticks(*, x: float, y: float, w: float, max_value: float, label: str) -> list[str]:
    elements = [f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + w:.1f}" y2="{y:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>']
    for index in range(4):
        value = max_value * index / 3
        tx = x + w * index / 3
        elements.append(f'<line x1="{tx:.1f}" y1="{y - 4:.1f}" x2="{tx:.1f}" y2="{y + 4:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(
            f'<text x="{tx:.1f}" y="{y + 18:.1f}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["muted"]}">{_esc(_fmt(value))}</text>'
        )
    elements.append(_axis_label(x + w, y + 34, label, anchor="end"))
    return elements


def _xy_axes(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    x_label: str,
    y_label: str,
    min_value: float,
    max_value: float,
    x_ticks: int,
) -> list[str]:
    elements = [
        f'<line x1="{x:.1f}" y1="{y + h:.1f}" x2="{x + w:.1f}" y2="{y + h:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>',
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y + h:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>',
    ]
    for index in range(4):
        value = min_value + (max_value - min_value) * index / 3
        ty = y + h - h * index / 3
        elements.append(f'<line x1="{x - 4:.1f}" y1="{ty:.1f}" x2="{x + w:.1f}" y2="{ty:.1f}" stroke="{PALETTE["grid"]}" stroke-width="0.65" opacity="0.85"/>')
        elements.append(
            f'<text x="{x - 8:.1f}" y="{ty + 3:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["muted"]}">{_esc(_fmt(value))}</text>'
        )
    for index in range(min(5, max(x_ticks, 1))):
        denom = max(min(5, max(x_ticks, 1)) - 1, 1)
        value = round((x_ticks - 1) * index / denom)
        tx = x + w * index / denom
        elements.append(f'<line x1="{tx:.1f}" y1="{y + h:.1f}" x2="{tx:.1f}" y2="{y + h + 4:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(
            f'<text x="{tx:.1f}" y="{y + h + 18:.1f}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["muted"]}">{value}</text>'
        )
    elements.append(_axis_label(x + w / 2, y + h + 38, x_label, anchor="middle"))
    elements.append(_rotated_axis_label(x - 52, y + h / 2, y_label))
    return elements


def _axis_label(x: float, y: float, text: str, *, anchor: str = "start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["muted"]}">{_esc(text)}</text>'


def _rotated_axis_label(x: float, y: float, text: str) -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" transform="rotate(-90 {x:.1f} {y:.1f})" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["muted"]}">{_esc(text)}</text>'


def _panel_small_multiples(rows: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    if any(isinstance(row, Mapping) and isinstance(row.get("series"), list) for row in rows):
        return _panel_history_small_multiples(rows, x=x, y=y, w=w, h=h)
    return _panel_metric_small_multiples(rows, x=x, y=y, w=w, h=h)


def _panel_history_small_multiples(rows: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    elements: list[str] = []
    visible = [row for row in rows[:6] if isinstance(row, Mapping)]
    columns = 2 if w >= 720 and len(visible) > 1 else 1
    gap_x = 22
    gap_y = 18
    top_start = y + 112
    available_h = max(130, h - 164)
    row_count = max(1, (len(visible) + columns - 1) // columns)
    card_w = int((w - 40 - gap_x * (columns - 1)) / columns)
    max_card_h = 330 if row_count == 1 else 230
    card_h = min(max_card_h, max(122, int((available_h - gap_y * (row_count - 1)) / row_count)))
    metric_order = [name for name in HISTORY_METRICS if any(name == series.get("metric") for row in visible for series in row.get("series", []) if isinstance(series, Mapping))]
    legend_y = y + 74
    legend_x = x + 24
    for metric_index, metric in enumerate(metric_order[:4]):
        lx = legend_x + metric_index * 150
        color = SERIES_COLORS.get(metric, PALETTE["blue"])
        label = SERIES_LABELS.get(metric, metric)
        elements.append(f'<line x1="{lx}" y1="{legend_y - 4}" x2="{lx + 24}" y2="{legend_y - 4}" stroke="{color}" stroke-width="2"/>')
        elements.append(f'<text x="{lx + 30}" y="{legend_y}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["muted"]}">{_esc(label)}</text>')
    for index, row in enumerate(visible):
        col = index % columns
        line = index // columns
        left = x + 20 + col * (card_w + gap_x)
        top = top_start + line * (card_h + gap_y)
        plot_x = left + 42
        plot_y = top + 34
        plot_w = card_w - 66
        plot_h = card_h - 76
        elements.append(f'<rect x="{left}" y="{top}" width="{card_w}" height="{card_h}" rx="6" fill="#ffffff" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(f'<text x="{left + 12}" y="{top + 18}" font-family="{FONT_FAMILY}" font-size="10.5" font-weight="700" fill="{PALETTE["ink"]}">{_esc(str(row.get("label") or row.get("asin") or "")[:28])}</text>')
        elements.extend(_mini_axes(plot_x, plot_y, plot_w, plot_h))
        for series in [item for item in row.get("series", []) if isinstance(item, Mapping)][:4]:
            points = series.get("normalized_points") if isinstance(series.get("normalized_points"), list) else []
            coords = []
            for point in points:
                if not isinstance(point, Mapping):
                    continue
                px = plot_x + (_num(point.get("x")) or 0) * plot_w
                py = plot_y + plot_h - (_num(point.get("y")) or 0) * plot_h
                coords.append(f"{px:.1f},{py:.1f}")
            if len(coords) < 2:
                continue
            color = str(series.get("color") or SERIES_COLORS.get(str(series.get("metric") or ""), PALETTE["blue"]))
            elements.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>')
            elements.append(f'<circle cx="{coords[-1].split(",")[0]}" cy="{coords[-1].split(",")[1]}" r="2.5" fill="#ffffff" stroke="{color}" stroke-width="1.4"/>')
        summary = _small_multiple_change_summary(row)
        if summary:
            elements.append(f'<text x="{left + 12}" y="{top + card_h - 14}" font-family="{FONT_FAMILY}" font-size="8.2" fill="{PALETTE["muted"]}">{_esc(summary)}</text>')
    if not elements:
        elements.append(_empty_panel_text(x, y, "No bounded history points found"))
    return _panel_frame(x, y, w, h, "D  Multi-ASIN history small multiples", "Each card is one ASIN; shared metric colors show retained real Keepa history") + "".join(elements) + "</g>"


def _panel_metric_small_multiples(rows: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    elements = []
    card_w = int((w - 58) / 2)
    card_h = 88
    for index, row in enumerate(rows[:6]):
        col = index % 2
        line = index // 2
        left = x + 20 + col * (card_w + 18)
        top = y + 68 + line * (card_h + 12)
        points = [point for point in row.get("points", []) if isinstance(point, Mapping)]
        coords = []
        point_elements = []
        elements.append(f'<rect x="{left}" y="{top}" width="{card_w}" height="{card_h}" rx="6" fill="#fbfcff" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(f'<text x="{left + 10}" y="{top + 16}" font-family="{FONT_FAMILY}" font-size="9" font-weight="700" fill="{PALETTE["ink"]}">{_esc(str(row.get("label") or "")[:24])}</text>')
        elements.append(f'<line x1="{left + 16}" y1="{top + 62}" x2="{left + card_w - 16}" y2="{top + 62}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(f'<line x1="{left + 16}" y1="{top + 28}" x2="{left + 16}" y2="{top + 62}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(f'<text x="{left + 10}" y="{top + 31}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">1</text>')
        elements.append(f'<text x="{left + 10}" y="{top + 64}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">0</text>')
        for point_index, point in enumerate(points[:4]):
            score = _num(point.get("normalized_score")) or 0
            px = left + 18 + point_index * ((card_w - 36) / max(min(len(points), 4) - 1, 1))
            py = top + 62 - score * 34
            coords.append(f"{px:.1f},{py:.1f}")
            point_elements.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="{PALETTE["blue"]}"/>')
            point_elements.append(
                f'<text x="{px:.1f}" y="{top + 78}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">{_esc(point.get("label"))}</text>'
            )
        if len(coords) >= 2:
            elements.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{PALETTE["blue"]}" stroke-width="1.8"/>')
        elements.extend(point_elements)
    if not elements:
        elements.append(_empty_panel_text(x, y, "No comparable product metrics found"))
    return _panel_frame(x, y, w, h, "D  Multi-ASIN small multiples", "Normalized current metrics; rank is inverted so higher is better") + "".join(elements) + "</g>"


def _mini_axes(x: float, y: float, w: float, h: float) -> list[str]:
    return [
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + w:.1f}" y2="{y:.1f}" stroke="{PALETTE["grid_light"]}" stroke-width="1"/>',
        f'<line x1="{x:.1f}" y1="{y + h / 2:.1f}" x2="{x + w:.1f}" y2="{y + h / 2:.1f}" stroke="{PALETTE["grid_light"]}" stroke-width="1"/>',
        f'<line x1="{x:.1f}" y1="{y + h:.1f}" x2="{x + w:.1f}" y2="{y + h:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>',
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y + h:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>',
        f'<text x="{x - 7:.1f}" y="{y + 3:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">1</text>',
        f'<text x="{x - 7:.1f}" y="{y + h + 3:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">0</text>',
        f'<text x="{x:.1f}" y="{y + h + 17:.1f}" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">old</text>',
        f'<text x="{x + w:.1f}" y="{y + h + 17:.1f}" text-anchor="end" font-family="{FONT_FAMILY}" font-size="7" fill="{PALETTE["muted"]}">new</text>',
    ]


def _small_multiple_change_summary(row: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for series in [item for item in row.get("series", []) if isinstance(item, Mapping)]:
        metric = str(series.get("metric") or "")
        if metric not in HISTORY_METRICS:
            continue
        change = _num(series.get("change_pct"))
        if change is None:
            continue
        label = SERIES_LABELS.get(metric, metric)
        parts.append(f"{label} {change:+.0f}%")
        if len(parts) >= 3:
            break
    return " | ".join(parts)


def _panel_risk_graph_summary(
    risks: list[Mapping[str, Any]],
    entities: list[Mapping[str, Any]],
    signals: list[Mapping[str, Any]],
    *,
    x: int,
    y: int,
    w: int,
    h: int,
) -> str:
    return (
        _panel_frame(x, y, w, h, "E  Risk, graph, and fallback temporal signals", "Compact audit summary for Agent reports")
        + _risk_bars(risks, x=x + 12, y=y + 54, w=360, h=h - 70)
        + _entity_bars(entities, x=x + 410, y=y + 54, w=350, h=h - 70)
        + _temporal_signal_bars(signals, x=x + 800, y=y + 54, w=360, h=h - 70)
        + "</g>"
    )


def _risk_bars(risks: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    values = [(str(item.get("code") or ""), int(item.get("count") or 0)) for item in risks if item.get("code")]
    max_value = max((value for _, value in values), default=1) or 1
    rows = []
    for index, (code, value) in enumerate(values[:5]):
        row_y = y + index * 27
        color = PALETTE["yellow"] if code == "data_missing" else PALETTE["red"] if "unstable" in code or "declining" in code else PALETTE["teal"]
        bar_w = int((w - 190) * value / max_value)
        rows.append(
            f'<text x="{x}" y="{row_y + 13}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["ink"]}">{_esc(code[:22])}</text>'
            f'<rect x="{x + 160}" y="{row_y}" width="{max(bar_w, 2)}" height="15" rx="3" fill="{color}"/>'
            f'<text x="{x + 166 + bar_w}" y="{row_y + 12}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["muted"]}">{value}</text>'
        )
    if not rows:
        rows.append(f'<text x="{x}" y="{y + 18}" font-family="{FONT_FAMILY}" font-size="10" fill="{PALETTE["muted"]}">No risk codes</text>')
    return "".join(rows)


def _entity_bars(entities: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    values = [(str(item.get("type") or ""), int(item.get("count") or 0)) for item in entities if item.get("type")]
    max_value = max((value for _, value in values), default=1) or 1
    bars = []
    bar_w = max(20, int((w - 28) / max(len(values), 1)) - 8)
    for index, (kind, value) in enumerate(values[:8]):
        left = x + index * (bar_w + 8)
        bar_h = int((h - 44) * value / max_value)
        top = y + h - 26 - bar_h
        bars.append(
            f'<rect x="{left}" y="{top}" width="{bar_w}" height="{bar_h}" rx="3" fill="{PALETTE["teal"]}"/>'
            f'<text x="{left + bar_w / 2:.1f}" y="{top - 6}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="10" fill="{PALETTE["muted"]}">{value}</text>'
            f'<text x="{left + bar_w / 2:.1f}" y="{y + h - 6}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="8" fill="{PALETTE["ink"]}">{_esc(kind[:9])}</text>'
        )
    if not bars:
        bars.append(f'<text x="{x}" y="{y + 18}" font-family="{FONT_FAMILY}" font-size="10" fill="{PALETTE["muted"]}">No graph entities</text>')
    return "".join(bars)


def _temporal_signal_bars(signals: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    values = []
    for item in signals[:5]:
        value = _num(item.get("value"))
        if value is not None:
            values.append((str(item.get("name") or item.get("metric") or "signal"), value))
    max_abs = max((abs(value) for _, value in values), default=1) or 1
    rows = []
    mid = x + 190
    for index, (name, value) in enumerate(values):
        row_y = y + index * 27
        bar_w = int((w - 240) * abs(value) / max_abs)
        color = PALETTE["green"] if value >= 0 else PALETTE["red"]
        bx = mid if value >= 0 else mid - bar_w
        rows.append(
            f'<text x="{x}" y="{row_y + 12}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["ink"]}">{_esc(name[:28])}</text>'
            f'<line x1="{mid}" y1="{row_y - 3}" x2="{mid}" y2="{row_y + 17}" stroke="{PALETTE["grid"]}" stroke-width="1"/>'
            f'<rect x="{bx}" y="{row_y}" width="{max(bar_w, 2)}" height="14" rx="3" fill="{color}"/>'
            f'<text x="{mid + (bar_w + 8 if value >= 0 else -bar_w - 8)}" y="{row_y + 11}" text-anchor="{"start" if value >= 0 else "end"}" font-family="{FONT_FAMILY}" font-size="9" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
        )
    if not rows:
        rows.append(f'<text x="{x}" y="{y + 18}" font-family="{FONT_FAMILY}" font-size="10" fill="{PALETTE["muted"]}">No fallback signals</text>')
    return "".join(rows)


def _panel_frame(x: int, y: int, w: int, h: int, title: str, subtitle: str) -> str:
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PALETTE["panel"]}" stroke="{PALETTE["grid"]}" stroke-width="1"/>'
        f'<text x="{x + 20}" y="{y + 28}" font-family="{FONT_FAMILY}" font-size="14" font-weight="700" fill="{PALETTE["ink"]}">{_esc(title)}</text>'
        f'<text x="{x + 20}" y="{y + 48}" font-family="{FONT_FAMILY}" font-size="10" fill="{PALETTE["muted"]}">{_esc(subtitle)}</text>'
    )


def _empty_panel_text(x: int, y: int, text: str) -> str:
    return f'<text x="{x + 20}" y="{y + 92}" font-family="{FONT_FAMILY}" font-size="11" fill="{PALETTE["muted"]}">{_esc(text)}</text>'


def _first_number(value: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _num(value.get(key))
        if number is not None:
            return number
    return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}"


def _window_sort_key(name: str) -> int:
    text = str(name)
    if text.startswith("recent_") and text.endswith("d"):
        number = text[len("recent_") : -1]
        if number.isdigit():
            return int(number)
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 10**9


def _dedupe_products(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("asin") or row.get("title") or len(result))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _load_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_text(path: str | Path, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
