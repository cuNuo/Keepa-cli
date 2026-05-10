"""
keepa_cli/agent_contract.py
文件说明：提供 Agent 输出契约的共享构造器。
主要职责：统一结构化 next_actions、轻量 profile 与证据索引字段。
依赖边界：纯本地数据整理，不访问 Keepa API，不读取凭据。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from keepa_cli.token_budget import estimate_request_budget


def build_action(
    *,
    tool: str,
    params: Mapping[str, Any] | None = None,
    cli: str,
    reason: str,
    estimated_tokens: int | None = None,
    requires_confirmation: bool | None = None,
) -> dict[str, Any]:
    action_params = dict(params or {})
    budget = estimate_request_budget(tool, action_params).to_dict()
    return {
        "tool": tool,
        "params": action_params,
        "cli": cli,
        "command": cli,
        "reason": reason,
        "estimated_tokens": int(budget["estimated_tokens"] if estimated_tokens is None else estimated_tokens),
        "requires_confirmation": bool(budget["requires_confirmation"] if requires_confirmation is None else requires_confirmation),
    }


def build_agent_brief(
    *,
    view: str,
    summary: str,
    key_facts: Mapping[str, Any] | None = None,
    read_order: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "view": view,
        "one_line": summary,
        "key_facts": dict(key_facts or {}),
        "read_order": list(read_order or ["agent_brief", "data_quality", "selection_signals", "next_actions", "evidence_index"]),
    }


def build_data_quality(*, present: Sequence[str] = (), missing: Sequence[str] = (), notes: Sequence[str] = ()) -> dict[str, Any]:
    present_items = sorted({str(item) for item in present if str(item)})
    missing_items = sorted({str(item) for item in missing if str(item)})
    if missing_items and len(present_items) < 3:
        confidence = "low"
    elif missing_items:
        confidence = "medium"
    else:
        confidence = "high"
    return {
        "present": present_items,
        "missing": missing_items,
        "confidence": confidence,
        "notes": list(notes),
    }


def build_evidence_index(entries: Mapping[str, tuple[str, str, str]]) -> dict[str, dict[str, str]]:
    return {
        name: {"path": path, "section": section, "why": why}
        for name, (path, section, why) in entries.items()
    }


def attach_agent_profile(
    data: dict[str, Any],
    *,
    view: str,
    summary: str,
    key_facts: Mapping[str, Any] | None = None,
    present: Sequence[str] = (),
    missing: Sequence[str] = (),
    notes: Sequence[str] = (),
    selection_signals: Mapping[str, Any] | None = None,
    evidence: Mapping[str, tuple[str, str, str]] | None = None,
    provenance_path: str = "cache_provenance",
) -> dict[str, Any]:
    data.setdefault(
        "agent_brief",
        build_agent_brief(view=view, summary=summary, key_facts=key_facts),
    )
    data.setdefault("data_quality", build_data_quality(present=present, missing=missing, notes=notes))
    data.setdefault("selection_signals", dict(selection_signals or {}))
    data.setdefault(
        "evidence_index",
        build_evidence_index(
            evidence
            or {
                "decision_brief": ("agent_brief", "summary", "Compact read-first summary for Agent planning."),
                "data_quality": ("data_quality", "summary", "Present and missing data for follow-up decisions."),
                "next_actions": ("next_actions", "summary", "Structured follow-up commands with params and budget."),
                "provenance": (provenance_path, "audit", "Source, endpoint, cache, fixture, or output path evidence."),
            }
        ),
    )
    if "provenance" not in data and isinstance(data.get(provenance_path), Mapping):
        data["provenance"] = dict(data[provenance_path])
    return data
