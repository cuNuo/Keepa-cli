"""
keepa_cli/service.py
文件说明：提供 CLI、stdio 与 TUI 共用的 Agent-safe command service。
主要职责：把高层命令转换为官方 Keepa endpoint、参数、预算和 envelope。
依赖边界：不处理终端输入输出，不保存凭据，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.agent_contract import attach_agent_profile
from keepa_cli.capabilities import build_capabilities
from keepa_cli.cassettes import promote_cassette_fixture, sanitize_cassette_file
from keepa_cli.commands.business import can_handle as can_handle_business_command
from keepa_cli.commands.business import handle_business_command
from keepa_cli.commands.cache import can_handle as can_handle_cache_command
from keepa_cli.commands.cache import handle_cache_command
from keepa_cli.commands.categories import can_handle as can_handle_category_command
from keepa_cli.commands.categories import handle_category_command
from keepa_cli.commands.common import as_list as _as_list
from keepa_cli.commands.common import bool_option as _bool_option
from keepa_cli.commands.common import bool_param as _bool_param
from keepa_cli.commands.common import client as _client
from keepa_cli.commands.common import confirmation_required as _confirmation_required
from keepa_cli.commands.common import live_cache_options as _live_cache_options
from keepa_cli.commands.common import param as _param
from keepa_cli.commands.deals import can_handle as can_handle_deals_command
from keepa_cli.commands.deals import handle_deals_command
from keepa_cli.commands.docs import can_handle as can_handle_docs_command
from keepa_cli.commands.docs import handle_docs_command
from keepa_cli.commands.finder import can_handle as can_handle_finder_command
from keepa_cli.commands.finder import handle_finder_command
from keepa_cli.commands.history import can_handle as can_handle_history_command
from keepa_cli.commands.history import handle_history_command
from keepa_cli.commands.products import can_handle as can_handle_product_command
from keepa_cli.commands.products import handle_product_command
from keepa_cli.commands.raw import can_handle as can_handle_raw_command
from keepa_cli.commands.raw import handle_raw_command
from keepa_cli.commands.tracking import can_handle as can_handle_tracking_command
from keepa_cli.commands.tracking import handle_tracking_command
from keepa_cli.commands.workflows import can_handle as can_handle_workflow_command
from keepa_cli.commands.workflows import handle_workflow_command
from keepa_cli.config import build_config_report, init_config, set_api_token, set_language, set_max_tokens_per_request
from keepa_cli.doctor import build_doctor_report
from keepa_cli.domains import list_domains, resolve_domain
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.fixture_sync import compare_fixture_dirs
from keepa_cli.high_value import attach_output_if_requested
from keepa_cli.research_graph import (
    build_category_products_graph,
    build_seller_graph,
    build_topsellers_graph,
    extract_research_graphs,
    graph_summary,
    merge_research_graphs,
)
from keepa_cli.research_brief import build_research_brief
from keepa_cli.schema_docs import generate_product_agent_schema
from keepa_cli.token_budget import estimate_request_budget


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _tokens_status(params: Mapping[str, Any], fixture_dir: Path | str | None) -> dict[str, Any]:
    return _client(fixture_dir).request(
        command="tokens.status",
        method="GET",
        path="/token",
        params={},
        dry_run=_bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
        **_live_cache_options(params),
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
        **_live_cache_options(params),
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
        **_live_cache_options(params),
    )
    data = payload.get("data")
    if payload.get("ok") and isinstance(data, dict):
        body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
        data["research_graph"] = build_seller_graph(sellers=sellers, body=body)
        attach_agent_profile(
            data,
            view="sellers_get",
            summary=f"{len(sellers)} seller ids requested",
            key_facts={
                "seller_count": len(sellers),
                "storefront": bool(_param(params, "storefront")),
                "research_graph_entities": data["research_graph"].get("entity_counts", {}),
            },
            present=["request", "body"] if data.get("body") else ["request"],
            missing=[] if data.get("body") or data.get("dry_run") else ["body"],
            selection_signals={"seller_count": len(sellers), "storefront_requested": bool(_param(params, "storefront"))},
            evidence={
                "seller_ids": ("request.params_redacted.seller", "summary", "Seller ids requested from Keepa."),
                "research_graph": ("research_graph", "summary", "Seller and storefront product entities."),
                "body": ("body.sellers", "summary", "Raw seller map when available."),
                "output": ("output", "audit", "Large response output path when --out is used."),
                "provenance": ("cache_provenance", "audit", "Fixture/cache/source provenance for the request."),
            },
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
        **_live_cache_options(params),
    )
    data = payload.get("data")
    if payload.get("ok") and isinstance(data, dict):
        body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
        bestsellers = body.get("bestSellersList") if isinstance(body.get("bestSellersList"), Mapping) else {}
        asin_list = bestsellers.get("asinList") if isinstance(bestsellers.get("asinList"), list) else []
        candidates = [
            {"rank": index + 1, "asin": str(asin), "category_id": str(bestsellers.get("categoryId") or category)}
            for index, asin in enumerate(asin_list[:25])
            if str(asin).strip()
        ]
        data["research_graph"] = build_category_products_graph(
            category_id=str(bestsellers.get("categoryId") or category),
            candidates=candidates,
        )
        attach_agent_profile(
            data,
            view="bestsellers_get",
            summary=f"Best Sellers request for category {category}",
            key_facts={
                "category_id": category,
                "source": "bestsellers",
                "research_graph_entities": data["research_graph"].get("entity_counts", {}),
            },
            present=["request", "body"] if data.get("body") else ["request"],
            missing=[] if data.get("body") or data.get("dry_run") else ["body"],
            selection_signals={"category_id": category, "source": "bestsellers", "candidate_count": len(candidates)},
            evidence={
                "request": ("request", "audit", "Best Sellers request specification."),
                "research_graph": ("research_graph", "summary", "Category and product entities from Best Sellers."),
                "body": ("body.bestSellersList", "summary", "Raw Best Sellers response when available."),
                "output": ("output", "audit", "Large response output path when --out is used."),
                "provenance": ("cache_provenance", "audit", "Fixture/cache/source provenance for the request."),
            },
        )
    return attach_output_if_requested(payload, _param(params, "out", "output"))











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
        **_live_cache_options(params),
    )
    data = payload.get("data")
    if payload.get("ok") and isinstance(data, dict):
        body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
        sellers = body.get("topSellers") if isinstance(body.get("topSellers"), list) else []
        seller_items = [item for item in sellers if isinstance(item, Mapping)]
        data["research_graph"] = build_topsellers_graph(
            sellers=seller_items,
            category_id=str(category) if category is not None else None,
        )
        attach_agent_profile(
            data,
            view="topsellers_list",
            summary="Top Sellers list request prepared",
            key_facts={
                "category_id": str(category) if category is not None else None,
                "seller_count": len(seller_items),
                "research_graph_entities": data["research_graph"].get("entity_counts", {}),
            },
            present=["request", "body"] if data.get("body") else ["request"],
            missing=[] if data.get("body") or data.get("dry_run") else ["body"],
            selection_signals={
                "category_id": str(category) if category is not None else None,
                "source": "topseller",
                "seller_count": len(seller_items),
            },
            evidence={
                "request": ("request", "audit", "Top Sellers request specification."),
                "research_graph": ("research_graph", "summary", "Seller ranking and category entities from Top Sellers."),
                "body": ("body", "summary", "Raw Top Sellers response when available."),
                "output": ("output", "audit", "Large response output path when --out is used."),
                "provenance": ("cache_provenance", "audit", "Fixture/cache/source provenance for the request."),
            },
        )
    return attach_output_if_requested(payload, _param(params, "out", "output"))


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


def _cassettes_promote(params: Mapping[str, Any]) -> dict[str, Any]:
    input_path = params.get("input") or params.get("in")
    name = params.get("name")
    if not input_path or not name:
        return error_envelope(
            command="cassettes.promote",
            kind="invalid_argument",
            message="cassettes.promote requires input and name",
        )
    metadata = promote_cassette_fixture(
        Path(str(input_path)),
        name=str(name),
        tests_dir=Path(str(params.get("tests_dir") or params.get("tests-dir") or "tests/fixtures")),
        package_dir=Path(str(params.get("package_dir") or params.get("package-dir") or "keepa_cli/fixtures")),
        manifest_path=None if _bool_option(params, "no_manifest", "no-manifest") else Path(str(params.get("manifest") or "evidence/manifest.csv")),
        title=str(params.get("title") or name),
        dry_run=_bool_option(params, "dry_run", "dry-run"),
    )
    return success_envelope(
        command="cassettes.promote",
        data=metadata,
        request={"transport": "service", "dry_run": _bool_option(params, "dry_run", "dry-run")},
        token_bucket={},
    )


def _cassettes_promote_and_verify(params: Mapping[str, Any]) -> dict[str, Any]:
    input_path = params.get("input") or params.get("in")
    name = params.get("name")
    if not input_path or not name:
        return error_envelope(
            command="cassettes.promote_and_verify",
            kind="invalid_argument",
            message="cassettes.promote_and_verify requires input and name",
        )

    tests_dir = Path(str(params.get("tests_dir") or params.get("tests-dir") or "tests/fixtures"))
    package_dir = Path(str(params.get("package_dir") or params.get("package-dir") or "keepa_cli/fixtures"))
    eval_dir = Path(str(params.get("eval_dir") or params.get("eval-dir") or "tests/agent_eval_fixtures"))
    run_eval = _bool_option(params, "run_eval", "run-eval")
    dry_run = _bool_option(params, "dry_run", "dry-run")
    metadata = promote_cassette_fixture(
        Path(str(input_path)),
        name=str(name),
        tests_dir=tests_dir,
        package_dir=package_dir,
        manifest_path=None if _bool_option(params, "no_manifest", "no-manifest") else Path(str(params.get("manifest") or "evidence/manifest.csv")),
        title=str(params.get("title") or name),
        dry_run=dry_run,
    )

    fixture_sync = None
    agent_eval = None
    if not dry_run:
        sync = compare_fixture_dirs(tests_dir, package_dir)
        fixture_sync = sync.to_dict()
        if run_eval:
            try:
                from keepa_cli.agent_eval import check_agent_eval_fixtures

                checked = check_agent_eval_fixtures(eval_dir, tests_dir)
                agent_eval = {"ok": True, "checked_specs": checked, "count": len(checked), "eval_dir": str(eval_dir)}
            except AssertionError as exc:
                agent_eval = {"ok": False, "error": str(exc), "eval_dir": str(eval_dir)}
    else:
        fixture_sync = {"ok": None, "skipped": "dry_run"}
        if run_eval:
            agent_eval = {"ok": None, "skipped": "dry_run"}

    ok = bool(fixture_sync.get("ok")) if not dry_run else True
    if agent_eval is not None and agent_eval.get("ok") is False:
        ok = False

    payload = success_envelope if ok else error_envelope
    if ok:
        return payload(
            command="cassettes.promote_and_verify",
            data={
                "view": "cassette_promote_and_verify",
                "promotion": metadata,
                "fixture_sync": fixture_sync,
                "agent_eval": agent_eval,
                "next_actions": [
                    {
                        "label": "Re-run promotion parity after editing Agent eval specs",
                        "tool": "cassettes_promote_and_verify",
                        "params": {"input": str(input_path), "name": metadata["fixture_name"], "run_eval": True},
                    },
                    {"label": "Review evidence manifest entry before committing", "path": str(metadata.get("manifest") or "")},
                ],
            },
            request={"transport": "service", "dry_run": dry_run, "run_eval": run_eval},
            token_bucket={},
        )
    return payload(
        command="cassettes.promote_and_verify",
        kind="fixture_sync_failed",
        message="promoted cassette fixture did not pass fixture sync verification",
        details={"promotion": metadata, "fixture_sync": fixture_sync, "agent_eval": agent_eval},
    )


def _research_graph_merge(params: Mapping[str, Any]) -> dict[str, Any]:
    graphs: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    raw_graphs = params.get("graph") if params.get("graph") is not None else params.get("graphs")
    if isinstance(raw_graphs, Mapping):
        graph_inputs: list[Any] = [raw_graphs]
    elif isinstance(raw_graphs, list | tuple):
        graph_inputs = list(raw_graphs)
    else:
        graph_inputs = []
    for index, graph in enumerate(graph_inputs):
        if isinstance(graph, Mapping):
            extracted = extract_research_graphs(graph)
            graphs.extend(extracted)
            sources.append({"kind": "inline", "index": index, "graph_count": len(extracted)})
    for raw_path in _as_list(params.get("input") or params.get("inputs")):
        path = Path(str(raw_path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        extracted = extract_research_graphs(payload)
        graphs.extend(extracted)
        sources.append({"kind": "file", "path": str(path), "graph_count": len(extracted)})
    if not graphs:
        return error_envelope(
            command="research_graph.merge",
            kind="invalid_argument",
            message="research_graph.merge requires at least one input JSON with research_graph data",
        )
    root = str(_param(params, "root", default="merged_research_graph"))
    label = str(_param(params, "label", default="merged research graph"))
    prefer_source = _param(params, "prefer_source", "prefer-source")
    graph = merge_research_graphs(graphs, root=root, label=label, prefer_source=prefer_source)
    data: dict[str, Any] = {
        "view": "research_graph_merge",
        "graph": graph,
        "summary": graph_summary(graph),
        "diagnostics": graph.get("diagnostics", {}),
        "diff": graph.get("diff", {}),
        "input_graph_count": len(graphs),
        "sources": sources,
        "agent_brief": {
            "one_line": f"merged {len(graphs)} research graphs into {graph.get('node_count', 0)} nodes",
            "key_facts": graph_summary(graph),
            "read_order": ["summary", "diagnostics", "diff", "graph", "sources"],
        },
        "data_quality": {
            "present": ["graph", "summary", "diagnostics", "diff", "sources"],
            "missing": [],
            "confidence": "high",
        },
        "evidence_index": {
            "graph": {"path": "graph", "section": "summary", "note": "Merged research graph."},
            "diagnostics": {"path": "diagnostics", "section": "audit", "note": "Duplicate, orphan, conflict, and source-weight checks."},
            "diff": {"path": "diff", "section": "audit", "note": "Changed node variants and selected source-preference resolutions."},
            "sources": {"path": "sources", "section": "audit", "note": "Input files or inline graph sources."},
        },
        "provenance": {"source": "local", "network": False},
    }
    out = _param(params, "out", "output")
    if out:
        output_path = Path(str(out))
        if output_path.parent != Path("."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        data["output"] = {"path": str(output_path), "format": "json", "size_bytes": output_path.stat().st_size}
    return success_envelope(
        command="research_graph.merge",
        data=data,
        request={"transport": "service"},
        token_bucket={},
    )


def _research_brief_export(params: Mapping[str, Any]) -> dict[str, Any]:
    brief = build_research_brief(params)
    data: dict[str, Any] = {
        "view": "research_brief_export",
        "brief": brief,
        "agent_brief": {
            "one_line": brief["decision_summary"]["one_line"],
            "key_facts": {
                "brief_id": brief["id"],
                "title": brief["title"],
                "risk_count": brief["risk_summary"]["risk_count"],
                "entity_graph_summary": brief.get("entity_graph_summary"),
            },
            "read_order": brief["recommended_read_order"],
        },
        "data_quality": brief["data_quality"],
        "evidence_index": {
            "brief": {"path": "brief", "section": "summary", "note": "Exported research brief for downstream Agent synthesis."},
            "decision_summary": {"path": "brief.decision_summary", "section": "summary", "note": "Compact decision facts."},
            "risk_summary": {"path": "brief.risk_summary", "section": "summary", "note": "Deduplicated risk codes and severities."},
            "follow_up_plan": {"path": "brief.follow_up_plan", "section": "summary", "note": "Executable follow-up actions when present."},
        },
        "provenance": brief["provenance"],
    }
    out = _param(params, "out", "output")
    if out:
        output_path = Path(str(out))
        if output_path.parent != Path("."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        data["output"] = {"path": str(output_path), "format": "json", "size_bytes": output_path.stat().st_size}
    return success_envelope(
        command="research_brief.export",
        data=data,
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
        if can_handle_cache_command(command):
            return handle_cache_command(command, params, env=env)
        if can_handle_docs_command(command):
            return handle_docs_command(command, params)
        if can_handle_workflow_command(command):
            return handle_workflow_command(command, params)
        if can_handle_business_command(command):
            return handle_business_command(command, params, fixture_dir=fixture_dir)
        if can_handle_product_command(command):
            return handle_product_command(command, params, fixture_dir=fixture_dir)
        if can_handle_category_command(command):
            return handle_category_command(command, params, fixture_dir=fixture_dir)
        if can_handle_tracking_command(command):
            return handle_tracking_command(command, params, fixture_dir=fixture_dir)
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
        if can_handle_raw_command(command):
            return handle_raw_command(command, params, fixture_dir=fixture_dir)
        if command in {"tokens.status", "token.status"}:
            return _tokens_status(params, fixture_dir)
        if command in {"graphs.image", "graph.image"}:
            return _graph_image(params, fixture_dir)
        if command in {"lightningdeals.list", "lightningdeal.list"}:
            return _lightningdeals_list(params, fixture_dir)
        if can_handle_finder_command(command):
            return handle_finder_command(command, params, fixture_dir=fixture_dir)
        if can_handle_deals_command(command):
            return handle_deals_command(command, params, fixture_dir=fixture_dir)
        if command == "sellers.get":
            return _seller_get(params, fixture_dir)
        if command == "bestsellers.get":
            return _bestsellers_get(params, fixture_dir)
        if command in {"topsellers.list", "topseller.list"}:
            return _topsellers_list(params, fixture_dir)
        if can_handle_history_command(command):
            return handle_history_command(command, params, fixture_dir=fixture_dir)
        if command in {"schema.generate", "schemas.generate"}:
            return _schema_generate(params)
        if command in {"cassettes.sanitize", "cassette.sanitize"}:
            return _cassettes_sanitize(params)
        if command in {"cassettes.promote", "cassette.promote", "fixtures.promote", "fixture.promote"}:
            return _cassettes_promote(params)
        if command in {"cassettes.promote_and_verify", "cassettes.promote-and-verify", "cassette.promote_and_verify", "fixture.promote_and_verify"}:
            return _cassettes_promote_and_verify(params)
        if command in {"research_graph.merge", "research-graph.merge", "graph.merge"}:
            return _research_graph_merge(params)
        if command in {"research_brief.export", "research-brief.export", "brief.export"}:
            return _research_brief_export(params)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return error_envelope(command=command, kind="invalid_argument", message=str(exc))

    return error_envelope(
        command=command or "service",
        kind="unsupported_command",
        message=f"unsupported command: {command}",
    )
