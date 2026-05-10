"""
keepa_cli/commands/history.py
文件说明：history 命令族 service 路由。
主要职责：把历史导出与趋势分析转换为 Keepa product 请求和本地分析结果。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.analysis import analyze_history_rows
from keepa_cli.commands.common import as_list, client, live_cache_options
from keepa_cli.domains import resolve_domain
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.history_export import build_history_export_data, extract_history_rows, normalize_series_names


HISTORY_COMMANDS = {"history.export", "history.trend", "history.analyze"}


def can_handle(command: str) -> bool:
    return command in HISTORY_COMMANDS


def handle_history_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    if command == "history.export":
        return history_export(params, fixture_dir)
    if command in {"history.trend", "history.analyze"}:
        return history_trend(params, fixture_dir)
    raise ValueError(f"unsupported history command: {command}")


def _keepa_body_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    body = data.get("body")
    if isinstance(body, dict):
        return body
    return data


def _find_product(body: dict[str, Any], asin: str) -> dict[str, Any] | None:
    products = body.get("products")
    if not isinstance(products, list):
        return None
    for product in products:
        if isinstance(product, dict) and str(product.get("asin", "")).upper() == asin.upper():
            return product
    for product in products:
        if isinstance(product, dict):
            return product
    return None


def _history_product_payload(
    command: str,
    params: Mapping[str, Any],
    fixture_dir: Path | str | None,
) -> dict[str, Any]:
    asins = as_list(params.get("asin") or params.get("asins"))
    if len(asins) != 1:
        return error_envelope(
            command=command,
            kind="invalid_argument",
            message=f"{command} requires exactly one asin",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "asin": asins[0],
        "history": "1",
    }
    return client(fixture_dir).request(
        command=command,
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )


def _history_rows_from_payload(
    command: str,
    params: Mapping[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, dict[str, Any] | None]:
    asin = as_list(params.get("asin") or params.get("asins"))[0]
    body = _keepa_body_from_payload(payload)
    product = _find_product(body, asin)
    if product is None:
        return (
            error_envelope(
                command=command,
                kind="product_not_found",
                message=f"product not found in Keepa response: {asin}",
                token_bucket=payload.get("token_bucket") if isinstance(payload.get("token_bucket"), dict) else None,
            ),
            None,
            None,
        )

    try:
        rows = extract_history_rows(
            product,
            normalize_series_names(params.get("series")),
            include_missing=bool(params.get("include_missing")),
        )
    except ValueError as exc:
        return (
            error_envelope(
                command=command,
                kind="history_unavailable",
                message=str(exc),
                token_bucket=payload.get("token_bucket") if isinstance(payload.get("token_bucket"), dict) else None,
            ),
            None,
            None,
        )
    if not rows:
        return (
            error_envelope(
                command=command,
                kind="history_empty",
                message="selected history series contains no data points",
                token_bucket=payload.get("token_bucket") if isinstance(payload.get("token_bucket"), dict) else None,
            ),
            None,
            None,
        )
    return None, rows, product


def history_export(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    payload = _history_product_payload("history.export", params, fixture_dir)
    if not payload.get("ok") or payload.get("data", {}).get("dry_run"):
        return payload

    error, rows, product = _history_rows_from_payload("history.export", params, payload)
    if error is not None:
        return error
    assert rows is not None
    assert product is not None

    output_format = str(params.get("format") or "json").lower()
    data = build_history_export_data(
        asin=str(product.get("asin", as_list(params.get("asin"))[0])),
        domain=str(params.get("domain", "US")),
        rows=rows,
        output_format=output_format,
        output_path=params.get("out"),
    )
    return success_envelope(
        command="history.export",
        data=data,
        request=payload.get("request") if isinstance(payload.get("request"), dict) else {},
        token_bucket=payload.get("token_bucket") if isinstance(payload.get("token_bucket"), dict) else {},
    )


def history_trend(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    payload = _history_product_payload("history.trend", params, fixture_dir)
    if not payload.get("ok") or payload.get("data", {}).get("dry_run"):
        return payload

    error, rows, product = _history_rows_from_payload("history.trend", params, payload)
    if error is not None:
        return error
    assert rows is not None
    assert product is not None

    window_days = [int(item) for item in as_list(params.get("window_days"))] or [30, 90, 180]
    data = {
        "asin": str(product.get("asin", as_list(params.get("asin"))[0])),
        "domain": str(params.get("domain", "US")),
        "series": normalize_series_names(params.get("series")),
        "analysis": analyze_history_rows(rows, window_days=window_days),
    }
    return success_envelope(
        command="history.trend",
        data=data,
        request=payload.get("request") if isinstance(payload.get("request"), dict) else {},
        token_bucket=payload.get("token_bucket") if isinstance(payload.get("token_bucket"), dict) else {},
    )
