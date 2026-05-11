"""
keepa_cli/research_context.py
文件说明：提供调研 Agent 的本地上下文、策略和目标解析能力。
主要职责：暴露 MCP/CLI 可复用的 policy、roots、target resolution 与 context query。
依赖边界：只读取项目内 schema、fixture、evidence、zread 与环境布尔状态，不访问 Keepa API。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping


POLICY_SCHEMA_VERSION = "2026-05-11.1"
ASIN_RE = re.compile(r"\b[A-Z0-9]{10}\b", re.IGNORECASE)
UPC_EAN_RE = re.compile(r"\b\d{12,14}\b")
SELLER_RE = re.compile(r"\bA[A-Z0-9]{9,20}\b", re.IGNORECASE)


def build_context_policy(env: Mapping[str, str] | None = None, *, repo_root: Path | str | None = None) -> dict[str, Any]:
    active_env = os.environ if env is None else env
    root = _repo_root(repo_root)
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "view": "context_policy",
        "mode": "offline_first",
        "default_toolset": "research",
        "recommended_start_order": [
            "keepa://context/policy",
            "keepa://tools/index",
            "keepa://prompts/index",
            "keepa://evidence/recent",
            "keepa.resolve_research_target",
            "keepa.query_research_context",
            "keepa.workflow_plan",
        ],
        "live_keepa": {
            "allowed_by_default": False,
            "requires_api_key": True,
            "api_key_configured": bool(active_env.get("KEEPA_API_KEY")),
            "requires_confirmation_for_high_cost": True,
            "safe_defaults": ["fixture", "dry_run", "from_cache"],
        },
        "session_profiles": [
            "offline_fixture_only",
            "dry_run_default",
            "live_read_allowed",
            "tracking_readonly",
            "fixture_curation",
        ],
        "roots": _roots(root),
        "tool_policy": {
            "default_allowed_toolsets": ["research"],
            "explicit_toolsets": ["audit", "business", "docs", "reports", "tracking-readonly", "all"],
            "write_tools_exposed_by_default": False,
            "supports_allow_tools_filter": True,
            "supports_exclude_tools_filter": True,
            "supports_profile_gating": True,
            "profile_behavior": "tools/list marks inactive tools; tools/call returns inactive_tool before service execution when profile disallows a tool",
        },
        "provenance": {
            "source": "local://keepa_cli.research_context.build_context_policy",
            "repo_root": str(root),
        },
    }


def resolve_research_target(params: Mapping[str, Any], *, repo_root: Path | str | None = None) -> dict[str, Any]:
    query = str(params.get("query") or params.get("q") or "").strip()
    domain = str(params.get("domain") or "US").strip() or "US"
    hint_type = str(params.get("hint_type") or params.get("type") or "").strip().lower()
    root = _repo_root(repo_root)

    candidates: list[dict[str, Any]] = []
    for asin in _unique(match.upper() for match in ASIN_RE.findall(query)):
        candidates.append(_candidate("asin", asin, 0.96, domain=domain, source="query_regex", reason="Matched 10-character ASIN pattern."))
    for code in _unique(UPC_EAN_RE.findall(query)):
        candidates.append(_candidate("code", code, 0.82, domain=domain, source="query_regex", reason="Matched 12-14 digit UPC/EAN/ISBN-like code."))
    for seller in _unique(match.upper() for match in SELLER_RE.findall(query)):
        candidates.append(_candidate("seller", seller, 0.74, domain=domain, source="query_regex", reason="Matched Amazon seller-like identifier."))

    category_ids = _category_ids(query)
    for category_id in category_ids:
        candidates.append(_candidate("category", category_id, 0.78, domain=domain, source="query_regex", reason="Matched numeric category id."))

    candidates.extend(_fixture_candidates(query, root=root, domain=domain))
    candidates.extend(_evidence_candidates(query, root=root))

    if query and not candidates:
        candidates.append(_candidate("keyword", query, 0.55, domain=domain, source="fallback", reason="No stable id detected; treat input as keyword/category search term."))

    if hint_type:
        candidates = _rank_with_hint(candidates, hint_type)
    else:
        candidates = sorted(candidates, key=lambda item: item["score"], reverse=True)

    primary = candidates[0] if candidates else None
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "view": "research_target_resolution",
        "query": query,
        "domain": domain,
        "hint_type": hint_type or None,
        "primary": primary,
        "candidates": candidates,
        "next_actions": _target_next_actions(primary),
        "data_quality": {
            "present": ["query"] if query else [],
            "missing": [] if query else ["query"],
            "notes": ["resolution is local-only and does not call Keepa"],
        },
        "provenance": {"source": "local://keepa_cli.research_context.resolve_research_target"},
    }


def query_research_context(params: Mapping[str, Any], *, repo_root: Path | str | None = None) -> dict[str, Any]:
    root = _repo_root(repo_root)
    target = params.get("target")
    if not isinstance(target, Mapping):
        resolved = resolve_research_target(params, repo_root=root)
        target = resolved.get("primary") or {}
    target_type = str(params.get("target_type") or target.get("type") or "").strip()
    target_id = str(params.get("target_id") or target.get("id") or params.get("query") or "").strip()
    question = str(params.get("question") or params.get("query") or "").strip()

    resources: list[dict[str, Any]] = []
    resources.extend(_context_resources_for_target(target_type, target_id, root=root))
    resources.extend(_context_resources_for_question(question, root=root))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for resource in resources:
        key = str(resource.get("uri") or resource.get("path") or resource)
        if key not in seen:
            seen.add(key)
            deduped.append(resource)

    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "view": "research_context_query",
        "target": {"type": target_type or None, "id": target_id or None},
        "question": question or None,
        "resources": deduped,
        "recommended_read_order": [item["uri"] for item in deduped if item.get("uri")][:8],
        "notes": [
            "query_research_context is local-only and does not call Keepa",
            "use resources/read for URI entries before requesting live Keepa data",
        ],
        "provenance": {"source": "local://keepa_cli.research_context.query_research_context"},
    }


def _roots(root: Path) -> dict[str, Any]:
    return {
        "repo_root": str(root),
        "read_roots": [str(root), str(Path(os.getenv("TEMP", str(root))).resolve())],
        "write_roots": [
            str((root / "evidence").resolve()),
            str((root / "tests" / "fixtures").resolve()),
            str((root / "keepa_cli" / "fixtures").resolve()),
        ],
        "never_commit": [
            "evidence/runtime-logs/",
            ".venv/",
            "__pycache__/",
            ".pytest_cache/",
        ],
    }


def _candidate(target_type: str, target_id: str, score: float, *, domain: str | None = None, source: str, reason: str, uri: str | None = None) -> dict[str, Any]:
    candidate = {
        "type": target_type,
        "id": target_id,
        "score": score,
        "source": source,
        "reason": reason,
    }
    if domain:
        candidate["domain"] = domain
    if uri:
        candidate["resource_uri"] = uri
    return candidate


def _target_next_actions(primary: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not primary:
        return []
    target_type = primary.get("type")
    target_id = primary.get("id")
    domain = primary.get("domain", "US")
    if target_type == "asin":
        return [{"tool": "keepa.products_get", "params": {"asin": target_id, "domain": domain, "view": "summary", "agent_view": True}}]
    if target_type == "category":
        return [{"tool": "keepa.categories_finder_selection", "params": {"category": target_id, "domain": domain}}]
    if target_type == "seller":
        return [{"tool": "keepa.sellers_get", "params": {"seller": target_id, "domain": domain, "dry_run": True}}]
    if target_type == "keyword":
        return [{"tool": "keepa.categories_search", "params": {"term": target_id, "domain": domain}}]
    if target_type == "fixture":
        return [{"tool": "keepa.query_research_context", "params": {"target": dict(primary)}}]
    return []


def _fixture_candidates(query: str, *, root: Path, domain: str) -> list[dict[str, Any]]:
    needle = query.lower()
    if not needle:
        return []
    results: list[dict[str, Any]] = []
    for base in (root / "keepa_cli" / "fixtures", root / "tests" / "fixtures"):
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json"))[:300]:
            name = path.name.lower()
            if needle in name or any(asin.lower() in name for asin in ASIN_RE.findall(query)):
                logical = path.relative_to(root).as_posix()
                score = 0.9 if any(asin.lower() in name for asin in ASIN_RE.findall(query)) else 0.68
                results.append(_candidate("fixture", logical, score, domain=domain, source="fixture_name", reason="Matched local sanitized fixture filename.", uri=f"keepa://fixtures/{path.name}"))
    return results[:10]


def _evidence_candidates(query: str, *, root: Path) -> list[dict[str, Any]]:
    manifest = root / "evidence" / "manifest.csv"
    if not manifest.exists() or not query:
        return []
    needle = query.lower()
    results: list[dict[str, Any]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines()[-80:]:
        if needle in line.lower():
            logical_path = line.split(",", 1)[0].strip()
            uri = "keepa://evidence/" + _base64url(logical_path)
            results.append(_candidate("evidence", logical_path, 0.62, source="evidence_manifest", reason="Matched evidence manifest line.", uri=uri))
    return results[:8]


def _context_resources_for_target(target_type: str, target_id: str, *, root: Path) -> list[dict[str, Any]]:
    if not target_id:
        return _base_context_resources()
    if target_type == "asin":
        return [{"uri": f"keepa://asin/{target_id}/fixture", "kind": "fixture_candidates"}, *_base_context_resources()]
    if target_type == "fixture":
        return [{"uri": f"keepa://fixtures/{Path(target_id).name}", "kind": "fixture"}, *_base_context_resources()]
    if target_type == "evidence":
        return [{"uri": "keepa://evidence/" + _base64url(target_id), "kind": "evidence"}, *_base_context_resources()]
    return _base_context_resources()


def _context_resources_for_question(question: str, *, root: Path) -> list[dict[str, Any]]:
    lowered = question.lower()
    resources: list[dict[str, Any]] = []
    if "schema" in lowered or "agent" in lowered:
        resources.append({"uri": "keepa://schema/products-agent-view", "kind": "schema"})
    if "risk" in lowered or "taxonomy" in lowered or "风险" in lowered:
        resources.append({"uri": "keepa://schema/risk-taxonomy", "kind": "schema"})
    if "workflow" in lowered or "runtime" in lowered:
        resources.append({"uri": "keepa://workflow/runtime-contract", "kind": "workflow_runtime_contract"})
        resources.append({"uri": "keepa://schema/workflow-runtime-contract", "kind": "schema"})
    if "tool" in lowered or "mcp" in lowered:
        resources.append({"uri": "keepa://tools/index", "kind": "tools_index"})
    if "prompt" in lowered:
        resources.append({"uri": "keepa://prompts/index", "kind": "prompts_index"})
    if "evidence" in lowered or "recent" in lowered:
        resources.append({"uri": "keepa://evidence/recent", "kind": "evidence"})
    return resources


def _base_context_resources() -> list[dict[str, str]]:
    return [
        {"uri": "keepa://context/policy", "kind": "policy"},
        {"uri": "keepa://tools/index", "kind": "tools_index"},
        {"uri": "keepa://evidence/recent", "kind": "evidence"},
    ]


def _rank_with_hint(candidates: list[dict[str, Any]], hint_type: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        if item.get("type") == hint_type:
            item["score"] = min(1.0, float(item["score"]) + 0.12)
            item["hint_matched"] = True
        ranked.append(item)
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def _category_ids(query: str) -> list[str]:
    if not re.search(r"category|类目|browse|node", query, re.IGNORECASE):
        return []
    return _unique(re.findall(r"\b\d{4,12}\b", query))


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        key = text.lower()
        if key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _repo_root(repo_root: Path | str | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    return Path(__file__).resolve().parents[1]


def _base64url(value: str) -> str:
    import base64

    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
