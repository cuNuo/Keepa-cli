"""
keepa_cli/commands/categories.py
文件说明：categories 命令族 service 路由。
主要职责：把分类查询、分类候选和 Finder scaffold 封装为 Agent-safe envelope。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepa_cli.agent_contract import attach_agent_profile, build_action
from keepa_cli.commands.common import (
    as_list,
    bool_option,
    bool_param,
    client,
    confirmation_required,
    live_cache_options,
    param,
)
from keepa_cli.commands.products import product_get
from keepa_cli.domains import resolve_domain
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.high_value import attach_output_if_requested
from keepa_cli.research_graph import (
    build_category_candidates_graph,
    build_category_graph,
    build_category_products_graph,
)
from keepa_cli.token_budget import estimate_request_budget


CATEGORY_COMMANDS = {
    "categories.get",
    "categories.search",
    "categories.finder-selection",
    "categories.finder_selection",
    "categories.products",
}


def can_handle(command: str) -> bool:
    return command in CATEGORY_COMMANDS


def handle_category_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    if command == "categories.get":
        return categories_get(params, fixture_dir)
    if command == "categories.search":
        return categories_search(params, fixture_dir)
    if command in {"categories.finder-selection", "categories.finder_selection"}:
        return categories_finder_selection(params)
    if command == "categories.products":
        return categories_products(params, fixture_dir)
    raise ValueError(f"unsupported categories command: {command}")


def categories_get(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    categories = as_list(params.get("category") or params.get("categories"))
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
        "parents": bool_param(params.get("parents", False)),
    }
    return client(fixture_dir).request(
        command="categories.get",
        method="GET",
        path="/category",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )


def categories_search(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
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
    payload = client(fixture_dir).request(
        command="categories.search",
        method="GET",
        path="/search",
        params=request_params,
        dry_run=bool(params.get("dry_run")),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
    if not payload.get("ok"):
        return payload
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("dry_run"):
        return payload
    body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
    data.update(category_search_view(body, term=term, domain=str(params.get("domain", "US"))))
    return payload


def category_search_view(body: Mapping[str, Any], *, term: str, domain: str) -> dict[str, Any]:
    categories = body.get("categories") if isinstance(body.get("categories"), Mapping) else {}
    candidates: list[dict[str, Any]] = []
    for raw_id, raw_category in categories.items():
        if not isinstance(raw_category, Mapping):
            continue
        category_id = str(raw_category.get("catId") or raw_id)
        children = raw_category.get("children") if isinstance(raw_category.get("children"), list) else []
        candidates.append(
            {
                "category_id": category_id,
                "name": raw_category.get("name"),
                "parent": raw_category.get("parent"),
                "children_count": len(children),
                "matched": bool(raw_category.get("matched")),
                "next_actions": [
                    build_action(
                        tool="categories.products",
                        params={"category": category_id, "domain": domain, "limit": 25, "dry_run": True},
                        cli=f"categories products {category_id} --domain {domain} --limit 25 --dry-run",
                        reason="preview the 50-token Best Sellers request before fetching ASIN candidates",
                        estimated_tokens=0,
                        requires_confirmation=False,
                    ),
                    build_action(
                        tool="categories.finder-selection",
                        params={"category": category_id, "domain": domain, "out": f"finder-category-{category_id}.json"},
                        cli=f"categories finder-selection {category_id} --domain {domain} --out finder-category-{category_id}.json",
                        reason="create a local Product Finder selection scaffold for this category",
                    ),
                ],
            }
        )
    candidates.sort(key=lambda item: (not item["matched"], str(item.get("name") or ""), item["category_id"]))
    result = {
        "view": "category_search",
        "term": term,
        "category_candidate_count": len(candidates),
        "category_candidates": candidates,
        "research_graph": build_category_candidates_graph(candidates, term=term),
        "next_actions": [
            item
            for candidate in candidates[:3]
            for item in candidate["next_actions"]
        ],
    }
    return attach_agent_profile(
        result,
        view="category_search",
        summary=f"{len(candidates)} category candidates for {term}",
        key_facts={
            "term": term,
            "candidate_count": len(candidates),
            "top_category_id": candidates[0]["category_id"] if candidates else None,
            "research_graph_entities": result["research_graph"].get("entity_counts", {}),
        },
        present=["categories", "category_candidates"] if candidates else ["categories"],
        missing=[] if candidates else ["category_candidates"],
        selection_signals={"candidate_count": len(candidates), "matched_count": len([item for item in candidates if item["matched"]])},
        evidence={
            "category_candidates": ("category_candidates", "summary", "Candidate category ids derived from Keepa category search."),
            "research_graph": ("research_graph", "summary", "Search term, category candidate, and parent category entities."),
            "raw_categories": ("body.categories", "audit", "Raw Keepa category search response."),
            "next_actions": ("next_actions", "summary", "Structured category follow-up actions."),
            "provenance": ("cache_provenance", "audit", "Fixture/cache/source provenance for the category search."),
        },
    )


def categories_finder_selection(params: Mapping[str, Any]) -> dict[str, Any]:
    category = str(param(params, "category", "category_id", "category-id", default="")).strip()
    if not category:
        return error_envelope(
            command="categories.finder-selection",
            kind="invalid_argument",
            message="categories.finder-selection requires a category id",
        )

    domain = str(params.get("domain", "US"))
    per_page = int(param(params, "per_page", "per-page", default=50) or 50)
    sales_rank_max = int(param(params, "sales_rank_max", "sales-rank-max", default=20000) or 20000)
    min_reviews = int(param(params, "min_reviews", "min-reviews", default=50) or 50)
    selection = {
        "categories_include": [int(category) if category.isdigit() else category],
        "current_SALES_gte": 1,
        "current_SALES_lte": sales_rank_max,
        "current_COUNT_REVIEWS_gte": min_reviews,
        "sort": [["current_SALES", "asc"]],
        "perPage": per_page,
        "page": 0,
    }
    data: dict[str, Any] = {
        "view": "finder_selection_scaffold",
        "category_id": category,
        "domain": domain,
        "selection": selection,
        "research_graph": build_category_graph(category_id=category, evidence_path="selection.categories_include"),
        "field_notes": [
            "categories_include is an Agent-level scaffold field; verify against Keepa Finder field support before live query if your account expects a different category selector.",
            "The scaffold is local-only and does not consume Keepa tokens.",
        ],
        "next_actions": [
            build_action(
                tool="finder.query",
                params={"selection_file": "<PATH>", "domain": domain, "dry_run": True, "max_tokens": 25},
                cli=f"finder query --selection-file <PATH> --domain {domain} --dry-run --max-tokens 25",
                reason="validate the generated selection request shape without consuming tokens",
                estimated_tokens=0,
                requires_confirmation=False,
            ),
            build_action(
                tool="categories.products",
                params={"category": category, "domain": domain, "limit": 25, "dry_run": True},
                cli=f"categories products {category} --domain {domain} --limit 25 --dry-run",
                reason="preview Best Sellers category candidate retrieval",
                estimated_tokens=0,
                requires_confirmation=False,
            ),
        ],
    }
    output_path = param(params, "out", "output")
    if output_path:
        path = Path(str(output_path))
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        data["output"] = {
            "path": str(path),
            "format": "json",
            "size_bytes": path.stat().st_size,
            "result_count": 1,
        }
        data["next_actions"][0] = build_action(
            tool="finder.query",
            params={"selection_file": str(path), "domain": domain, "dry_run": True, "max_tokens": 25},
            cli=f"finder query --selection-file {path} --domain {domain} --dry-run --max-tokens 25",
            reason="validate the generated selection request shape without consuming tokens",
            estimated_tokens=0,
            requires_confirmation=False,
        )
    attach_agent_profile(
        data,
        view="finder_selection_scaffold",
        summary=f"Finder selection scaffold for category {category}",
        key_facts={
            "category_id": category,
            "domain": domain,
            "per_page": per_page,
            "research_graph_entities": data["research_graph"].get("entity_counts", {}),
        },
        present=["selection", "next_actions"],
        notes=["local scaffold only; verify category selector field before live Finder query"],
        selection_signals={"category_id": category, "sales_rank_max": sales_rank_max, "min_reviews": min_reviews},
        evidence={
            "selection": ("selection", "summary", "Generated Product Finder selection scaffold."),
            "research_graph": ("research_graph", "summary", "Category entity targeted by the generated Finder scaffold."),
            "field_notes": ("field_notes", "audit", "Known caveats for category selector compatibility."),
            "next_actions": ("next_actions", "summary", "Structured follow-up actions."),
            "output": ("output", "audit", "Selection JSON output path when --out is used."),
        },
    )
    return success_envelope(
        command="categories.finder-selection",
        data=data,
        request={"transport": "service", "dry_run": True},
        token_bucket={"estimated": estimate_request_budget("categories.finder-selection", dict(params)).to_dict()},
    )


def categories_products(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    category = str(param(params, "category", "category_id", "category-id", default="")).strip()
    if not category:
        return error_envelope(
            command="categories.products",
            kind="invalid_argument",
            message="categories.products requires a category id",
        )

    limit = int(param(params, "limit", "max_asins", "max-asins", default=25) or 25)
    if limit <= 0:
        return error_envelope(
            command="categories.products",
            kind="invalid_argument",
            message="categories.products limit must be positive",
        )
    hydrate_top = int(param(params, "hydrate_top", "hydrate-top", default=0) or 0)
    if hydrate_top < 0:
        return error_envelope(
            command="categories.products",
            kind="invalid_argument",
            message="categories.products hydrate_top must be zero or positive",
        )

    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "category": category,
    }
    confirmation = confirmation_required("categories.products", {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = client(fixture_dir).request(
        command="categories.products",
        method="GET",
        path="/bestsellers",
        params=request_params,
        dry_run=bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
        **live_cache_options(params),
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
        data["hydration"] = {
            "enabled": False,
            "requested": hydrate_top,
            "reason": "dry-run never hydrates products",
        }
        data["official_cost_note"] = "Live categories.products uses Keepa /bestsellers. The official base cost is 50 tokens; limit only reduces returned/output candidates, not the /bestsellers base cost."
        data["research_graph"] = build_category_products_graph(category_id=category, candidates=[])
        data["next_actions"] = [
            build_action(
                tool="categories.products",
                params={"category": category, "domain": "<DOMAIN>", "limit": limit, "yes": True},
                cli=f"categories products {category} --domain <DOMAIN> --limit {limit} --yes",
                reason="fetch category ASIN candidates from Keepa Best Sellers",
                estimated_tokens=50,
            )
        ]
        if hydrate_top:
            data["next_actions"].append(
                build_action(
                    tool="categories.products",
                    params={"category": category, "domain": "<DOMAIN>", "limit": limit, "hydrate_top": hydrate_top, "yes": True},
                    cli=f"categories products {category} --domain <DOMAIN> --limit {limit} --hydrate-top {hydrate_top} --yes",
                    reason="fetch category ASIN candidates and explicitly hydrate top product summaries",
                    estimated_tokens=50 + hydrate_top,
                )
            )
        data["alternative_actions"] = [
            build_action(
                tool="categories.finder-selection",
                params={"category": category, "domain": "<DOMAIN>", "out": f"finder-category-{category}.json"},
                cli=f"categories finder-selection {category} --domain <DOMAIN> --out finder-category-{category}.json",
                reason="build a local Finder scaffold before deciding whether /bestsellers is worth 50 tokens",
                estimated_tokens=0,
                requires_confirmation=False,
            ),
            build_action(
                tool="categories.search",
                params={"term": "<TERM>", "domain": "<DOMAIN>"},
                cli="categories search <TERM> --domain <DOMAIN>",
                reason="verify category ids before spending the official /bestsellers cost",
                estimated_tokens=1,
                requires_confirmation=False,
            ),
            build_action(
                tool="products.compare",
                params={"asin": ["<ASIN1>", "<ASIN2>"], "domain": "<DOMAIN>", "full": True, "view": "deal"},
                cli="products compare <ASIN1> <ASIN2> --domain <DOMAIN> --full --view deal",
                reason="compare known candidate ASINs from web search or prior research without calling /bestsellers",
                estimated_tokens=2,
                requires_confirmation=False,
            ),
        ]
        attach_agent_profile(
            data,
            view="category_products",
            summary=f"Dry-run category product candidates for {category}",
            key_facts={
                "category_id": category,
                "source": "bestsellers",
                "limit": limit,
                "research_graph_entities": data["research_graph"].get("entity_counts", {}),
            },
            present=["request", "next_actions", "official_cost_note"],
            missing=["asins"],
            selection_signals={"source": "bestsellers", "estimated_candidate_limit": limit},
            evidence={
                "request": ("request", "audit", "Dry-run Keepa request specification."),
                "research_graph": ("research_graph", "summary", "Category entity for the planned Best Sellers request."),
                "next_actions": ("next_actions", "summary", "Structured follow-up actions."),
                "alternative_actions": ("alternative_actions", "summary", "Lower-risk planning paths before a 50-token Best Sellers request."),
                "hydration": ("hydration", "summary", "Hydration status and requested top-N count."),
            },
        )
        return payload

    body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
    normalized = category_products_view(body, category=category, limit=limit, domain=str(params.get("domain", "US")))
    data.update(normalized)
    data["hydration"] = hydrate_category_products(data["asins"], hydrate_top=hydrate_top, params=params, fixture_dir=fixture_dir)
    attach_agent_profile(
        data,
        view="category_products",
        summary=f"{len(data.get('asins') or [])} ASIN candidates from category {data.get('category_id')}",
        key_facts={
            "category_id": data.get("category_id"),
            "candidate_count": data.get("candidate_count"),
            "source": data.get("source"),
            "research_graph_entities": data.get("research_graph", {}).get("entity_counts", {}),
        },
        present=["asins", "candidates", "next_actions"],
        missing=[] if data.get("asins") else ["asins"],
        selection_signals={"candidate_count": data.get("candidate_count"), "source": data.get("source"), "hydrated": bool(data["hydration"].get("enabled"))},
        evidence={
            "candidates": ("candidates", "summary", "Ranked ASIN candidates from Best Sellers."),
            "research_graph": ("research_graph", "summary", "Category and candidate product entities from Best Sellers."),
            "asins": ("asins", "summary", "Candidate ASIN list for compare/get follow-up."),
            "hydration": ("hydration", "summary", "Optional hydrated Agent product summaries."),
            "raw_bestsellers": ("body.bestSellersList", "audit", "Raw Keepa Best Sellers payload."),
            "provenance": ("cache_provenance", "audit", "Fixture/cache/source provenance for the request."),
        },
    )
    token_bucket = payload.get("token_bucket")
    if isinstance(token_bucket, dict):
        token_bucket["estimated"] = estimate_request_budget("categories.products", {**dict(params), **request_params}).to_dict()
    return attach_output_if_requested(payload, param(params, "out", "output"))


def category_products_view(body: Mapping[str, Any], *, category: str, limit: int, domain: str) -> dict[str, Any]:
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
        "research_graph": build_category_products_graph(category_id=str(bestsellers.get("categoryId") or category), candidates=candidates),
        "next_actions": [
            item
            for item in (
                build_action(
                    tool="products.compare",
                    params={"asin": asins[:10], "domain": domain, "full": True, "view": "deal"},
                    cli=compare_command or "",
                    reason="compare top category candidates with deal profile",
                    estimated_tokens=max(1, len(asins[:10])),
                )
                if compare_command
                else None,
                build_action(
                    tool="products.get",
                    params={"asin": asins[0], "domain": domain, "full": True, "agent_view": True, "view": "summary"},
                    cli=get_command or "",
                    reason="inspect the top category candidate with Agent summary",
                )
                if get_command
                else None,
            )
            if item is not None
        ],
    }


def hydrate_category_products(
    asins: Sequence[str],
    *,
    hydrate_top: int,
    params: Mapping[str, Any],
    fixture_dir: Path | str | None,
) -> dict[str, Any]:
    if hydrate_top <= 0:
        return {
            "enabled": False,
            "requested": 0,
            "reason": "pass --hydrate-top N to explicitly fetch top product summaries",
        }
    selected = [asin for asin in asins[:hydrate_top] if asin]
    if not selected:
        return {"enabled": True, "requested": hydrate_top, "asins": [], "products": [], "errors": []}

    product_params: dict[str, Any] = {
        "asin": selected,
        "domain": params.get("domain", "US"),
        "full": True,
        "agent_view": True,
        "view": "summary",
        "history_limit": int(param(params, "history_limit", "history-limit", default=3) or 3),
        "temporal_windows": param(params, "temporal_windows", "temporal-window-days", "temporal_window_days"),
    }
    product_fixture = param(params, "product_fixture", "product-fixture")
    if product_fixture:
        product_params["fixture"] = product_fixture
    product_payload = product_get(product_params, fixture_dir)
    data = product_payload.get("data") if isinstance(product_payload.get("data"), Mapping) else {}
    products = data.get("products") if isinstance(data.get("products"), list) else []
    return {
        "enabled": True,
        "requested": hydrate_top,
        "hydrated_count": len(products),
        "asins": selected,
        "view": data.get("view"),
        "profile": data.get("profile"),
        "products": products,
        "errors": [] if product_payload.get("ok") else [product_payload.get("error")],
        "token_bucket": product_payload.get("token_bucket", {}),
    }
