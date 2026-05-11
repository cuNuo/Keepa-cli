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


FIGURE_SCHEMA_VERSION = "2026-05-11.2"


PALETTE = {
    "ink": "#1f2933",
    "muted": "#667085",
    "grid": "#d9dee7",
    "panel": "#ffffff",
    "teal": "#0f9f8f",
    "blue": "#4f7cff",
    "yellow": "#c98a04",
    "red": "#c2413a",
    "green": "#1f9d55",
    "purple": "#7c5cc4",
}


def build_research_figures(*, input_path: str, out_dir: str, title: str) -> dict[str, Any]:
    payload = _load_json_file(input_path)
    return build_research_figures_from_payload(payload, out_dir=out_dir, title=title, source_label=input_path)


def build_research_figures_from_payload(
    payload: Any,
    *,
    out_dir: str,
    title: str,
    source_label: str,
) -> dict[str, Any]:
    figure_data = _figure_data(payload)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source_path = out / "agent-research-summary.source.json"
    _write_text(source_path, json.dumps({"schema_version": FIGURE_SCHEMA_VERSION, **figure_data}, ensure_ascii=False, indent=2) + "\n")

    figure_items: list[dict[str, Any]] = []
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
    for spec in _single_figure_specs(figure_data, title=title):
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


def _figure_data(payload: Any) -> dict[str, Any]:
    products = _product_rows_for_figures(payload)
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
        "history_series": _history_series_for_figures(payload),
        "window_heatmap": _window_heatmap_for_figures(payload),
        "small_multiples": _small_multiples_for_figures(products),
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
    preferred = ("new", "buy_box_shipping", "sales_rank", "review_count")

    def visit(item: Any, path: str, asin: str | None) -> None:
        if isinstance(item, Mapping):
            identity = item.get("identity") if isinstance(item.get("identity"), Mapping) else {}
            current_asin = str(item.get("asin") or identity.get("asin") or asin or "")
            history = item.get("history_summary") if isinstance(item.get("history_summary"), Mapping) else {}
            if not history and isinstance(item.get("csv"), list):
                history = _history_summary(item, 120)
            history_series = history.get("series") if isinstance(history.get("series"), Mapping) else {}
            for name in preferred:
                entry = history_series.get(name) if isinstance(history_series.get(name), Mapping) else {}
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
                            "data_basis": "history_summary.last_points",
                            "points": points[-60:],
                        }
                    )
            for key, child in item.items():
                visit(child, f"{path}.{key}", current_asin)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]", asin)

    visit(value, "$", None)
    return _dedupe_history_series(series)[:12]


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


def _small_multiples_for_figures(products: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
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
    height = 1120
    panels = [
        _panel_product_comparison(data.get("products") or [], x=44, y=92, w=372, h=300),
        _panel_history_lines(data.get("history_series") or [], x=454, y=92, w=782, h=300),
        _panel_window_heatmap(data.get("window_heatmap") or [], x=44, y=430, w=590, h=300),
        _panel_small_multiples(data.get("small_multiples") or [], x=680, y=430, w=556, h=300),
        _panel_risk_graph_summary(
            data.get("risk_codes") or [],
            data.get("entity_counts") or [],
            data.get("temporal_signals") or [],
            x=44,
            y=768,
            w=1192,
            h=260,
        ),
    ]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
  <rect width="{width}" height="{height}" fill="#f7f8fb"/>
  <text x="44" y="46" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="700" fill="{PALETTE['ink']}">{_esc(title)}</text>
  <text x="44" y="70" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="{PALETTE['muted']}">Agent-ready SVG generated from local Keepa evidence; history, windows, comparison metrics, risk, and graph entities stay linked to source JSON.</text>
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
                _panel_history_lines(data.get("history_series") or [], x=56, y=92, w=840, h=430),
                title=f"{title}: bounded history lines",
                subtitle="Recent Keepa samples retained for Agent-safe inspection.",
                caption="Each line is scaled to its own observed range; labels show start-to-end change for the retained window.",
                width=960,
                height=620,
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
            "x_axis": "Normalized metric",
            "y_axis": "Normalized score",
            "caption": "Multi-ASIN normalized comparison; rank is inverted so higher means better.",
            "svg": _single_svg(
                _panel_small_multiples(data.get("small_multiples") or [], x=56, y=92, w=820, h=430),
                title=f"{title}: multi-ASIN small multiples",
                subtitle="Comparable current metrics normalized within this result set.",
                caption="Scores are relative to the visible ASIN set; use them as transparent inputs, not a black-box recommendation.",
                width=940,
                height=620,
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
  <text x="56" y="42" font-family="Arial, Helvetica, sans-serif" font-size="21" font-weight="700" fill="{PALETTE['ink']}">{_esc(title)}</text>
  <text x="56" y="66" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="{PALETTE['muted']}">{_esc(subtitle)}</text>
  {panel}
  <text x="56" y="{height - 38}" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="{PALETTE['muted']}">{_esc(caption)}</text>
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
    rows.extend(_axis_ticks(x=plot_x, y=plot_y + len(visible) * 34 + 8, w=plot_w, max_value=max_value, label=metric.replace("_", " ")))
    for index, product in enumerate(visible):
        row_y = plot_y + index * 34
        value = _num(product.get(metric)) or 0
        bar_w = int(plot_w * value / max_value)
        label = product.get("asin") or product.get("title")
        rows.append(
            f'<text x="{x + 20}" y="{row_y + 14}" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="{PALETTE["ink"]}">{_esc(label)}</text>'
            f'<rect x="{plot_x}" y="{row_y}" width="{max(bar_w, 2)}" height="18" rx="3" fill="{PALETTE["blue"]}"/>'
            f'<text x="{plot_x + 8 + bar_w}" y="{row_y + 14}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
        )
    if not rows:
        rows.append(_empty_panel_text(x, y, "No product metric rows found"))
    return (
        _panel_frame(x, y, w, h, "A  Product comparison", f"Primary metric: {metric.replace('_', ' ')}")
        + "".join(rows)
        + _axis_label(plot_x + plot_w / 2, y + h - 18, metric.replace("_", " "), anchor="middle")
        + "</g>"
    )


def _panel_history_lines(series: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    selected = _select_history_series(series)
    plot_x = x + 72
    plot_y = y + 82
    plot_w = w - 128
    plot_h = h - 148
    elements: list[str] = []
    colors = [PALETTE["teal"], PALETTE["blue"], PALETTE["yellow"], PALETTE["purple"]]
    for index, item in enumerate(selected):
        points = item.get("points") if isinstance(item.get("points"), list) else []
        numeric = [_num(point.get("value")) for point in points if isinstance(point, Mapping)]
        values = [value for value in numeric if value is not None]
        if len(values) < 2:
            continue
        low = min(values)
        high = max(values)
        span = high - low or 1
        if index == 0:
            elements.extend(_xy_axes(plot_x, plot_y, plot_w, plot_h, x_label="recent point index", y_label=str(item.get("name") or "value"), min_value=low, max_value=high, x_ticks=len(values)))
        coords = []
        count = len(values)
        for point_index, value in enumerate(values):
            px = plot_x + (plot_w * point_index / max(count - 1, 1))
            py = plot_y + plot_h - ((value - low) / span * plot_h)
            coords.append(f"{px:.1f},{py:.1f}")
        color = colors[index % len(colors)]
        label = f'{item.get("asin") or "product"} {item.get("name")}'
        elements.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
        elements.append(f'<circle cx="{coords[-1].split(",")[0]}" cy="{coords[-1].split(",")[1]}" r="3.2" fill="{color}"/>')
        elements.append(
            f'<text x="{plot_x + index * 176}" y="{y + h - 40}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{color}">{_esc(str(label)[:28])}</text>'
        )
        elements.append(
            f'<text x="{plot_x + index * 176}" y="{y + h - 27}" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["muted"]}">{_fmt(values[0])} -> {_fmt(values[-1])}</text>'
        )
    if not elements:
        elements.append(_empty_panel_text(x, y, "No history_summary.last_points with numeric values found"))
    return _panel_frame(x, y, w, h, "B  Price / rank history", "Real recent Keepa points when full Agent history is present") + "".join(elements) + "</g>"


def _select_history_series(series: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    priority = {"new": 0, "buy_box_shipping": 1, "sales_rank": 2, "review_count": 3}
    return sorted(
        [item for item in series if isinstance(item, Mapping)],
        key=lambda item: (str(item.get("asin") or ""), priority.get(str(item.get("name") or ""), 99)),
    )[:4]


def _panel_window_heatmap(cells: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    wanted_series = ["new", "buy_box_shipping", "sales_rank", "review_count", "rating", "new_offer_count"]
    windows = sorted({str(cell.get("window") or "") for cell in cells if cell.get("window")}, key=_window_sort_key)
    series = [name for name in wanted_series if any(cell.get("series") == name for cell in cells)]
    if not series:
        series = sorted({str(cell.get("series") or "") for cell in cells if cell.get("series")})[:6]
    windows = windows[:6]
    series = series[:6]
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
            f'<text x="{start_x + col * cell_w + cell_w / 2:.1f}" y="{start_y - 12}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["muted"]}">{_esc(window.replace("recent_", ""))}</text>'
        )
    for row, name in enumerate(series):
        y0 = start_y + row * cell_h
        elements.append(f'<text x="{x + 20}" y="{y0 + 18}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["ink"]}">{_esc(name[:18])}</text>')
        for col, window in enumerate(windows):
            cell = lookup.get((window, name))
            change = _num(cell.get("change_pct")) if isinstance(cell, Mapping) else None
            color = _heat_color(change)
            label = "" if change is None else _fmt(change)
            x0 = start_x + col * cell_w
            elements.append(f'<rect x="{x0}" y="{y0}" width="{cell_w - 4}" height="{cell_h - 4}" rx="4" fill="{color}" stroke="#ffffff" stroke-width="1"/>')
            if label:
                elements.append(
                    f'<text x="{x0 + (cell_w - 4) / 2:.1f}" y="{y0 + 17}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["ink"]}">{_esc(label)}%</text>'
                )
    legend_x = start_x
    legend_y = y + h - 44
    legend = [(-30, "lower"), (0, "flat"), (30, "higher")]
    for index, (value, label) in enumerate(legend):
        lx = legend_x + index * 82
        elements.append(f'<rect x="{lx}" y="{legend_y}" width="24" height="12" rx="3" fill="{_heat_color(value)}" stroke="#ffffff" stroke-width="1"/>')
        elements.append(f'<text x="{lx + 30}" y="{legend_y + 10}" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["muted"]}">{label}</text>')
    if not elements:
        elements.append(_empty_panel_text(x, y, "No temporal windows found; run with --agent-view --view research"))
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
            f'<text x="{tx:.1f}" y="{y + 18:.1f}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["muted"]}">{_esc(_fmt(value))}</text>'
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
            f'<text x="{x - 8:.1f}" y="{ty + 3:.1f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["muted"]}">{_esc(_fmt(value))}</text>'
        )
    for index in range(min(5, max(x_ticks, 1))):
        denom = max(min(5, max(x_ticks, 1)) - 1, 1)
        value = round((x_ticks - 1) * index / denom)
        tx = x + w * index / denom
        elements.append(f'<line x1="{tx:.1f}" y1="{y + h:.1f}" x2="{tx:.1f}" y2="{y + h + 4:.1f}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(
            f'<text x="{tx:.1f}" y="{y + h + 18:.1f}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["muted"]}">{value}</text>'
        )
    elements.append(_axis_label(x + w / 2, y + h + 38, x_label, anchor="middle"))
    elements.append(_rotated_axis_label(x - 52, y + h / 2, y_label))
    return elements


def _axis_label(x: float, y: float, text: str, *, anchor: str = "start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["muted"]}">{_esc(text)}</text>'


def _rotated_axis_label(x: float, y: float, text: str) -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" transform="rotate(-90 {x:.1f} {y:.1f})" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["muted"]}">{_esc(text)}</text>'


def _panel_small_multiples(rows: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
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
        elements.append(f'<text x="{left + 10}" y="{top + 16}" font-family="Arial, Helvetica, sans-serif" font-size="9" font-weight="700" fill="{PALETTE["ink"]}">{_esc(str(row.get("label") or "")[:24])}</text>')
        elements.append(f'<line x1="{left + 16}" y1="{top + 62}" x2="{left + card_w - 16}" y2="{top + 62}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(f'<line x1="{left + 16}" y1="{top + 28}" x2="{left + 16}" y2="{top + 62}" stroke="{PALETTE["grid"]}" stroke-width="1"/>')
        elements.append(f'<text x="{left + 10}" y="{top + 31}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="7" fill="{PALETTE["muted"]}">1</text>')
        elements.append(f'<text x="{left + 10}" y="{top + 64}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="7" fill="{PALETTE["muted"]}">0</text>')
        for point_index, point in enumerate(points[:4]):
            score = _num(point.get("normalized_score")) or 0
            px = left + 18 + point_index * ((card_w - 36) / max(min(len(points), 4) - 1, 1))
            py = top + 62 - score * 34
            coords.append(f"{px:.1f},{py:.1f}")
            point_elements.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="{PALETTE["blue"]}"/>')
            point_elements.append(
                f'<text x="{px:.1f}" y="{top + 78}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="7" fill="{PALETTE["muted"]}">{_esc(point.get("label"))}</text>'
            )
        if len(coords) >= 2:
            elements.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{PALETTE["blue"]}" stroke-width="1.8"/>')
        elements.extend(point_elements)
    if not elements:
        elements.append(_empty_panel_text(x, y, "No comparable product metrics found"))
    return _panel_frame(x, y, w, h, "D  Multi-ASIN small multiples", "Normalized current metrics; rank is inverted so higher is better") + "".join(elements) + "</g>"


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
            f'<text x="{x}" y="{row_y + 13}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["ink"]}">{_esc(code[:22])}</text>'
            f'<rect x="{x + 160}" y="{row_y}" width="{max(bar_w, 2)}" height="15" rx="3" fill="{color}"/>'
            f'<text x="{x + 166 + bar_w}" y="{row_y + 12}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["muted"]}">{value}</text>'
        )
    if not rows:
        rows.append(f'<text x="{x}" y="{y + 18}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">No risk codes</text>')
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
            f'<text x="{left + bar_w / 2:.1f}" y="{top - 6}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">{value}</text>'
            f'<text x="{left + bar_w / 2:.1f}" y="{y + h - 6}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="8" fill="{PALETTE["ink"]}">{_esc(kind[:9])}</text>'
        )
    if not bars:
        bars.append(f'<text x="{x}" y="{y + 18}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">No graph entities</text>')
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
            f'<text x="{x}" y="{row_y + 12}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["ink"]}">{_esc(name[:28])}</text>'
            f'<line x1="{mid}" y1="{row_y - 3}" x2="{mid}" y2="{row_y + 17}" stroke="{PALETTE["grid"]}" stroke-width="1"/>'
            f'<rect x="{bx}" y="{row_y}" width="{max(bar_w, 2)}" height="14" rx="3" fill="{color}"/>'
            f'<text x="{mid + (bar_w + 8 if value >= 0 else -bar_w - 8)}" y="{row_y + 11}" text-anchor="{"start" if value >= 0 else "end"}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
        )
    if not rows:
        rows.append(f'<text x="{x}" y="{y + 18}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">No fallback signals</text>')
    return "".join(rows)


def _panel_frame(x: int, y: int, w: int, h: int, title: str, subtitle: str) -> str:
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PALETTE["panel"]}" stroke="{PALETTE["grid"]}" stroke-width="1"/>'
        f'<text x="{x + 20}" y="{y + 28}" font-family="Arial, Helvetica, sans-serif" font-size="14" font-weight="700" fill="{PALETTE["ink"]}">{_esc(title)}</text>'
        f'<text x="{x + 20}" y="{y + 48}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">{_esc(subtitle)}</text>'
    )


def _empty_panel_text(x: int, y: int, text: str) -> str:
    return f'<text x="{x + 20}" y="{y + 92}" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="{PALETTE["muted"]}">{_esc(text)}</text>'


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
