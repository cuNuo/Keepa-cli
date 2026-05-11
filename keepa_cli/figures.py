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

from keepa_cli.research_graph import extract_research_graphs


FIGURE_SCHEMA_VERSION = "2026-05-11.1"


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
    figure_data = _figure_data(payload)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    svg_path = out / "agent-research-summary.svg"
    svg_text = _summary_svg(figure_data, title=title)
    _write_text(svg_path, svg_text)
    source_path = out / "agent-research-summary.source.json"
    _write_text(source_path, json.dumps({"schema_version": FIGURE_SCHEMA_VERSION, **figure_data}, ensure_ascii=False, indent=2) + "\n")
    return {
        "schema_version": FIGURE_SCHEMA_VERSION,
        "title": title,
        "format": "svg",
        "figures": [
            {
                "name": "agent-research-summary",
                "kind": "multi_panel_svg",
                "path": str(svg_path),
                "format": "svg",
                "size_bytes": svg_path.stat().st_size,
                "source_data_path": str(source_path),
                "source_data_bytes": source_path.stat().st_size,
                "panels": ["product_metric_comparison", "risk_code_summary", "research_graph_entities", "temporal_signal_summary"],
            }
        ],
        "data_summary": {
            "product_count": len(figure_data["products"]),
            "risk_code_count": len(figure_data["risk_codes"]),
            "graph_entity_types": len(figure_data["entity_counts"]),
            "temporal_signal_count": len(figure_data["temporal_signals"]),
        },
        "provenance": {
            "source": "local",
            "endpoint": "local://figures.research",
            "input": input_path,
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
    height = 900
    panels = [
        _panel_product_comparison(data.get("products") or [], x=44, y=92, w=590, h=330),
        _panel_risks(data.get("risk_codes") or [], x=680, y=92, w=556, h=330),
        _panel_entities(data.get("entity_counts") or [], x=44, y=480, w=590, h=320),
        _panel_temporal(data.get("temporal_signals") or [], x=680, y=480, w=556, h=320),
    ]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
  <rect width="{width}" height="{height}" fill="#f7f8fb"/>
  <text x="44" y="46" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="700" fill="{PALETTE['ink']}">{_esc(title)}</text>
  <text x="44" y="70" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="{PALETTE['muted']}">Agent-ready SVG generated from local Keepa evidence; panels summarize comparison, risk, graph entities, and temporal signals.</text>
  {''.join(panels)}
</svg>
"""


def _panel_product_comparison(products: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    metric = "monthly_sold" if any(_num(p.get("monthly_sold")) is not None for p in products) else "review_count"
    values = [_num(product.get(metric)) or 0 for product in products]
    max_value = max(values, default=1) or 1
    rows = []
    for index, product in enumerate(products[:6]):
        row_y = y + 72 + index * 38
        value = _num(product.get(metric)) or 0
        bar_w = int((w - 230) * value / max_value)
        label = product.get("asin") or product.get("title")
        rows.append(
            f'<text x="{x + 20}" y="{row_y + 14}" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="{PALETTE["ink"]}">{_esc(label)}</text>'
            f'<rect x="{x + 150}" y="{row_y}" width="{max(bar_w, 2)}" height="18" rx="3" fill="{PALETTE["blue"]}"/>'
            f'<text x="{x + 160 + bar_w}" y="{row_y + 14}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
        )
    if not rows:
        rows.append(_empty_panel_text(x, y, "No product metric rows found"))
    return _panel_frame(x, y, w, h, "A  Product comparison", f"Primary metric: {metric.replace('_', ' ')}") + "".join(rows) + "</g>"


def _panel_risks(risks: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    values = [(str(item.get("code") or ""), int(item.get("count") or 0)) for item in risks if item.get("code")]
    max_value = max((value for _, value in values), default=1) or 1
    rows = []
    for index, (code, value) in enumerate(values[:7]):
        row_y = y + 72 + index * 32
        color = PALETTE["yellow"] if code == "data_missing" else PALETTE["red"] if "unstable" in code or "declining" in code else PALETTE["teal"]
        bar_w = int((w - 240) * value / max_value)
        rows.append(
            f'<text x="{x + 20}" y="{row_y + 13}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["ink"]}">{_esc(code)}</text>'
            f'<rect x="{x + 210}" y="{row_y}" width="{max(bar_w, 2)}" height="16" rx="3" fill="{color}"/>'
            f'<text x="{x + 220 + bar_w}" y="{row_y + 13}" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">{value}</text>'
        )
    if not rows:
        rows.append(_empty_panel_text(x, y, "No risk taxonomy codes found"))
    return _panel_frame(x, y, w, h, "B  Risk taxonomy", "Machine-readable risk code frequency") + "".join(rows) + "</g>"


def _panel_entities(entities: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    values = [(str(item.get("type") or ""), int(item.get("count") or 0)) for item in entities if item.get("type")]
    max_value = max((value for _, value in values), default=1) or 1
    bars = []
    bar_w = max(24, int((w - 90) / max(len(values), 1)) - 10)
    for index, (kind, value) in enumerate(values[:10]):
        left = x + 42 + index * (bar_w + 10)
        bar_h = int((h - 120) * value / max_value)
        top = y + h - 55 - bar_h
        bars.append(
            f'<rect x="{left}" y="{top}" width="{bar_w}" height="{bar_h}" rx="3" fill="{PALETTE["teal"]}"/>'
            f'<text x="{left + bar_w / 2:.1f}" y="{top - 6}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="10" fill="{PALETTE["muted"]}">{value}</text>'
            f'<text x="{left + bar_w / 2:.1f}" y="{y + h - 28}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["ink"]}">{_esc(kind[:10])}</text>'
        )
    if not bars:
        bars.append(_empty_panel_text(x, y, "No research graph entities found"))
    return _panel_frame(x, y, w, h, "C  Research graph", "Entity counts across merged evidence") + "".join(bars) + "</g>"


def _panel_temporal(signals: list[Mapping[str, Any]], *, x: int, y: int, w: int, h: int) -> str:
    values = []
    for item in signals[:8]:
        value = _num(item.get("value"))
        if value is not None:
            values.append((str(item.get("name") or item.get("metric") or "signal"), value))
    max_abs = max((abs(value) for _, value in values), default=1) or 1
    rows = []
    mid = x + 260
    for index, (name, value) in enumerate(values):
        row_y = y + 70 + index * 28
        bar_w = int((w - 320) * abs(value) / max_abs)
        color = PALETTE["green"] if value >= 0 else PALETTE["red"]
        bx = mid if value >= 0 else mid - bar_w
        rows.append(
            f'<text x="{x + 20}" y="{row_y + 12}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["ink"]}">{_esc(name[:34])}</text>'
            f'<line x1="{mid}" y1="{row_y - 3}" x2="{mid}" y2="{row_y + 17}" stroke="{PALETTE["grid"]}" stroke-width="1"/>'
            f'<rect x="{bx}" y="{row_y}" width="{max(bar_w, 2)}" height="14" rx="3" fill="{color}"/>'
            f'<text x="{mid + (bar_w + 8 if value >= 0 else -bar_w - 8)}" y="{row_y + 11}" text-anchor="{"start" if value >= 0 else "end"}" font-family="Arial, Helvetica, sans-serif" font-size="9" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
        )
    if not rows:
        rows.append(_empty_panel_text(x, y, "No temporal features found in this payload"))
    return _panel_frame(x, y, w, h, "D  Temporal signals", "Windowed or trend features when available") + "".join(rows) + "</g>"


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
