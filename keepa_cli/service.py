"""
keepa_cli/service.py
文件说明：提供 CLI、stdio 与 TUI 共用的 Agent-safe command service。
主要职责：把高层命令转换为官方 Keepa endpoint、参数、预算和 envelope。
依赖边界：不处理终端输入输出，不保存凭据，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepa_cli.analysis import analyze_history_rows
from keepa_cli.client import KeepaClient
from keepa_cli.config import build_config_report, init_config
from keepa_cli.doctor import build_doctor_report
from keepa_cli.domains import list_domains, resolve_domain
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.history_export import build_history_export_data, extract_history_rows, normalize_series_names


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _bool_param(value: Any) -> str:
    return "1" if value is True or str(value).lower() in {"1", "true", "yes", "on"} else "0"


def _optional_params(params: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        if name in params and params[name] is not None:
            result[name] = params[name]
    return result


def _client(fixture_dir: Path | str | None = None) -> KeepaClient:
    selected_fixture_dir = Path(fixture_dir) if fixture_dir is not None else DEFAULT_FIXTURE_DIR
    return KeepaClient(fixture_dir=selected_fixture_dir)


def _product_get(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    asins = _as_list(params.get("asin") or params.get("asins"))
    codes = _as_list(params.get("code") or params.get("codes"))
    if bool(asins) == bool(codes):
        return error_envelope(
            command="products.get",
            kind="invalid_argument",
            message="products.get requires exactly one of asin/asins or code/codes",
        )

    request_params: dict[str, Any] = {"domain": str(resolve_domain(params.get("domain", "US")).domain_id)}
    if asins:
        request_params["asin"] = ",".join(asins)
    else:
        request_params["code"] = ",".join(codes)

    request_params.update(
        _optional_params(
            params,
            (
                "stats",
                "update",
                "history",
                "days",
                "offers",
                "code-limit",
                "only-live-offers",
                "videos",
                "aplus",
                "rating",
                "buybox",
                "stock",
                "historical-variations",
            ),
        )
    )
    return _client(fixture_dir).request(
        command="products.get",
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )


def _product_search(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    term = str(params.get("term", "")).strip()
    if not term:
        return error_envelope(
            command="products.search",
            kind="invalid_argument",
            message="products.search requires a non-empty search term",
        )

    request_params = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "type": "product",
        "term": term,
    }
    return _client(fixture_dir).request(
        command="products.search",
        method="GET",
        path="/search",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )


def _categories_get(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    categories = _as_list(params.get("category") or params.get("categories"))
    if not categories:
        return error_envelope(
            command="categories.get",
            kind="invalid_argument",
            message="categories.get requires at least one category id",
        )
    if len(categories) > 10:
        return error_envelope(
            command="categories.get",
            kind="invalid_argument",
            message="Keepa category lookup supports at most 10 category ids per request",
        )

    request_params = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "category": ",".join(categories),
        "parents": _bool_param(params.get("parents", False)),
    }
    return _client(fixture_dir).request(
        command="categories.get",
        method="GET",
        path="/category",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )


def _categories_search(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    term = str(params.get("term", "")).strip()
    if not term:
        return error_envelope(
            command="categories.search",
            kind="invalid_argument",
            message="categories.search requires a non-empty search term",
        )

    request_params = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "type": "category",
        "term": term,
    }
    return _client(fixture_dir).request(
        command="categories.search",
        method="GET",
        path="/search",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )


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
    asins = _as_list(params.get("asin") or params.get("asins"))
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
    return _client(fixture_dir).request(
        command=command,
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )


def _history_rows_from_payload(
    command: str,
    params: Mapping[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, dict[str, Any] | None]:
    asin = _as_list(params.get("asin") or params.get("asins"))[0]
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


def _history_export(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
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
        asin=str(product.get("asin", _as_list(params.get("asin"))[0])),
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


def _history_trend(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    payload = _history_product_payload("history.trend", params, fixture_dir)
    if not payload.get("ok") or payload.get("data", {}).get("dry_run"):
        return payload

    error, rows, product = _history_rows_from_payload("history.trend", params, payload)
    if error is not None:
        return error
    assert rows is not None
    assert product is not None

    window_days = [int(item) for item in _as_list(params.get("window_days"))] or [30, 90, 180]
    data = {
        "asin": str(product.get("asin", _as_list(params.get("asin"))[0])),
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


def run_command(
    command: str,
    params: Mapping[str, Any] | None = None,
    *,
    fixture_dir: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    params = dict(params or {})
    env = os.environ if env is None else env

    try:
        if command == "doctor":
            return success_envelope(
                command="doctor",
                data=build_doctor_report(env=env),
                request={"transport": "service"},
                token_bucket={},
            )
        if command == "domains.list":
            return success_envelope(
                command="domains.list",
                data={"domains": list_domains()},
                request={"transport": "service"},
                token_bucket={},
            )
        if command == "config.show":
            return success_envelope(
                command="config.show",
                data=build_config_report(path=params.get("path"), env=env),
                request={"transport": "service"},
                token_bucket={},
            )
        if command == "config.init":
            return success_envelope(
                command="config.init",
                data=init_config(path=params.get("path"), env=env, dry_run=bool(params.get("dry_run"))),
                request={"transport": "service", "dry_run": bool(params.get("dry_run"))},
                token_bucket={},
            )
        if command == "request.get" or command == "request.post":
            method = command.rsplit(".", 1)[1].upper()
            return _client(fixture_dir).request(
                command=command,
                method=method,
                path=str(params.get("path", "")),
                params=dict(params.get("params") or {}),
                dry_run=bool(params.get("dry_run")),
                fixture=params.get("fixture"),
            )
        if command == "products.get":
            return _product_get(params, fixture_dir)
        if command == "products.search":
            return _product_search(params, fixture_dir)
        if command == "categories.get":
            return _categories_get(params, fixture_dir)
        if command == "categories.search":
            return _categories_search(params, fixture_dir)
        if command == "history.export":
            return _history_export(params, fixture_dir)
        if command in {"history.trend", "history.analyze"}:
            return _history_trend(params, fixture_dir)
    except ValueError as exc:
        return error_envelope(command=command, kind="invalid_argument", message=str(exc))

    return error_envelope(
        command=command or "service",
        kind="unsupported_command",
        message=f"unsupported command: {command}",
    )
