"""
keepa_cli/commands/products.py
文件说明：products 命令族 service 路由。
主要职责：把产品查询命令转换为 Keepa product/search 请求和 Agent 视图。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.commands.common import as_list, bool_option, client, live_cache_options, param, product_query_options
from keepa_cli.domains import resolve_domain
from keepa_cli.envelope import error_envelope
from keepa_cli.high_value import attach_output_if_requested, write_body_output
from keepa_cli.product_view import build_agent_product_view, build_product_compare_view


PRODUCT_COMMANDS = {"products.get", "products.compare", "products.search"}


def can_handle(command: str) -> bool:
    return command in PRODUCT_COMMANDS


def handle_product_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    if command == "products.get":
        return product_get(params, fixture_dir)
    if command == "products.compare":
        return products_compare(params, fixture_dir)
    if command == "products.search":
        return product_search(params, fixture_dir)
    raise ValueError(f"unsupported products command: {command}")


def product_get(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    asins = as_list(params.get("asin") or params.get("asins"))
    codes = as_list(params.get("code") or params.get("codes"))
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

    request_params.update(product_query_options(params))
    payload = client(fixture_dir).request(
        command="products.get",
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
    view = str(param(params, "view", "output_view") or "").strip().lower()
    if bool_option(params, "agent_view", "agent-view") or view == "agent":
        data = payload.get("data")
        if payload.get("ok") and isinstance(data, dict) and not data.get("dry_run"):
            output_path = param(params, "out", "output")
            raw_output = None
            if output_path:
                raw_output = write_body_output(data, output_path)
            history_limit = int(param(params, "history_limit", "history-limit") or 10)
            data = build_agent_product_view(
                data,
                history_limit=history_limit,
                temporal_windows=param(params, "temporal_windows", "temporal-window-days", "temporal_window_days"),
                view_profile=view,
                fields=param(params, "fields"),
                chunks_dir=param(params, "chunks_dir", "chunks-dir"),
            )
            if raw_output:
                raw = data.get("raw")
                if isinstance(raw, dict):
                    raw["output"] = raw_output
            payload["data"] = data
    else:
        payload = attach_output_if_requested(payload, param(params, "out", "output"))
    return payload


def products_compare(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    asins = as_list(params.get("asin") or params.get("asins"))
    if not asins:
        return error_envelope(
            command="products.compare",
            kind="invalid_argument",
            message="products.compare requires at least one ASIN",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "asin": ",".join(asins),
    }
    request_params.update(product_query_options(params))
    payload = client(fixture_dir).request(
        command="products.compare",
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
    payload = attach_output_if_requested(payload, param(params, "out", "output"))
    data = payload.get("data")
    if payload.get("ok") and isinstance(data, dict) and not data.get("dry_run"):
        history_limit = int(param(params, "history_limit", "history-limit") or 5)
        agent_view = build_agent_product_view(
            data,
            history_limit=history_limit,
            temporal_windows=param(params, "temporal_windows", "temporal-window-days", "temporal_window_days"),
            view_profile=str(param(params, "view") or "deal"),
            fields=param(params, "fields"),
            chunks_dir=param(params, "chunks_dir", "chunks-dir"),
        )
        payload["data"] = build_product_compare_view(agent_view)
    return payload


def product_search(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
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
    return client(fixture_dir).request(
        command="products.search",
        method="GET",
        path="/search",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
