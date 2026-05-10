"""
keepa_cli/service.py
文件说明：提供 CLI、stdio 与 TUI 共用的 Agent-safe command service。
主要职责：把高层命令转换为官方 Keepa endpoint、参数、预算和 envelope。
依赖边界：不处理终端输入输出，不保存凭据，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

import os
import json
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepa_cli.analysis import analyze_history_rows
from keepa_cli.capabilities import build_capabilities
from keepa_cli.cassettes import sanitize_cassette_file
from keepa_cli.client import KeepaClient
from keepa_cli.commands.workflows import can_handle as can_handle_workflow_command
from keepa_cli.commands.workflows import handle_workflow_command
from keepa_cli.config import build_config_report, init_config, set_api_token, set_language, set_max_tokens_per_request
from keepa_cli.doctor import build_doctor_report
from keepa_cli.domains import list_domains, resolve_domain
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.high_value import attach_output_if_requested, load_selection, selection_to_query_value, write_body_output
from keepa_cli.history_export import build_history_export_data, extract_history_rows, normalize_series_names
from keepa_cli.product_view import build_agent_product_view, build_product_compare_view
from keepa_cli.schema_docs import generate_product_agent_schema
from keepa_cli.token_budget import estimate_request_budget


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


def _param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


def _bool_option(params: Mapping[str, Any], *names: str) -> bool:
    value = _param(params, *names)
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def _product_query_options(params: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if _bool_option(params, "full", "full_detail", "full-detail"):
        stats_window = _param(params, "stats_window", "stats-window", default="0")
        result.update({"history": "1", "stats": str(stats_window), "videos": "1", "aplus": "1"})

    for canonical in (
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
    ):
        value = _param(params, canonical, canonical.replace("-", "_"))
        if value is not None:
            result[canonical] = value
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

    request_params.update(_product_query_options(params))
    payload = _client(fixture_dir).request(
        command="products.get",
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )
    view = str(_param(params, "view", "output_view") or "").strip().lower()
    if _bool_option(params, "agent_view", "agent-view") or view == "agent":
        data = payload.get("data")
        if payload.get("ok") and isinstance(data, dict) and not data.get("dry_run"):
            output_path = _param(params, "out", "output")
            raw_output = None
            if output_path:
                raw_output = write_body_output(data, output_path)
            history_limit = int(_param(params, "history_limit", "history-limit") or 10)
            data = build_agent_product_view(
                data,
                history_limit=history_limit,
                temporal_windows=_param(params, "temporal_windows", "temporal-window-days", "temporal_window_days"),
                view_profile=view,
                fields=_param(params, "fields"),
                chunks_dir=_param(params, "chunks_dir", "chunks-dir"),
            )
            if raw_output:
                raw = data.get("raw")
                if isinstance(raw, dict):
                    raw["output"] = raw_output
            payload["data"] = data
    else:
        payload = attach_output_if_requested(payload, _param(params, "out", "output"))
    return payload


def _products_compare(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    asins = _as_list(params.get("asin") or params.get("asins"))
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
    request_params.update(_product_query_options(params))
    payload = _client(fixture_dir).request(
        command="products.compare",
        method="GET",
        path="/product",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
    )
    payload = attach_output_if_requested(payload, _param(params, "out", "output"))
    data = payload.get("data")
    if payload.get("ok") and isinstance(data, dict) and not data.get("dry_run"):
        history_limit = int(_param(params, "history_limit", "history-limit") or 5)
        agent_view = build_agent_product_view(
            data,
            history_limit=history_limit,
            temporal_windows=_param(params, "temporal_windows", "temporal-window-days", "temporal_window_days"),
            view_profile=str(_param(params, "view") or "deal"),
            fields=_param(params, "fields"),
            chunks_dir=_param(params, "chunks_dir", "chunks-dir"),
        )
        payload["data"] = build_product_compare_view(agent_view)
    return payload


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


def _confirmation_required(command: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    budget = estimate_request_budget(command, dict(params)).to_dict()
    if not budget["requires_confirmation"]:
        return None
    if _bool_option(params, "dry_run", "dry-run") or params.get("fixture") or _bool_option(params, "yes"):
        return None
    return error_envelope(
        command=command,
        kind="confirmation_required",
        message="request requires explicit confirmation because it may consume significant Keepa tokens",
        details={
            "resume_with": "--yes",
            "estimated_tokens": budget["estimated_tokens"],
            "worst_case_tokens": budget["worst_case_tokens"],
        },
        token_bucket={"estimated": budget},
    )


def _tokens_status(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    return _client(fixture_dir).request(
        command="tokens.status",
        method="GET",
        path="/token",
        params={},
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )


def _graph_image(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    asin = str(_param(params, "asin", default="")).strip()
    if not asin:
        return error_envelope(
            command="graphs.image",
            kind="invalid_argument",
            message="graphs.image requires an ASIN",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "asin": asin,
    }
    for name in (
        "range",
        "width",
        "height",
        "amazon",
        "new",
        "used",
        "salesrank",
        "bb",
        "fba",
        "warehouse",
        "ld",
        "deal",
        "cBackground",
        "cAmazon",
        "cNew",
        "cUsed",
        "cBB",
        "cFBA",
    ):
        if _param(params, name) is not None:
            request_params[name] = _param(params, name)

    extra_params = _param(params, "extra_params", "params")
    if isinstance(extra_params, Mapping):
        request_params.update(dict(extra_params))

    if not _bool_option(params, "dry_run", "dry-run") and not params.get("fixture") and not params.get("out"):
        budget = estimate_request_budget("graphs.image", request_params).to_dict()
        return error_envelope(
            command="graphs.image",
            kind="binary_output_path_required",
            message="graph image live download returns PNG bytes and requires --out",
            details={"resume_with": "--out <path>", "offline_alternative": "use --dry-run or --fixture"},
            token_bucket={"estimated": budget},
        )

    return _client(fixture_dir).request(
        command="graphs.image",
        method="GET",
        path="/graphimage",
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
        out=params.get("out"),
        binary=not _bool_option(params, "dry_run", "dry-run") and not params.get("fixture"),
    )


def _lightningdeals_list(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
    }
    asin = str(_param(params, "asin", default="")).strip()
    if asin:
        request_params["asin"] = asin

    payload = _client(fixture_dir).request(
        command="lightningdeals.list",
        method="GET",
        path="/lightningdeal",
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    return attach_output_if_requested(payload, _param(params, "out", "output"))


def _tracking_body(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_value = _param(params, "tracking", "trackings")
    tracking_file = _param(params, "tracking_file", "tracking-file")
    if tracking_file is not None:
        path = Path(str(tracking_file))
        if not path.is_file():
            raise ValueError(f"tracking file not found: {tracking_file}")
        raw_value = json.loads(path.read_text(encoding="utf-8"))
    elif isinstance(raw_value, str):
        raw_value = json.loads(raw_value)

    if isinstance(raw_value, Mapping):
        return [dict(raw_value)]
    if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
        result: list[dict[str, Any]] = []
        for item in raw_value:
            if not isinstance(item, Mapping):
                raise ValueError("tracking list items must be JSON objects")
            result.append(dict(item))
        return result
    raise ValueError("tracking.add requires tracking JSON object/list or tracking_file")


def _redact_url_query_secrets(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = []
    for key, value in query:
        if key.lower() in {"key", "api_key", "apikey", "token", "authorization"}:
            redacted_query.append((key, "[REDACTED]"))
        else:
            redacted_query.append((key, value))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(redacted_query),
            parsed.fragment,
        )
    )


def _sanitize_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if not isinstance(request, dict):
        return payload
    params_redacted = request.get("params_redacted")
    if not isinstance(params_redacted, dict):
        return payload
    url = params_redacted.get("url")
    if isinstance(url, str):
        params_redacted["url"] = _redact_url_query_secrets(url)
    return payload


def _tracking_request(command: str, params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    action = command.split(".", 1)[1]
    request_params: dict[str, Any] = {}
    method = "GET"
    json_body: list[dict[str, Any]] | None = None

    if action in {"list", "list-names"}:
        request_params["type"] = "list"
        if _bool_option(params, "asins_only", "asins-only"):
            request_params["asins-only"] = "1"
        if action == "list-names":
            request_params["asins-only"] = "1"
    elif action == "get":
        asin = str(_param(params, "asin", default="")).strip()
        if not asin:
            return error_envelope(command=command, kind="invalid_argument", message="tracking.get requires an ASIN")
        request_params.update({"type": "get", "asin": asin})
    elif action == "add":
        method = "POST"
        request_params["type"] = "add"
        json_body = _tracking_body(params)
    elif action == "remove":
        asin = str(_param(params, "asin", default="")).strip()
        if not asin:
            return error_envelope(command=command, kind="invalid_argument", message="tracking.remove requires an ASIN")
        request_params.update({"type": "remove", "asin": asin})
    elif action == "remove-all":
        request_params["type"] = "removeAll"
    elif action == "notifications":
        request_params.update(
            {
                "type": "notification",
                "since": str(_param(params, "since", default=0)),
                "revise": _bool_param(_param(params, "revise", default=False)),
            }
        )
    elif action == "webhook":
        url = str(_param(params, "url", default="")).strip()
        if not url:
            return error_envelope(command=command, kind="invalid_argument", message="tracking.webhook requires a URL")
        request_params.update({"type": "webhook", "url": url})
    else:
        return error_envelope(command=command, kind="unsupported_command", message=f"unsupported tracking action: {action}")

    confirmation = _confirmation_required(command, {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = _client(fixture_dir).request(
        command=command,
        method=method,
        path="/tracking",
        params=request_params,
        json_body=json_body,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    if action == "webhook":
        payload = _sanitize_webhook_payload(payload)
    return attach_output_if_requested(payload, _param(params, "out", "output"))


def _selection_query(
    command: str,
    path: str,
    params: Mapping[str, Any],
    fixture_dir: Path | str | None,
) -> dict[str, Any]:
    selection = load_selection(
        _param(params, "selection"),
        _param(params, "selection_file", "selection-file"),
    )
    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "selection": selection_to_query_value(selection),
    }
    if _param(params, "max_tokens", "max-tokens") is not None:
        request_params["max_tokens"] = int(_param(params, "max_tokens", "max-tokens"))

    confirmation = _confirmation_required(command, {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = _client(fixture_dir).request(
        command=command,
        method="GET",
        path=path,
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    return attach_output_if_requested(payload, _param(params, "out", "output"))


def _seller_get(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    sellers = _as_list(params.get("seller") or params.get("sellers"))
    if not sellers:
        return error_envelope(
            command="sellers.get",
            kind="invalid_argument",
            message="sellers.get requires at least one seller id",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "seller": ",".join(sellers),
    }
    if _param(params, "storefront") is not None:
        request_params["storefront"] = _bool_param(params.get("storefront"))
    if _param(params, "update") is not None:
        request_params["update"] = params.get("update")

    payload = _client(fixture_dir).request(
        command="sellers.get",
        method="GET",
        path="/seller",
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    return attach_output_if_requested(payload, _param(params, "out", "output"))


def _bestsellers_get(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    category = str(_param(params, "category", "category_id", "category-id", default="")).strip()
    if not category:
        return error_envelope(
            command="bestsellers.get",
            kind="invalid_argument",
            message="bestsellers.get requires a category id",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "category": category,
    }
    confirmation = _confirmation_required("bestsellers.get", {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = _client(fixture_dir).request(
        command="bestsellers.get",
        method="GET",
        path="/bestsellers",
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    return attach_output_if_requested(payload, _param(params, "out", "output"))


def _categories_products(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    category = str(_param(params, "category", "category_id", "category-id", default="")).strip()
    if not category:
        return error_envelope(
            command="categories.products",
            kind="invalid_argument",
            message="categories.products requires a category id",
        )

    limit = int(_param(params, "limit", "max_asins", "max-asins", default=25) or 25)
    if limit <= 0:
        return error_envelope(
            command="categories.products",
            kind="invalid_argument",
            message="categories.products limit must be positive",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "category": category,
    }
    confirmation = _confirmation_required("categories.products", {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = _client(fixture_dir).request(
        command="categories.products",
        method="GET",
        path="/bestsellers",
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    if not payload.get("ok"):
        return payload
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    if data.get("dry_run"):
        data["view"] = "category_products"
        data["category_id"] = category
        data["source"] = "bestsellers"
        data["limit"] = limit
        data["next_actions"] = [
            {
                "command": f"categories products {category} --domain <DOMAIN> --limit {limit} --yes",
                "reason": "fetch category ASIN candidates from Keepa Best Sellers",
                "estimated_tokens": 50,
            }
        ]
        return payload

    body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
    normalized = _category_products_view(body, category=category, limit=limit, domain=str(params.get("domain", "US")))
    data.update(normalized)
    return attach_output_if_requested(payload, _param(params, "out", "output"))


def _category_products_view(body: Mapping[str, Any], *, category: str, limit: int, domain: str) -> dict[str, Any]:
    bestsellers = body.get("bestSellersList") if isinstance(body.get("bestSellersList"), Mapping) else {}
    asin_list = bestsellers.get("asinList") if isinstance(bestsellers.get("asinList"), list) else []
    asins = [str(asin) for asin in asin_list[:limit] if str(asin).strip()]
    candidates = [
        {
            "rank": index + 1,
            "asin": asin,
            "source": "bestsellers",
            "category_id": str(bestsellers.get("categoryId") or category),
        }
        for index, asin in enumerate(asins)
    ]
    compare_command = f"products compare {' '.join(asins[:10])} --domain {domain} --full --view deal" if asins else None
    get_command = f"products get {asins[0]} --domain {domain} --full --agent-view --view summary" if asins else None
    return {
        "view": "category_products",
        "source": "bestsellers",
        "category_id": str(bestsellers.get("categoryId") or category),
        "last_update": bestsellers.get("lastUpdate"),
        "candidate_count": len(candidates),
        "asins": asins,
        "candidates": candidates,
        "next_actions": [
            item
            for item in (
                {
                    "command": compare_command,
                    "reason": "compare top category candidates with deal profile",
                    "estimated_tokens": max(1, len(asins[:10])),
                }
                if compare_command
                else None,
                {
                    "command": get_command,
                    "reason": "inspect the top category candidate with Agent summary",
                    "estimated_tokens": 1,
                }
                if get_command
                else None,
            )
            if item is not None
        ],
    }


def _topsellers_list(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
    }
    category = _param(params, "category", "category_id", "category-id")
    if category is not None:
        request_params["category"] = str(category)

    confirmation = _confirmation_required("topsellers.list", {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = _client(fixture_dir).request(
        command="topsellers.list",
        method="GET",
        path="/topseller",
        params=request_params,
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
    )
    return attach_output_if_requested(payload, _param(params, "out", "output"))


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


def _schema_generate(params: Mapping[str, Any]) -> dict[str, Any]:
    metadata = generate_product_agent_schema(
        Path(str(params.get("snapshot") or "tests/snapshots/agent_schema_snapshot.json")),
        Path(str(params.get("out") or "docs/schema/products.agent-view.schema.json")),
    )
    return success_envelope(
        command="schema.generate",
        data=metadata,
        request={"transport": "service"},
        token_bucket={},
    )


def _cassettes_sanitize(params: Mapping[str, Any]) -> dict[str, Any]:
    input_path = params.get("input") or params.get("in")
    output_path = params.get("out") or params.get("output")
    if not input_path or not output_path:
        return error_envelope(
            command="cassettes.sanitize",
            kind="invalid_argument",
            message="cassettes.sanitize requires input and out paths",
        )
    metadata = sanitize_cassette_file(Path(str(input_path)), Path(str(output_path)))
    return success_envelope(
        command="cassettes.sanitize",
        data=metadata,
        request={"transport": "service"},
        token_bucket={},
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
        if command == "capabilities":
            return success_envelope(
                command="capabilities",
                data=build_capabilities(),
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
        if can_handle_workflow_command(command):
            return handle_workflow_command(command, params)
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
        if command in {"config.set-token", "config.set_token"}:
            return success_envelope(
                command="config.set-token",
                data=set_api_token(
                    str(params.get("token", "")),
                    path=params.get("path"),
                    env=env,
                    dry_run=bool(params.get("dry_run")),
                ),
                request={"transport": "service", "dry_run": bool(params.get("dry_run"))},
                token_bucket={},
            )
        if command in {"config.set-language", "config.set_language"}:
            return success_envelope(
                command="config.set-language",
                data=set_language(
                    str(params.get("language", "")),
                    path=params.get("path"),
                    env=env,
                    dry_run=bool(params.get("dry_run")),
                ),
                request={"transport": "service", "dry_run": bool(params.get("dry_run"))},
                token_bucket={},
            )
        if command in {"config.set-max-tokens", "config.set_max_tokens"}:
            return success_envelope(
                command="config.set-max-tokens",
                data=set_max_tokens_per_request(
                    params.get("max_tokens", params.get("max-tokens", "")),
                    path=params.get("path"),
                    env=env,
                    dry_run=bool(params.get("dry_run")),
                ),
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
        if command in {"tokens.status", "token.status"}:
            return _tokens_status(params, fixture_dir)
        if command in {"graphs.image", "graph.image"}:
            return _graph_image(params, fixture_dir)
        if command in {"lightningdeals.list", "lightningdeal.list"}:
            return _lightningdeals_list(params, fixture_dir)
        if command in {
            "tracking.list",
            "tracking.list-names",
            "tracking.get",
            "tracking.add",
            "tracking.remove",
            "tracking.remove-all",
            "tracking.notifications",
            "tracking.webhook",
        }:
            return _tracking_request(command, params, fixture_dir)
        if command == "products.get":
            return _product_get(params, fixture_dir)
        if command == "products.compare":
            return _products_compare(params, fixture_dir)
        if command == "products.search":
            return _product_search(params, fixture_dir)
        if command == "categories.get":
            return _categories_get(params, fixture_dir)
        if command == "categories.search":
            return _categories_search(params, fixture_dir)
        if command == "categories.products":
            return _categories_products(params, fixture_dir)
        if command == "finder.query":
            return _selection_query("finder.query", "/query", params, fixture_dir)
        if command == "deals.query":
            return _selection_query("deals.query", "/deal", params, fixture_dir)
        if command == "sellers.get":
            return _seller_get(params, fixture_dir)
        if command == "bestsellers.get":
            return _bestsellers_get(params, fixture_dir)
        if command in {"topsellers.list", "topseller.list"}:
            return _topsellers_list(params, fixture_dir)
        if command == "history.export":
            return _history_export(params, fixture_dir)
        if command in {"history.trend", "history.analyze"}:
            return _history_trend(params, fixture_dir)
        if command in {"schema.generate", "schemas.generate"}:
            return _schema_generate(params)
        if command in {"cassettes.sanitize", "cassette.sanitize"}:
            return _cassettes_sanitize(params)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return error_envelope(command=command, kind="invalid_argument", message=str(exc))

    return error_envelope(
        command=command or "service",
        kind="unsupported_command",
        message=f"unsupported command: {command}",
    )
