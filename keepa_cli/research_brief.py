"""
keepa_cli/research_brief.py
文件说明：把多步 Agent 调研输出汇总为稳定 research brief。
主要职责：从本地 JSON payload 或 inline payload 提取决策摘要、风险、图谱、后续动作与证据链接。
依赖边界：纯本地 JSON 转换，不访问 Keepa API。
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.research_graph import extract_research_graphs, graph_summary, merge_research_graphs


RESEARCH_BRIEF_SCHEMA_VERSION = "2026-05-12.1"


def build_research_brief(params: Mapping[str, Any]) -> dict[str, Any]:
    payloads, sources = _load_payloads(params)
    if not payloads:
        raise ValueError("research_brief.export requires input JSON files, inline payload, or graph")

    title = str(params.get("title") or params.get("label") or "Keepa research brief")
    graphs = []
    for payload in payloads:
        graphs.extend(extract_research_graphs(payload))
    graph = _summary_graph(params, graphs, title=title)
    graph_summary_value = graph_summary(graph) if isinstance(graph, Mapping) else None

    decision_items = _decision_items(payloads)
    risks = _risk_items(payloads)
    next_actions = _next_actions(payloads)
    evidence_links = _evidence_links(payloads)
    brief_id = str(params.get("id") or params.get("brief_id") or _default_brief_id(title, graph, sources))
    external_signal_stub = _brief_slot(
        params,
        payloads,
        "external_signal_stub",
        expected_inputs=["ads_transparency", "amazon_live", "tiktok_shop_or_video", "publisher_reviews", "search_ads_observations"],
    )
    ip_risk_inputs = _brief_slot(
        params,
        payloads,
        "ip_risk_inputs",
        expected_inputs=["patent_search_queries", "patent_publication_numbers", "assignee_or_brand_matches", "design_patent_flags", "fto_review_owner"],
    )
    claim_risk_inputs = _brief_slot(
        params,
        payloads,
        "claim_risk_inputs",
        expected_inputs=["product_claims", "regulated_terms", "evidence_required", "marketplace_policy_refs", "review_owner"],
    )

    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "view": "research_brief_export",
        "id": brief_id,
        "title": title,
        "decision_summary": {
            "one_line": _decision_one_line(decision_items, graph_summary_value),
            "items": decision_items[:20],
        },
        "risk_summary": _risk_summary(risks),
        "entity_graph_summary": graph_summary_value,
        "input_summary": {
            "payload_count": len(payloads),
            "research_graph_count": len(graphs),
            "sources": sources,
        },
        "follow_up_plan": {
            "next_actions": next_actions[:20],
            "action_count": len(next_actions),
        },
        "evidence_links": evidence_links[:50],
        "external_signal_stub": external_signal_stub,
        "ip_risk_inputs": ip_risk_inputs,
        "claim_risk_inputs": claim_risk_inputs,
        "data_quality": {
            "present": _present_sections(decision_items, risks, graph_summary_value, next_actions, evidence_links, external_signal_stub, ip_risk_inputs, claim_risk_inputs),
            "missing": _missing_sections(decision_items, risks, graph_summary_value, next_actions, evidence_links, external_signal_stub, ip_risk_inputs, claim_risk_inputs),
            "confidence": "high" if graph_summary_value or decision_items else "medium",
        },
        "provenance": {
            "source": "local://keepa_cli.research_brief.build_research_brief",
            "network": False,
        },
        "recommended_read_order": [
            "decision_summary",
            "risk_summary",
            "entity_graph_summary",
            "follow_up_plan",
            "evidence_links",
            "external_signal_stub",
            "ip_risk_inputs",
            "claim_risk_inputs",
            "input_summary",
        ],
    }


def brief_resource_payload(cache_key: str, cached: Mapping[str, Any] | None) -> dict[str, Any]:
    found = isinstance(cached, Mapping)
    data = cached.get("data") if found and isinstance(cached.get("data"), Mapping) else {}
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "cache_key": cache_key,
        "found": found,
        "source": "agent_session",
        "brief": copy.deepcopy(data.get("brief")) if isinstance(data, Mapping) else None,
        "note": "Session resources are process-local; call resources/read in the same MCP session that produced this cache_key.",
    }


def brief_graph_resource_payload(cache_key: str, cached: Mapping[str, Any] | None) -> dict[str, Any]:
    found = isinstance(cached, Mapping)
    data = cached.get("data") if found and isinstance(cached.get("data"), Mapping) else {}
    brief = data.get("brief") if isinstance(data, Mapping) and isinstance(data.get("brief"), Mapping) else {}
    return {
        "schema_version": RESEARCH_BRIEF_SCHEMA_VERSION,
        "cache_key": cache_key,
        "found": found,
        "source": "agent_session",
        "entity_graph_summary": copy.deepcopy(brief.get("entity_graph_summary")),
        "input_summary": copy.deepcopy(brief.get("input_summary")),
        "note": "This resource returns graph summary only; use keepa://research/{cache_key}/brief for the full brief.",
    }


def _load_payloads(params: Mapping[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    payloads: list[Any] = []
    sources: list[dict[str, Any]] = []
    inline = params.get("payload") if params.get("payload") is not None else params.get("data")
    for index, item in enumerate(_as_list(inline)):
        payloads.append(item)
        sources.append({"kind": "inline", "index": index})

    graph = params.get("graph")
    if graph is not None:
        payloads.append({"research_graph": graph})
        sources.append({"kind": "inline_graph"})

    for raw_path in _as_list(params.get("input") or params.get("inputs")):
        path = Path(str(raw_path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append(payload)
        sources.append({"kind": "file", "path": str(path)})
    return payloads, sources


def _decision_items(payloads: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path, value in _walk(payloads):
        if not isinstance(value, Mapping):
            continue
        brief = value.get("agent_brief")
        if isinstance(brief, Mapping):
            one_line = brief.get("one_line") or brief.get("summary")
            if one_line:
                items.append(
                    _compact(
                        {
                            "path": path,
                            "one_line": one_line,
                            "key_facts": copy.deepcopy(brief.get("key_facts", {})),
                            "risk_codes": copy.deepcopy(brief.get("risk_codes", [])),
                            "missing_data": copy.deepcopy(brief.get("missing_data", [])),
                        }
                    )
                )
    return _dedupe_items(items, key="one_line")


def _risk_items(payloads: list[Any]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for path, value in _walk(payloads):
        if not isinstance(value, Mapping):
            continue
        taxonomy = value.get("risk_taxonomy")
        if isinstance(taxonomy, Mapping):
            for item in taxonomy.get("items") or []:
                if isinstance(item, Mapping):
                    risks.append(_compact({"path": path, **copy.deepcopy(dict(item))}))
            for code in taxonomy.get("codes") or []:
                risks.append({"path": path, "code": str(code), "severity": taxonomy.get("highest_severity")})
        summary = value.get("risk_summary")
        if isinstance(summary, Mapping):
            by_code = summary.get("by_code") if isinstance(summary.get("by_code"), Mapping) else {}
            for code, count in by_code.items():
                risks.append({"path": path, "code": str(code), "count": count})
    return _dedupe_items(risks, key="code")


def _risk_summary(risks: list[dict[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for risk in risks:
        code = str(risk.get("code") or "").strip()
        severity = str(risk.get("severity") or "unknown").strip()
        if code:
            by_code[code] = by_code.get(code, 0) + int(risk.get("count") or 1)
        if severity:
            by_severity[severity] = by_severity.get(severity, 0) + 1
    return {
        "risk_count": len(risks),
        "by_code": by_code,
        "by_severity": by_severity,
        "items": risks[:20],
    }


def _next_actions(payloads: list[Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for path, value in _walk(payloads):
        if not isinstance(value, Mapping):
            continue
        for action in value.get("next_actions") or []:
            if isinstance(action, Mapping):
                actions.append(_compact({"path": path, **copy.deepcopy(dict(action))}))
        brief = value.get("agent_brief")
        if isinstance(brief, Mapping):
            for action in brief.get("recommended_next_actions") or []:
                if isinstance(action, Mapping):
                    actions.append(_compact({"path": path, **copy.deepcopy(dict(action))}))
    return _dedupe_items(actions, key="tool")


def _evidence_links(payloads: list[Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for path, value in _walk(payloads):
        if not isinstance(value, Mapping):
            continue
        evidence = value.get("evidence_index")
        if isinstance(evidence, Mapping):
            links.append({"path": path, "kind": "evidence_index", "keys": sorted(str(key) for key in evidence.keys())})
        output = value.get("output")
        if isinstance(output, Mapping) and output.get("path") and ("format" in output or "size_bytes" in output or "result_count" in output):
            links.append({"path": path, "kind": "output", "output_path": output.get("path"), "format": output.get("format")})
    return _dedupe_items(links, key="path")


def _brief_slot(
    params: Mapping[str, Any],
    payloads: list[Any],
    key: str,
    *,
    expected_inputs: list[str],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(params.get(key))):
        if isinstance(item, Mapping):
            items.append(_compact({"path": f"$.params.{key}.{index}", **copy.deepcopy(dict(item))}))
    for path, value in _walk(payloads):
        if not isinstance(value, Mapping):
            continue
        slot = value.get(key)
        for index, item in enumerate(_as_list(slot)):
            if isinstance(item, Mapping):
                items.append(_compact({"path": f"{path}.{key}.{index}", **copy.deepcopy(dict(item))}))
    return {
        "status": "provided" if items else "pending_external_research",
        "item_count": len(items),
        "items": _dedupe_items(items, key="path")[:20],
        "expected_inputs": expected_inputs,
        "note": "Keepa does not perform external web, ad transparency, patent, FTO, or legal claim review; merge those public or human-reviewed inputs here.",
    }


def _summary_graph(params: Mapping[str, Any], graphs: list[Mapping[str, Any]], *, title: str) -> Mapping[str, Any] | None:
    graph = _first_mapping(params.get("graph"))
    if isinstance(graph, Mapping):
        return graph
    if not graphs:
        return None
    if len(graphs) == 1:
        return graphs[0]
    root = str(params.get("graph_root") or params.get("id") or params.get("brief_id") or "research_brief_graph")
    return merge_research_graphs(list(graphs), root=root, label=f"{title} graph")


def _first_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                return item
    return None


def _decision_one_line(items: list[dict[str, Any]], graph: Mapping[str, Any] | None) -> str:
    if items:
        return str(items[0].get("one_line") or "")
    if graph:
        return f"research graph has {graph.get('node_count', 0)} nodes and {graph.get('edge_count', 0)} edges"
    return "research brief generated from local payloads"


def _default_brief_id(title: str, graph: Mapping[str, Any] | None, sources: list[dict[str, Any]]) -> str:
    root = str(graph.get("root") or "") if isinstance(graph, Mapping) else ""
    if root:
        return root
    stem = "".join(ch if ch.isalnum() else "_" for ch in title.lower()).strip("_")
    return stem or f"research_brief_{len(sources)}"


def _present_sections(
    decisions: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    graph: Mapping[str, Any] | None,
    actions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    external_signal_stub: Mapping[str, Any],
    ip_risk_inputs: Mapping[str, Any],
    claim_risk_inputs: Mapping[str, Any],
) -> list[str]:
    present = []
    if decisions:
        present.append("decision_summary")
    if risks:
        present.append("risk_summary")
    if graph:
        present.append("entity_graph_summary")
    if actions:
        present.append("follow_up_plan")
    if evidence:
        present.append("evidence_links")
    if external_signal_stub.get("item_count"):
        present.append("external_signal_stub")
    if ip_risk_inputs.get("item_count"):
        present.append("ip_risk_inputs")
    if claim_risk_inputs.get("item_count"):
        present.append("claim_risk_inputs")
    return present


def _missing_sections(
    decisions: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    graph: Mapping[str, Any] | None,
    actions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    external_signal_stub: Mapping[str, Any],
    ip_risk_inputs: Mapping[str, Any],
    claim_risk_inputs: Mapping[str, Any],
) -> list[str]:
    expected = {
        "decision_summary": bool(decisions),
        "risk_summary": bool(risks),
        "entity_graph_summary": bool(graph),
        "follow_up_plan": bool(actions),
        "evidence_links": bool(evidence),
        "external_signal_stub": bool(external_signal_stub.get("item_count")),
        "ip_risk_inputs": bool(ip_risk_inputs.get("item_count")),
        "claim_risk_inputs": bool(claim_risk_inputs.get("item_count")),
    }
    return [key for key, present in expected.items() if not present]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _walk(value: Any, path: str = "$") -> list[tuple[str, Any]]:
    items = [(path, value)]
    if isinstance(value, Mapping):
        for key, item in value.items():
            items.extend(_walk(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            items.extend(_walk(item, f"{path}.{index}"))
    return items


def _dedupe_items(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        marker = str(item.get(key) or item)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
    return deduped


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}
