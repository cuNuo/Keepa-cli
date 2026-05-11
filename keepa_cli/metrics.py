"""
keepa_cli/metrics.py
文件说明：提供选品业务指标公式与可审计估算输出。
主要职责：从 Keepa 原始产品、Agent view 或 compare row 中派生 velocity、seller、inventory 与 cashflow 指标。
依赖边界：纯本地计算，不访问 Keepa API，不读取文件系统。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


METRICS_SCHEMA_VERSION = "2026-05-11.1"
FORMULA_VERSION = "2026-05-11.metrics.v1"


def build_business_metrics(
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    alias: str,
    target_days: int = 30,
    fast_mover_threshold: int = 500,
    max_results: int | None = None,
) -> dict[str, Any]:
    products = _extract_products(payload)
    rows = [
        _product_metrics(
            item["product"],
            source_path=item["path"],
            target_days=target_days,
            fast_mover_threshold=fast_mover_threshold,
        )
        for item in products
    ]
    ranked = sorted(
        rows,
        key=lambda row: (
            _score(row, "velocity", "velocity_score") or 0,
            -(_score(row, "seller_metrics", "estimated_seller_count") or 9999),
        ),
        reverse=True,
    )
    limited = ranked[:max_results] if max_results else ranked
    return {
        "view": "business_metrics",
        "schema_version": METRICS_SCHEMA_VERSION,
        "alias": alias,
        "formula_version": FORMULA_VERSION,
        "formula_policy": {
            "required_fields": ["method", "version", "inputs", "confidence", "evidence_path"],
            "principle": "所有估算只表达基于 Keepa 字段的本地 proxy，不把缺失字段推断为确定事实。",
        },
        "product_count": len(rows),
        "products": limited,
        "summary": _summary(rows, fast_mover_threshold=fast_mover_threshold),
        "brief": _brief(alias, rows, fast_mover_threshold=fast_mover_threshold),
        "data_quality": _data_quality(rows),
    }


def _product_metrics(product: Mapping[str, Any], *, source_path: str, target_days: int, fast_mover_threshold: int) -> dict[str, Any]:
    identity = _identity(product)
    seller_metrics = seller_competition_metrics(product, source_path=source_path)
    velocity = velocity_metrics(product, source_path=source_path)
    inventory = inventory_metrics(product, seller_metrics=seller_metrics, velocity=velocity, source_path=source_path, target_days=target_days)
    cashflow = cashflow_metrics(product, velocity=velocity, source_path=source_path)
    return {
        **identity,
        "source_path": source_path,
        "metrics": {
            "seller_metrics": seller_metrics,
            "velocity": velocity,
            "inventory": inventory,
            "cashflow": cashflow,
        },
        "decision_signals": {
            "fast_mover": bool((velocity.get("velocity_score") or 0) >= fast_mover_threshold),
            "competition_level": seller_metrics.get("competition_level"),
            "inventory_risk_level": inventory.get("risk_level"),
            "cashflow_pressure": cashflow.get("cashflow_pressure"),
        },
        "evidence_index": {
            "velocity": {"path": velocity["evidence_path"], "section": "metrics.velocity", "why": "销量速度与 sales rank drop proxy。"},
            "seller_metrics": {"path": seller_metrics["evidence_path"], "section": "metrics.seller_metrics", "why": "seller count 与 Buy Box 竞争。"},
            "inventory": {"path": inventory["evidence_path"], "section": "metrics.inventory", "why": "缺货风险与补货优先级 proxy。"},
            "cashflow": {"path": cashflow["evidence_path"], "section": "metrics.cashflow", "why": "现金流压力与月销售额 proxy。"},
        },
    }


def seller_competition_metrics(product: Mapping[str, Any], *, source_path: str = "$") -> dict[str, Any]:
    total_offer = _first_number(product, ("offers.total_offer_count", "stats.totalOfferCount", "total_offer_count"))
    fba = _first_number(product, ("offers.offer_count_fba", "stats.offerCountFBA", "offer_count_fba"))
    fbm = _first_number(product, ("offers.offer_count_fbm", "stats.offerCountFBM", "offer_count_fbm"))
    buy_box_seller = _first_value(product, ("pricing.buy_box.seller_id", "stats.buyBoxSellerId", "buy_box_seller_id"))
    seller_ids = _seller_ids(product)
    seller_count = total_offer.value
    method = "offer_count_stats_v1"
    reasons: list[str] = []
    if seller_count is None and fba.value is not None and fbm.value is not None:
        seller_count = fba.value + fbm.value
        method = "fba_fbm_offer_sum_v1"
        reasons.append("total offer count missing; summed FBA and FBM offer counts")
    if seller_count is None and seller_ids:
        seller_count = len(seller_ids)
        method = "seller_id_lower_bound_v1"
        reasons.append("only seller id samples are available; count is a lower bound")
    if seller_count is None:
        reasons.append("seller count fields missing")
    confidence = _confidence("high" if total_offer.value is not None else "medium" if seller_count is not None else "low", reasons)
    return _estimate(
        method=method,
        inputs={
            "total_offer_count": total_offer.value,
            "offer_count_fba": fba.value,
            "offer_count_fbm": fbm.value,
            "buy_box_seller_id": buy_box_seller.value,
            "seller_id_sample_count": len(seller_ids),
        },
        confidence=confidence,
        evidence_path=_join_path(source_path, total_offer.path or fba.path or fbm.path or buy_box_seller.path) or f"{source_path}.stats",
        values={
            "estimated_seller_count": int(seller_count) if seller_count is not None else None,
            "competition_level": _competition_level(seller_count),
            "fba_share": _share(fba.value, seller_count),
            "fbm_share": _share(fbm.value, seller_count),
            "buy_box_seller_id": buy_box_seller.value,
            "unique_seller_count_lower_bound": len(seller_ids) or None,
        },
    )


def velocity_metrics(product: Mapping[str, Any], *, source_path: str = "$") -> dict[str, Any]:
    monthly = _first_number(product, ("demand.monthly_sold", "monthlySold", "monthly_sold"))
    drops30 = _first_number(product, ("demand.sales_rank_drops.30", "stats.salesRankDrops30", "sales_rank_drops_30"))
    drops90 = _first_number(product, ("demand.sales_rank_drops.90", "stats.salesRankDrops90", "sales_rank_drops_90"))
    sales_rank = _first_number(product, ("category.sales_rank_current.value", "sales_rank"))
    if monthly.value is not None:
        velocity_score = monthly.value
        unit = "monthly_units"
        method = "monthly_sold_direct_v1"
        confidence = _confidence("high", [])
    elif drops30.value is not None:
        velocity_score = drops30.value
        unit = "sales_rank_drop_events_30"
        method = "sales_rank_drop_proxy_v1"
        confidence = _confidence("low", ["monthlySold missing; velocity score uses rank drop event proxy, not unit sales"])
    else:
        velocity_score = None
        unit = "unknown"
        method = "velocity_missing_v1"
        confidence = _confidence("low", ["monthlySold and sales rank drop fields missing"])
    return _estimate(
        method=method,
        inputs={
            "monthly_sold": monthly.value,
            "sales_rank_drops_30": drops30.value,
            "sales_rank_drops_90": drops90.value,
            "sales_rank": sales_rank.value,
        },
        confidence=confidence,
        evidence_path=_join_path(source_path, monthly.path or drops30.path or drops90.path or sales_rank.path) or f"{source_path}.demand",
        values={
            "velocity_score": velocity_score,
            "score_unit": unit,
            "monthly_units": monthly.value,
            "daily_units": round(monthly.value / 30, 2) if monthly.value is not None else None,
            "velocity_level": _velocity_level(monthly.value, drops30.value),
        },
    )


def inventory_metrics(
    product: Mapping[str, Any],
    *,
    seller_metrics: Mapping[str, Any],
    velocity: Mapping[str, Any],
    source_path: str = "$",
    target_days: int = 30,
) -> dict[str, Any]:
    oos30 = _out_of_stock_percent(product, "30")
    seller_count = _as_number(seller_metrics.get("estimated_seller_count"))
    monthly_units = _as_number(velocity.get("monthly_units"))
    risk_points = 0
    reasons: list[str] = []
    if oos30.value is not None:
        if oos30.value >= 25:
            risk_points += 3
            reasons.append("30-day out-of-stock percentage is high")
        elif oos30.value >= 10:
            risk_points += 2
            reasons.append("30-day out-of-stock percentage is elevated")
    else:
        risk_points += 1
        reasons.append("out-of-stock percentage missing")
    if monthly_units is not None and seller_count is not None and monthly_units >= 500 and seller_count <= 3:
        risk_points += 2
        reasons.append("high velocity with few active sellers")
    elif monthly_units is None:
        reasons.append("monthlySold missing")
    if seller_count is None:
        reasons.append("seller count missing")
    risk_level = "high" if risk_points >= 4 else "medium" if risk_points >= 2 else "low"
    confidence_level = "medium" if oos30.value is not None and (monthly_units is not None or seller_count is not None) else "low"
    return _estimate(
        method="stockout_risk_from_oos_offer_velocity_v1",
        inputs={
            "target_days": target_days,
            "out_of_stock_percentage_30": oos30.value,
            "monthly_units": monthly_units,
            "estimated_seller_count": seller_count,
        },
        confidence=_confidence(confidence_level, reasons),
        evidence_path=_join_path(source_path, oos30.path) or seller_metrics["evidence_path"] or velocity["evidence_path"] or f"{source_path}.offers",
        values={
            "risk_level": risk_level,
            "risk_points": risk_points,
            "target_days": target_days,
            "target_period_units": round(monthly_units / 30 * target_days, 2) if monthly_units is not None else None,
            "replenishment_priority": "urgent" if risk_level == "high" else "watch" if risk_level == "medium" else "normal",
        },
    )


def cashflow_metrics(product: Mapping[str, Any], *, velocity: Mapping[str, Any], source_path: str = "$") -> dict[str, Any]:
    price = _price(product)
    monthly_units = _as_number(velocity.get("monthly_units"))
    monthly_revenue = round(price.value * monthly_units, 2) if price.value is not None and monthly_units is not None else None
    reasons: list[str] = []
    if price.value is None:
        reasons.append("current price missing")
    if monthly_units is None:
        reasons.append("monthlySold missing")
    return _estimate(
        method="gross_sales_proxy_from_price_velocity_v1",
        inputs={
            "price": price.value,
            "monthly_units": monthly_units,
            "excludes": ["COGS", "FBA fees", "ads", "refunds", "tax", "lead time"],
        },
        confidence=_confidence("medium" if monthly_revenue is not None else "low", reasons),
        evidence_path=_join_path(source_path, price.path) or velocity["evidence_path"] or f"{source_path}.pricing",
        values={
            "monthly_gross_revenue_proxy": monthly_revenue,
            "daily_gross_revenue_proxy": round(monthly_revenue / 30, 2) if monthly_revenue is not None else None,
            "cashflow_pressure": _cashflow_pressure(monthly_revenue, monthly_units),
        },
    )


def _extract_products(payload: Mapping[str, Any] | Sequence[Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    _collect_products(payload, "$", found)
    return found


def _collect_products(value: Any, path: str, found: list[dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        data = value.get("data")
        if isinstance(data, (Mapping, list, tuple)):
            _collect_products(data, f"{path}.data", found)
            if found:
                return
        for key in ("products", "rows"):
            items = value.get(key)
            if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
                for index, item in enumerate(items):
                    if isinstance(item, Mapping):
                        found.append({"path": f"{path}.{key}[{index}]", "product": item})
                if found:
                    return
        if _looks_like_product(value):
            found.append({"path": path, "product": value})
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _collect_products(item, f"{path}[{index}]", found)


def _looks_like_product(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in ("asin", "identity", "monthlySold", "demand", "pricing", "stats", "monthly_sold"))


def _identity(product: Mapping[str, Any]) -> dict[str, Any]:
    identity = product.get("identity") if isinstance(product.get("identity"), Mapping) else {}
    return {
        "asin": identity.get("asin") or product.get("asin"),
        "title": identity.get("title") or product.get("title"),
        "brand": identity.get("brand") or product.get("brand"),
    }


class _LocatedValue:
    def __init__(self, value: Any, path: str | None) -> None:
        self.value = value
        self.path = path


def _first_value(product: Mapping[str, Any], paths: Sequence[str]) -> _LocatedValue:
    for path in paths:
        found = _get_path(product, path)
        if found.path and found.value not in (None, "", -1, -2):
            return found
    return _LocatedValue(None, None)


def _first_number(product: Mapping[str, Any], paths: Sequence[str]) -> _LocatedValue:
    found = _first_value(product, paths)
    return _LocatedValue(_as_number(found.value), found.path)


def _get_path(value: Mapping[str, Any], dotted: str) -> _LocatedValue:
    current: Any = value
    for part in dotted.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return _LocatedValue(None, None)
    return _LocatedValue(current, dotted)


def _join_path(source_path: str, relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    if relative_path.startswith("$"):
        return relative_path
    return f"{source_path}.{relative_path}"


def _as_number(value: Any) -> float | None:
    if value in (None, "", -1, -2):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _price(product: Mapping[str, Any]) -> _LocatedValue:
    direct = _first_number(product, ("pricing.buy_box.price.amount", "pricing.current.new.amount", "buy_box_price", "new_price"))
    if direct.value is not None:
        return direct
    raw = _first_number(product, ("stats.buyBoxPrice",))
    if raw.value is not None:
        return _LocatedValue(round(raw.value / 100, 2), raw.path)
    return _LocatedValue(None, None)


def _seller_ids(product: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    stats = product.get("stats") if isinstance(product.get("stats"), Mapping) else {}
    for key in ("sellerIdsLowestFBA", "sellerIdsLowestFBM"):
        values = stats.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            ids.update(str(item) for item in values if item)
    buy_box = _first_value(product, ("pricing.buy_box.seller_id", "stats.buyBoxSellerId", "buy_box_seller_id"))
    if buy_box.value:
        ids.add(str(buy_box.value))
    return ids


def _out_of_stock_percent(product: Mapping[str, Any], window: str) -> _LocatedValue:
    view_path = f"offers.out_of_stock_percentage.{window}.new"
    view_value = _first_number(product, (view_path,))
    if view_value.value is not None:
        return view_value
    stats = product.get("stats") if isinstance(product.get("stats"), Mapping) else {}
    raw = stats.get(f"outOfStockPercentage{window}")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) and len(raw) > 1:
        return _LocatedValue(_as_number(raw[1]), f"stats.outOfStockPercentage{window}[1]")
    return _LocatedValue(None, None)


def _estimate(*, method: str, inputs: Mapping[str, Any], confidence: Mapping[str, Any], evidence_path: str, values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "method": method,
        "version": FORMULA_VERSION,
        "inputs": dict(inputs),
        "confidence": dict(confidence),
        "evidence_path": evidence_path,
        **{key: value for key, value in values.items() if value is not None},
    }


def _confidence(level: str, reasons: Sequence[str]) -> dict[str, Any]:
    scores = {"high": 0.9, "medium": 0.65, "low": 0.35}
    return {"level": level, "score": scores.get(level, 0.35), "reasons": list(reasons)}


def _competition_level(seller_count: float | None) -> str:
    if seller_count is None:
        return "unknown"
    if seller_count <= 5:
        return "low"
    if seller_count <= 20:
        return "medium"
    return "high"


def _velocity_level(monthly_units: float | None, drops30: float | None) -> str:
    if monthly_units is not None:
        if monthly_units >= 1000:
            return "fast"
        if monthly_units >= 100:
            return "active"
        return "slow"
    if drops30 is not None:
        return "proxy-active" if drops30 >= 10 else "proxy-slow"
    return "unknown"


def _cashflow_pressure(monthly_revenue: float | None, monthly_units: float | None) -> str:
    if monthly_revenue is None and monthly_units is None:
        return "unknown"
    if (monthly_revenue or 0) >= 50_000 or (monthly_units or 0) >= 3_000:
        return "high"
    if (monthly_revenue or 0) >= 10_000 or (monthly_units or 0) >= 500:
        return "medium"
    return "low"


def _share(part: float | None, total: float | None) -> float | None:
    if part is None or not total:
        return None
    return round(part / total, 4)


def _score(row: Mapping[str, Any], metric: str, key: str) -> float | None:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
    item = metrics.get(metric) if isinstance(metrics.get(metric), Mapping) else {}
    return _as_number(item.get(key))


def _summary(rows: Sequence[Mapping[str, Any]], *, fast_mover_threshold: int) -> dict[str, Any]:
    inventory_counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    competition_counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    fast_movers = 0
    for row in rows:
        if (_score(row, "velocity", "velocity_score") or 0) >= fast_mover_threshold:
            fast_movers += 1
        metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
        inventory = metrics.get("inventory") if isinstance(metrics.get("inventory"), Mapping) else {}
        seller = metrics.get("seller_metrics") if isinstance(metrics.get("seller_metrics"), Mapping) else {}
        inventory_counts[str(inventory.get("risk_level") or "unknown")] = inventory_counts.get(str(inventory.get("risk_level") or "unknown"), 0) + 1
        competition_counts[str(seller.get("competition_level") or "unknown")] = competition_counts.get(str(seller.get("competition_level") or "unknown"), 0) + 1
    return {
        "fast_mover_threshold": fast_mover_threshold,
        "fast_mover_count": fast_movers,
        "inventory_risk_counts": inventory_counts,
        "competition_counts": competition_counts,
    }


def _brief(alias: str, rows: Sequence[Mapping[str, Any]], *, fast_mover_threshold: int) -> dict[str, Any]:
    summary = _summary(rows, fast_mover_threshold=fast_mover_threshold)
    high_inventory = summary["inventory_risk_counts"].get("high", 0)
    decision = "no_products"
    if rows:
        if alias in {"business.find-fast-movers", "velocity.research"}:
            decision = "prioritize_fast_movers" if summary["fast_mover_count"] else "collect_more_velocity_evidence"
        elif alias in {"business.inventory-audit", "inventory.audit"}:
            decision = "resolve_inventory_risk" if high_inventory else "inventory_risk_not_primary"
        else:
            decision = "shortlist_balanced_opportunities" if summary["fast_mover_count"] and not high_inventory else "review_risk_before_shortlist"
    return {
        "decision": decision,
        "risk": {
            "high_inventory_risk_count": high_inventory,
            "high_competition_count": summary["competition_counts"].get("high", 0),
        },
        "next_actions": [
            "先复核 confidence.level 为 low 的估算，再下结论。",
            "若 seller_count 或 out_of_stock 缺失，只补 offers/stock 相关字段，不重复拉取全量 payload。",
            "现金流 proxy 只代表 GMV，不含成本、费率、广告和账期。",
        ],
        "read_order": ["brief", "summary", "products[].decision_signals", "products[].metrics", "products[].evidence_index"],
    }


def _data_quality(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    low_confidence = 0
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else {}
        for metric in metrics.values():
            if isinstance(metric, Mapping):
                confidence = metric.get("confidence") if isinstance(metric.get("confidence"), Mapping) else {}
                if confidence.get("level") == "low":
                    low_confidence += 1
    return {
        "present": ["products", "metrics", "summary", "brief"],
        "missing": [] if rows else ["products"],
        "confidence": "medium" if rows and low_confidence else "high" if rows else "low",
        "low_confidence_metric_count": low_confidence,
    }
