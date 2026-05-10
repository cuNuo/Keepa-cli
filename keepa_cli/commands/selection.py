"""
keepa_cli/commands/selection.py
文件说明：selection 型 Keepa 请求共享工具。
主要职责：为 finder/deals 复用 selection 读取、确认、请求与 Agent profile 附加逻辑。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.agent_contract import attach_agent_profile
from keepa_cli.commands.common import bool_option, client, confirmation_required, live_cache_options, param
from keepa_cli.domains import resolve_domain
from keepa_cli.high_value import attach_output_if_requested, load_selection, selection_to_query_value
from keepa_cli.research_graph import build_deals_graph, build_selection_graph


def attach_selection_profile(payload: dict[str, Any], *, command: str, selection: Mapping[str, Any]) -> None:
    data = payload.get("data")
    if not payload.get("ok") or not isinstance(data, dict):
        return
    present = ["selection", "request"]
    body = data.get("body") if isinstance(data.get("body"), Mapping) else {}
    if body:
        present.append("body")
    deals = body.get("deals") if isinstance(body.get("deals"), list) else []
    if command == "deals.query" and deals:
        data["research_graph"] = build_deals_graph(deals=[item for item in deals if isinstance(item, Mapping)], command=command)
    else:
        data["research_graph"] = build_selection_graph(command=command, selection=selection, body=body)
    attach_agent_profile(
        data,
        view=command.replace(".", "_"),
        summary=f"{command} selection request prepared",
        key_facts={
            "selection_keys": sorted(selection.keys()),
            "dry_run": bool(data.get("dry_run")),
            "research_graph_entities": data["research_graph"].get("entity_counts", {}),
        },
        present=present,
        missing=[] if data.get("body") or data.get("dry_run") else ["body"],
        selection_signals={"selection_keys": sorted(selection.keys()), "selection_size": len(selection)},
        evidence={
            "selection": ("request.params_redacted.selection", "audit", "Serialized Finder/Deals selection sent to Keepa."),
            "research_graph": ("research_graph", "summary", "Selection, category, deal, and product entities derived from the request/response."),
            "body": ("body", "summary", "Raw response body when fixture/live data is available."),
            "output": ("output", "audit", "Large response output path when --out is used."),
            "provenance": ("cache_provenance", "audit", "Fixture/cache/source provenance for the request."),
        },
    )


def selection_query(
    command: str,
    path: str,
    params: Mapping[str, Any],
    fixture_dir: Path | str | None,
) -> dict[str, Any]:
    selection = load_selection(
        param(params, "selection"),
        param(params, "selection_file", "selection-file"),
    )
    request_params: dict[str, Any] = {
        "domain": str(resolve_domain(params.get("domain", "US")).domain_id),
        "selection": selection_to_query_value(selection),
    }
    if param(params, "max_tokens", "max-tokens") is not None:
        request_params["max_tokens"] = int(param(params, "max_tokens", "max-tokens"))

    confirmation = confirmation_required(command, {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = client(fixture_dir).request(
        command=command,
        method="GET",
        path=path,
        params=request_params,
        dry_run=bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
    attach_selection_profile(payload, command=command, selection=selection)
    return attach_output_if_requested(payload, param(params, "out", "output"))
