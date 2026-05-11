"""
keepa_cli/agent/resources.py
文件说明：定义 MCP resources 与大响应 chunk resource manifest。
主要职责：把 schema、fixture manifest、evidence 与本地 chunk 文件暴露为按需读取的 MCP resource。
依赖边界：只读本地文本文件，不访问 Keepa API，不读取明文凭据。
"""

from __future__ import annotations

import base64
import copy
import csv
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli import __version__
from keepa_cli.agent.cache_keys import build_cache_key
from keepa_cli.agent.prompts import get_mcp_prompt, list_mcp_prompts, prompt_names
from keepa_cli.agent.tools import get_tool_definition, list_mcp_tools, resolve_toolset_groups, toolset_names, workflow_runtime_contract
from keepa_cli.figures import build_research_figures_from_payload
from keepa_cli.research_brief import brief_graph_resource_payload, brief_resource_payload
from keepa_cli.research_context import build_context_policy
from keepa_cli.research_graph import extract_research_graphs, graph_summary


RESOURCE_SCHEMA_VERSION = "2026-05-10.6"
MAX_RESOURCE_TEXT_BYTES = 1_000_000


STATIC_RESOURCES: tuple[dict[str, str], ...] = (
    {
        "uri": "keepa://schema/products-agent-view",
        "name": "products.agent-view.schema",
        "description": "Generated JSON schema for the product Agent view contract.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://schema/workflow-runtime-contract",
        "name": "workflow-runtime-contract.schema",
        "description": "JSON schema for the MCP workflow runtime contract resource.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://schema/risk-taxonomy",
        "name": "risk-taxonomy.schema",
        "description": "JSON schema for the stable Agent risk taxonomy enum and evidence-bearing risk items.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://fixtures/manifest",
        "name": "fixture-and-evidence-manifest",
        "description": "Current evidence manifest with fixture and task-log entries.",
        "mimeType": "text/csv",
    },
    {
        "uri": "keepa://guides/cassette-promotion",
        "name": "cassette-promotion-guide",
        "description": "Offline-first workflow for sanitizing live Keepa responses into regression fixtures.",
        "mimeType": "text/markdown",
    },
    {
        "uri": "keepa://evidence/recent",
        "name": "recent-evidence",
        "description": "Recent task evidence entries summarized from evidence/manifest.csv.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://context/policy",
        "name": "context-policy",
        "description": "Offline-first Agent policy, allowed roots, tool gating hints, and live Keepa safety status.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://tools/index",
        "name": "mcp-tools-index",
        "description": "Compact MCP toolset and tool schema index for Agent discovery without loading every tool schema.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://workflow/runtime-contract",
        "name": "workflow-runtime-contract",
        "description": "MCP tools/call runtime argument contract for resource_uri, artifacts, workflow_inputs, and missing_inputs handling.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://prompts/index",
        "name": "mcp-prompts-index",
        "description": "MCP prompt catalog for product research, category research, deal comparison, and project onboarding.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://zread/wiki/current",
        "name": "zread-current-wiki",
        "description": "Current committed zread wiki version and public documentation links.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://zread/wiki/toc",
        "name": "zread-wiki-toc",
        "description": "Current zread wiki table of contents from .zread/wiki.",
        "mimeType": "application/json",
    },
    {
        "uri": "keepa://zread/wiki/pages",
        "name": "zread-wiki-pages",
        "description": "Compact zread wiki page catalog with resource URIs for each page.",
        "mimeType": "application/json",
    },
)


RESOURCE_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "uriTemplate": "keepa://schema/{name}",
        "name": "schema-by-name",
        "description": "Read a generated schema by stable name. Supports products-agent-view, workflow-runtime-contract, and risk-taxonomy.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://fixtures/{name}",
        "name": "fixture-by-name",
        "description": "Read a sanitized JSON fixture by file name from keepa_cli/fixtures or tests/fixtures.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://cache-key/{command}/{encoded_params}",
        "name": "session-cache-key-preview",
        "description": "Preview the deterministic AgentSession cache key for a service command and base64url JSON params.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://workflow/{encoded_params}/policy",
        "name": "workflow-policy-preview",
        "description": "Read workflow.plan policy for base64url JSON params without loading the full plan.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://research/{cache_key}",
        "name": "session-research-by-cache-key",
        "description": "Audit a cached AgentSession result by cache key, including graph summary, evidence index, provenance, and ledger.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://research/{cache_key}/brief",
        "name": "session-research-brief-by-cache-key",
        "description": "Read a cached research_brief.export result by cache key.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://research/{cache_key}/graph",
        "name": "session-research-brief-graph-by-cache-key",
        "description": "Read graph summary from a cached research_brief.export result by cache key.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://research/{cache_key}/figures",
        "name": "session-research-figures-by-cache-key",
        "description": "Generate or read local SVG figure resources for a cached AgentSession result by cache key.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://research/{cache_key}/figures/{figure_set}",
        "name": "session-research-figure-set-by-cache-key",
        "description": "Generate only one SVG figure group for a cached AgentSession result. figure_set is all, history, compare, or audit.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://graphs/{root}",
        "name": "research-graph-by-root",
        "description": "Find research_graph payloads by root id in the live AgentSession cache and local fixtures.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://toolsets/{toolset}",
        "name": "mcp-toolset-by-name",
        "description": "Read a compact MCP toolset manifest by name, including tool resource URIs and command mappings.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://tools/{name}",
        "name": "mcp-tool-schema-by-name",
        "description": "Read one MCP tool schema by name without listing every tool.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://prompts/{name}",
        "name": "mcp-prompt-by-name",
        "description": "Read one MCP prompt definition or no-argument rendered prompt by name.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://asin/{asin}/fixture",
        "name": "asin-fixture-candidates",
        "description": "List local fixture files whose names contain an ASIN.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://evidence/{encoded_logical_path}",
        "name": "evidence-by-logical-path",
        "description": "Read an evidence task log by base64url encoded logical_path from evidence/manifest.csv.",
        "mimeType": "text/markdown",
    },
    {
        "uriTemplate": "keepa://chunk/{encoded_path}",
        "name": "chunk-file-by-encoded-path",
        "description": "Read a chunk file referenced by an MCP resource manifest.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://output/{encoded_path}",
        "name": "output-file-by-encoded-path",
        "description": "Read a local output file referenced by an MCP resource manifest.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://zread/wiki/page/{slug_or_file}",
        "name": "zread-wiki-page",
        "description": "Read a committed zread wiki markdown page by slug, title slug, or markdown file name.",
        "mimeType": "text/markdown",
    },
)


def list_mcp_resources() -> list[dict[str, str]]:
    return [dict(resource) for resource in STATIC_RESOURCES]


def list_mcp_resource_templates() -> list[dict[str, str]]:
    return [dict(template) for template in RESOURCE_TEMPLATES]


def read_mcp_resource(
    uri: str,
    *,
    root: Path | str | None = None,
    session_cache: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    repo_root = Path(root).resolve() if root is not None else _default_repo_root()
    if uri == "keepa://schema/products-agent-view":
        return _read_text_resource(uri, repo_root / "docs/schema/products.agent-view.schema.json", "application/json")
    if uri == "keepa://schema/workflow-runtime-contract":
        return _read_text_resource(uri, repo_root / "docs/schema/workflow-runtime-contract.schema.json", "application/json")
    if uri == "keepa://schema/risk-taxonomy":
        return _read_text_resource(uri, repo_root / "docs/schema/risk-taxonomy.schema.json", "application/json")
    if uri == "keepa://fixtures/manifest":
        return _read_text_resource(uri, repo_root / "evidence/manifest.csv", "text/csv")
    if uri == "keepa://guides/cassette-promotion":
        return {"uri": uri, "mimeType": "text/markdown", "text": _cassette_promotion_guide()}
    if uri == "keepa://evidence/recent":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_recent_evidence(repo_root), ensure_ascii=False, indent=2)}
    if uri == "keepa://context/policy":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(build_context_policy(repo_root=repo_root), ensure_ascii=False, indent=2)}
    if uri == "keepa://tools/index":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_tools_index(), ensure_ascii=False, indent=2)}
    if uri == "keepa://workflow/runtime-contract":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(workflow_runtime_contract(), ensure_ascii=False, indent=2)}
    if uri == "keepa://prompts/index":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_prompts_index(), ensure_ascii=False, indent=2)}
    if uri == "keepa://zread/wiki/current":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_zread_current(repo_root), ensure_ascii=False, indent=2)}
    if uri == "keepa://zread/wiki/toc":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_zread_toc(repo_root), ensure_ascii=False, indent=2)}
    if uri == "keepa://zread/wiki/pages":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_zread_pages(repo_root), ensure_ascii=False, indent=2)}
    if uri.startswith("keepa://zread/wiki/page/"):
        return _read_zread_page_resource(uri, repo_root=repo_root)
    if uri.startswith("keepa://cache-key/"):
        return _read_cache_key_resource(uri)
    if uri.startswith("keepa://workflow/"):
        return _read_workflow_policy_resource(uri)
    if uri.startswith("keepa://research/"):
        return _read_research_cache_resource(uri, session_cache=session_cache)
    if uri.startswith("keepa://graphs/"):
        return _read_graph_root_resource(uri, repo_root=repo_root, session_cache=session_cache)
    if uri.startswith("keepa://toolsets/"):
        return _read_toolset_resource(uri)
    if uri.startswith("keepa://tools/"):
        return _read_tool_resource(uri)
    if uri.startswith("keepa://prompts/"):
        return _read_prompt_resource(uri)
    if uri.startswith("keepa://asin/"):
        return _read_asin_fixture_resource(uri, repo_root=repo_root)
    if uri.startswith("keepa://evidence/"):
        return _read_evidence_resource(uri, repo_root=repo_root)
    if uri.startswith("keepa://chunk/"):
        return _read_path_resource(uri, repo_root=repo_root, kind="chunk")
    if uri.startswith("keepa://output/"):
        return _read_path_resource(uri, repo_root=repo_root, kind="output")
    if uri.startswith("keepa://schema/"):
        return _read_named_schema_resource(uri, repo_root=repo_root)
    if uri.startswith("keepa://fixtures/"):
        return _read_fixture_resource(uri, repo_root=repo_root)
    raise ValueError(f"unknown MCP resource uri: {uri}")


def build_resource_manifest(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    resources: list[dict[str, Any]] = []
    _collect_file_resources(payload, resources, path_stack=[])
    deduped: dict[str, dict[str, Any]] = {}
    for resource in resources:
        path = str(resource.get("path") or "")
        if path:
            deduped[path] = resource
    if not deduped:
        return None
    ordered = sorted(deduped.values(), key=lambda item: (str(item.get("type") or ""), str(item.get("name") or ""), str(item.get("path") or "")))
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "strategy": "summary_with_resource_refs",
        "resource_count": len(ordered),
        "resources": ordered,
    }


def compact_payload_for_mcp(payload: Mapping[str, Any]) -> dict[str, Any]:
    manifest = build_resource_manifest(payload)
    if manifest is None:
        return copy.deepcopy(dict(payload))
    compact = copy.deepcopy(dict(payload))
    compact["mcp_resource_manifest"] = manifest
    data = compact.get("data")
    if isinstance(data, Mapping):
        compact["data"] = _compact_data_for_mcp(data)
    return compact


def path_to_resource_uri(path: Path | str, *, kind: str = "chunk") -> str:
    resolved = str(Path(path).resolve())
    token = _base64url_encode(resolved)
    return f"keepa://{kind}/{token}"


def text_to_resource_token(value: str) -> str:
    return _base64url_encode(value)


def _read_text_resource(uri: str, path: Path, mime_type: str) -> dict[str, str]:
    return {"uri": uri, "mimeType": mime_type, "text": _read_text_limited(path)}


def _read_path_resource(uri: str, *, repo_root: Path, kind: str) -> dict[str, str]:
    path = _path_from_resource_uri(uri, kind=kind)
    resolved = path.resolve()
    allowed_roots = [repo_root, Path(tempfile.gettempdir()).resolve()]
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise ValueError(f"resource path is outside allowed roots: {resolved}")
    return {"uri": uri, "mimeType": _mime_type(resolved), "text": _read_text_limited(resolved)}


def _read_named_schema_resource(uri: str, *, repo_root: Path) -> dict[str, str]:
    name = uri.removeprefix("keepa://schema/").strip()
    if name in {"products-agent-view", "products.agent-view.schema", "products.agent-view.schema.json"}:
        return _read_text_resource(uri, repo_root / "docs/schema/products.agent-view.schema.json", "application/json")
    if name in {"workflow-runtime-contract", "workflow-runtime-contract.schema", "workflow-runtime-contract.schema.json"}:
        return _read_text_resource(uri, repo_root / "docs/schema/workflow-runtime-contract.schema.json", "application/json")
    if name in {"risk-taxonomy", "risk-taxonomy.schema", "risk-taxonomy.schema.json"}:
        return _read_text_resource(uri, repo_root / "docs/schema/risk-taxonomy.schema.json", "application/json")
    raise ValueError(f"unknown schema resource name: {name}")


def _read_fixture_resource(uri: str, *, repo_root: Path) -> dict[str, str]:
    name = uri.removeprefix("keepa://fixtures/").strip()
    if name in {"", "manifest"}:
        return _read_text_resource(uri, repo_root / "evidence/manifest.csv", "text/csv")
    filename = Path(name).name
    if filename != name or not filename.endswith(".json"):
        raise ValueError(f"fixture resource must be a JSON fixture file name: {name}")
    for base in (repo_root / "keepa_cli/fixtures", repo_root / "tests/fixtures"):
        candidate = (base / filename).resolve()
        if _is_relative_to(candidate, base.resolve()) and candidate.exists():
            return _read_text_resource(uri, candidate, "application/json")
    raise ValueError(f"fixture resource not found: {filename}")


def _read_cache_key_resource(uri: str) -> dict[str, str]:
    rest = uri.removeprefix("keepa://cache-key/")
    command, separator, token = rest.partition("/")
    if not separator or not command:
        raise ValueError("cache-key resource requires keepa://cache-key/{command}/{encoded_params}")
    params = json.loads(_base64url_decode(token))
    if not isinstance(params, Mapping):
        raise ValueError("cache-key encoded params must decode to a JSON object")
    payload = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "command": command,
        "params": dict(params),
        "cache_key": build_cache_key(command, params),
        "note": "Preview only; resources/read does not inspect live AgentSession memory.",
    }
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _read_workflow_policy_resource(uri: str) -> dict[str, str]:
    rest = uri.removeprefix("keepa://workflow/")
    token, separator, suffix = rest.partition("/")
    if not token or separator != "/" or suffix != "policy":
        raise ValueError("workflow policy resource requires keepa://workflow/{encoded_params}/policy")
    params = json.loads(_base64url_decode(token))
    if not isinstance(params, Mapping):
        raise ValueError("workflow policy encoded params must decode to a JSON object")

    from keepa_cli.service import run_command

    envelope = run_command("workflow.plan", dict(params), env={})
    if not envelope.get("ok"):
        raise ValueError(str(envelope.get("error", {}).get("message") or "workflow.plan failed"))
    data = envelope.get("data") or {}
    if not isinstance(data, Mapping):
        raise ValueError("workflow.plan did not return a data object")
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    payload = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "view": "workflow_policy_resource",
        "command": "workflow.plan",
        "params": dict(params),
        "workflow_inputs": data.get("workflow_inputs") or {},
        "artifacts": data.get("artifacts") or {},
        "resource_templates": data.get("resource_templates") or [],
        "workflow_policy": data.get("workflow_policy") or {},
        "totals": data.get("totals") or {},
        "step_summary": [
            {
                "id": step.get("id"),
                "tool": step.get("tool"),
                "mcp_tool": step.get("mcp_tool"),
                "profile": (step.get("mcp") or {}).get("profile") if isinstance(step.get("mcp"), Mapping) else None,
                "requires_confirmation": step.get("requires_confirmation"),
                "estimated_tokens": step.get("estimated_tokens"),
                "input_refs": step.get("input_refs") or [],
                "artifact_refs": step.get("artifact_refs") or [],
            }
            for step in steps
            if isinstance(step, Mapping)
        ],
        "recommended_read_order": ["workflow_inputs", "artifacts", "resource_templates", "workflow_policy", "step_summary", "totals"],
    }
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _read_research_cache_resource(
    uri: str,
    *,
    session_cache: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, str]:
    token = uri.removeprefix("keepa://research/").strip()
    if token.endswith("/brief"):
        cache_key = _decode_resource_identifier(token.removesuffix("/brief"))
        cached = session_cache.get(cache_key) if session_cache is not None else None
        payload = brief_resource_payload(cache_key, cached)
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    if token.endswith("/graph"):
        cache_key = _decode_resource_identifier(token.removesuffix("/graph"))
        cached = session_cache.get(cache_key) if session_cache is not None else None
        payload = brief_graph_resource_payload(cache_key, cached)
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    if "/figures/" in token:
        cache_token, figure_set = token.rsplit("/figures/", 1)
        cache_key = _decode_resource_identifier(cache_token)
        payload = _research_figures_resource_payload(cache_key, figure_set=figure_set, session_cache=session_cache)
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    if token.endswith("/figures"):
        cache_key = _decode_resource_identifier(token.removesuffix("/figures"))
        payload = _research_figures_resource_payload(cache_key, figure_set="all", session_cache=session_cache)
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    cache_key = _decode_resource_identifier(token)
    payload = _research_cache_payload(cache_key, session_cache=session_cache)
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _research_cache_payload(
    cache_key: str,
    *,
    session_cache: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    cached = session_cache.get(cache_key) if session_cache is not None else None
    payload: dict[str, Any] = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "cache_key": cache_key,
        "found": isinstance(cached, Mapping),
        "source": "agent_session",
        "note": "Session resources are process-local; repeat resources/read in the same MCP session that produced the cache_key.",
    }
    if not isinstance(cached, Mapping):
        payload["available_cache_keys"] = sorted(session_cache.keys()) if session_cache is not None else []
        return payload

    data = cached.get("data") if isinstance(cached.get("data"), Mapping) else {}
    graphs = extract_research_graphs(cached)
    payload.update(
        {
            "ok": bool(cached.get("ok")),
            "command": cached.get("command"),
            "cache_hit": cached.get("cache_hit", False),
            "budget_ledger": copy.deepcopy(cached.get("budget_ledger", {})),
            "agent_brief": copy.deepcopy(data.get("agent_brief")) if isinstance(data, Mapping) else None,
            "data_quality": copy.deepcopy(data.get("data_quality")) if isinstance(data, Mapping) else None,
            "evidence_index": copy.deepcopy(data.get("evidence_index")) if isinstance(data, Mapping) else None,
            "provenance": copy.deepcopy(data.get("provenance")) if isinstance(data, Mapping) else None,
            "research_graph_count": len(graphs),
            "research_graphs": [_graph_audit_item(graph, source="session_cache", source_ref=cache_key) for graph in graphs],
        }
    )
    return payload


def _research_figures_resource_payload(
    cache_key: str,
    *,
    figure_set: str,
    session_cache: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    cached = session_cache.get(cache_key) if session_cache is not None else None
    payload: dict[str, Any] = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "cache_key": cache_key,
        "found": isinstance(cached, Mapping),
        "source": "agent_session",
        "note": "Figure resources are generated locally from the same-session cached structured result; no Keepa request is made.",
    }
    if not isinstance(cached, Mapping):
        payload["available_cache_keys"] = sorted(session_cache.keys()) if session_cache is not None else []
        return payload

    output_dir = Path(tempfile.gettempdir()) / "keepa-mcp-figures" / _safe_cache_dir_name(cache_key)
    figure_result = build_research_figures_from_payload(
        cached,
        out_dir=str(output_dir),
        title=f"Keepa Research {cache_key.split(':', 1)[0]}",
        source_label=f"agent-session-cache:{cache_key}",
        figure_set=figure_set,
    )
    manifest = build_resource_manifest({"data": figure_result}) or {"resources": []}
    payload.update(
        {
            "ok": True,
            "command": cached.get("command"),
            "figure_result": figure_result,
            "mcp_resource_manifest": manifest,
            "svg_resources": [
                resource
                for resource in manifest.get("resources", [])
                if isinstance(resource, Mapping) and resource.get("mimeType") == "image/svg+xml"
            ],
            "source_data_resources": [
                resource
                for resource in manifest.get("resources", [])
                if isinstance(resource, Mapping) and str(resource.get("path") or "").endswith(".source.json")
            ],
        }
    )
    return payload


def _safe_cache_dir_name(cache_key: str) -> str:
    token = _base64url_encode(cache_key)
    return token[:96]


def _read_graph_root_resource(
    uri: str,
    *,
    repo_root: Path,
    session_cache: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, str]:
    token = uri.removeprefix("keepa://graphs/").strip()
    root_id = _decode_resource_identifier(token)
    matches: list[dict[str, Any]] = []
    if session_cache is not None:
        for cache_key, cached in sorted(session_cache.items()):
            if isinstance(cached, Mapping):
                matches.extend(
                    _matching_graph_items(
                        cached,
                        root_id=root_id,
                        source="session_cache",
                        source_ref=cache_key,
                        resource_uri=f"keepa://research/{_base64url_encode(cache_key)}",
                    )
                )
    for path in _graph_fixture_paths(repo_root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        matches.extend(
            _matching_graph_items(
                payload,
                root_id=root_id,
                source="fixture",
                source_ref=str(path),
                resource_uri=f"keepa://fixtures/{path.name}",
            )
        )

    payload = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "root": root_id,
        "match_count": len(matches),
        "matches": matches,
        "sources_scanned": {
            "session_cache_keys": len(session_cache or {}),
            "fixture_files": len(_graph_fixture_paths(repo_root)),
        },
    }
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _matching_graph_items(
    value: Any,
    *,
    root_id: str,
    source: str,
    source_ref: str,
    resource_uri: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for graph in extract_research_graphs(value):
        if str(graph.get("root") or "") != root_id:
            continue
        matches.append(_graph_audit_item(graph, source=source, source_ref=source_ref, resource_uri=resource_uri))
    return matches


def _graph_audit_item(
    graph: Mapping[str, Any],
    *,
    source: str,
    source_ref: str,
    resource_uri: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "root": graph.get("root"),
        "source": source,
        "source_ref": source_ref,
        "summary": graph_summary(graph),
        "entity_counts": copy.deepcopy(graph.get("entity_counts", {})),
        "node_count": graph.get("node_count", 0),
        "edge_count": graph.get("edge_count", 0),
    }
    if resource_uri:
        item["resource_uri"] = resource_uri
    diagnostics = graph.get("diagnostics")
    if isinstance(diagnostics, Mapping):
        item["diagnostics"] = {
            "duplicate_node_count": diagnostics.get("duplicate_node_count", 0),
            "orphan_node_count": diagnostics.get("orphan_node_count", 0),
            "conflict_count": diagnostics.get("conflict_count", 0),
            "highest_source_weight": diagnostics.get("highest_source_weight", 0),
        }
    sources = graph.get("sources")
    if isinstance(sources, list):
        item["graph_sources"] = copy.deepcopy(sources[:10])
    return item


def _graph_fixture_paths(repo_root: Path) -> list[Path]:
    paths: dict[str, Path] = {}
    for base in (repo_root / "keepa_cli/fixtures", repo_root / "tests/fixtures"):
        if not base.exists():
            continue
        for path in base.glob("*.json"):
            if "agent_eval" in path.name or "graph" in path.name or "seller" in path.name or "category" in path.name:
                paths[str(path.resolve())] = path
    return sorted(paths.values(), key=lambda item: str(item))


def _tools_index() -> dict[str, Any]:
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "default_toolset": "research",
        "toolsets": [
            {
                "name": name,
                "resource_uri": f"keepa://toolsets/{name}",
                "description": "Use all only for debugging schema discovery." if name == "all" else f"Read the {name} MCP toolset manifest.",
            }
            for name in toolset_names()
        ],
        "tools": [
            {
                "name": tool["name"],
                "description": tool.get("description"),
                "service_command": (tool.get("x-keepa") or {}).get("service_command"),
                "groups": (tool.get("x-keepa") or {}).get("groups", []),
                "workflow_runtime": bool((tool.get("x-keepa") or {}).get("workflow_runtime")),
                "resource_uri": f"keepa://tools/{tool['name']}",
            }
            for tool in list_mcp_tools(toolsets="all")
        ],
        "workflow_runtime_contract_uri": "keepa://workflow/runtime-contract",
    }


def _read_toolset_resource(uri: str) -> dict[str, str]:
    name = uri.removeprefix("keepa://toolsets/").strip()
    if not name:
        raise ValueError("toolset resource requires keepa://toolsets/{toolset}")
    groups = resolve_toolset_groups(name)
    tools = list_mcp_tools(groups=groups, toolsets="all" if name == "all" else None)
    payload = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "toolset": name,
        "available_toolsets": toolset_names(),
        "tool_count": len(tools),
        "tools": [
            {
                "name": tool["name"],
                "description": tool.get("description"),
                "service_command": (tool.get("x-keepa") or {}).get("service_command"),
                "groups": (tool.get("x-keepa") or {}).get("groups", []),
                "workflow_runtime": bool((tool.get("x-keepa") or {}).get("workflow_runtime")),
                "resource_uri": f"keepa://tools/{tool['name']}",
            }
            for tool in tools
        ],
        "workflow_runtime_contract_uri": "keepa://workflow/runtime-contract",
    }
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _read_tool_resource(uri: str) -> dict[str, str]:
    name = uri.removeprefix("keepa://tools/").strip()
    tool = get_tool_definition(name)
    if tool is None:
        raise ValueError(f"unknown MCP tool resource: {name}")
    payload = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "tool": tool.to_mcp_tool(),
        "execution": {
            "transport": "mcp tools/call",
            "service_command": tool.command,
            "argument_mode": "structured_json",
            "cli_string_is_display_only": True,
            "workflow_runtime": tool.workflow_runtime,
            "workflow_runtime_contract_uri": "keepa://workflow/runtime-contract" if tool.workflow_runtime else None,
        },
    }
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _prompts_index() -> dict[str, Any]:
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "prompt_count": len(prompt_names()),
        "prompts": [
            {
                **prompt,
                "resource_uri": f"keepa://prompts/{prompt['name']}",
            }
            for prompt in list_mcp_prompts()
        ],
    }


def _read_prompt_resource(uri: str) -> dict[str, str]:
    name = uri.removeprefix("keepa://prompts/").strip()
    if not name:
        raise ValueError("prompt resource requires keepa://prompts/{name}")
    prompt_definition = next((prompt for prompt in list_mcp_prompts() if prompt.get("name") == name), None)
    if prompt_definition is None:
        raise ValueError(f"unknown MCP prompt resource: {name}")
    required = [argument["name"] for argument in prompt_definition.get("arguments", []) if argument.get("required")]
    payload = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "name": name,
        "definition": prompt_definition,
        "required_arguments": required,
        "rendered_prompt": None if required else get_mcp_prompt(name, {}),
        "note": "Prompts with required arguments should be called through prompts/get with arguments.",
    }
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _read_asin_fixture_resource(uri: str, *, repo_root: Path) -> dict[str, str]:
    rest = uri.removeprefix("keepa://asin/")
    asin, separator, suffix = rest.partition("/")
    if not separator or suffix != "fixture" or not asin.strip():
        raise ValueError("asin fixture resource requires keepa://asin/{asin}/fixture")
    normalized = asin.strip().upper()
    matches: list[dict[str, Any]] = []
    for base_name, base in (("package", repo_root / "keepa_cli/fixtures"), ("tests", repo_root / "tests/fixtures")):
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            if normalized in path.name.upper():
                matches.append({"name": path.name, "location": base_name, "path": str(path), "uri": f"keepa://fixtures/{path.name}"})
    payload = {"schema_version": RESOURCE_SCHEMA_VERSION, "asin": normalized, "match_count": len(matches), "fixtures": matches}
    return {"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}


def _read_evidence_resource(uri: str, *, repo_root: Path) -> dict[str, str]:
    encoded = uri.removeprefix("keepa://evidence/").strip()
    logical_path = _base64url_decode(encoded)
    if not logical_path.startswith("evidence/tasks/") or ".." in Path(logical_path).parts:
        raise ValueError(f"unsupported evidence logical path: {logical_path}")
    manifest = repo_root / "evidence/manifest.csv"
    known_paths: set[str] = set()
    if manifest.exists():
        with manifest.open("r", encoding="utf-8", newline="") as handle:
            known_paths = {str(row.get("logical_path") or "") for row in csv.DictReader(handle)}
    if logical_path not in known_paths:
        raise ValueError(f"evidence logical path not found in manifest: {logical_path}")
    path = (repo_root / logical_path).resolve()
    if not _is_relative_to(path, (repo_root / "evidence/tasks").resolve()):
        raise ValueError(f"evidence path is outside evidence/tasks: {path}")
    return _read_text_resource(uri, path, _mime_type(path))


def _path_from_resource_uri(uri: str, *, kind: str) -> Path:
    prefix = f"keepa://{kind}/"
    return Path(_base64url_decode(uri[len(prefix) :]))


def _base64url_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _base64url_decode(token: str) -> str:
    padding = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")


def _decode_resource_identifier(token: str) -> str:
    if not token:
        raise ValueError("resource identifier is required")
    if token.startswith("b64:"):
        decoded = _base64url_decode(token.removeprefix("b64:"))
    else:
        decoded = token
    return decoded.strip()


def _collect_file_resources(value: Any, resources: list[dict[str, Any]], *, path_stack: list[str]) -> None:
    if isinstance(value, Mapping):
        if "path" in value and ("format" in value or "size_bytes" in value):
            path = Path(str(value["path"]))
            kind = "chunk" if "chunks" in path_stack else "output"
            resources.append(
                {
                    "uri": path_to_resource_uri(path, kind=kind),
                    "name": str(value.get("name") or value.get("section") or path.name),
                    "type": kind,
                    "path": str(path),
                    "mimeType": _mime_type(path),
                    "size_bytes": value.get("size_bytes"),
                    "asin": value.get("asin"),
                    "section": value.get("section") or value.get("name"),
                    "json_path": ".".join(path_stack),
                }
            )
        for key, item in value.items():
            _collect_file_resources(item, resources, path_stack=[*path_stack, str(key)])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_file_resources(item, resources, path_stack=[*path_stack, str(index)])


def _compact_data_for_mcp(data: Mapping[str, Any]) -> dict[str, Any]:
    keep_keys = {
        "view",
        "profile",
        "product_count",
        "chunks",
        "output",
        "summary",
        "input_graph_count",
        "sources",
        "risk_summary",
        "agent_brief",
        "data_quality",
        "selection_signals",
        "evidence_index",
        "provenance",
        "next_actions",
    }
    compact: dict[str, Any] = {key: copy.deepcopy(value) for key, value in data.items() if key in keep_keys}
    graph = data.get("research_graph") or data.get("graph")
    if isinstance(graph, Mapping):
        compact["research_graph_summary"] = graph_summary(graph)
    products = data.get("products")
    if isinstance(products, list):
        compact["products"] = [_compact_product(product) for product in products if isinstance(product, Mapping)]
    rows = data.get("rows")
    if isinstance(rows, list):
        compact["rows"] = [_compact_compare_row(row) for row in rows if isinstance(row, Mapping)]
    raw = data.get("raw")
    if isinstance(raw, Mapping) and isinstance(raw.get("output"), Mapping):
        compact["raw"] = {"output": copy.deepcopy(raw["output"])}
    return compact


def _compact_product(product: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    brief = product.get("agent_brief")
    if isinstance(brief, Mapping):
        result["agent_brief"] = {
            "one_line": brief.get("one_line"),
            "key_facts": copy.deepcopy(brief.get("key_facts", {})),
            "risk_codes": copy.deepcopy(brief.get("risk_codes", [])),
            "highest_risk_severity": brief.get("highest_risk_severity"),
            "research_graph_entities": copy.deepcopy(brief.get("research_graph_entities", {})),
            "missing_data": copy.deepcopy(brief.get("missing_data", [])),
            "recommended_next_actions": copy.deepcopy(brief.get("recommended_next_actions", [])),
        }
    for key in ("identity", "data_quality", "risk_taxonomy", "selection_signals", "next_actions"):
        if key in product:
            result[key] = copy.deepcopy(product[key])
    evidence = product.get("evidence_index")
    if isinstance(evidence, Mapping):
        result["evidence_index_summary"] = {
            "key_count": len(evidence),
            "resource_hint": "load the evidence_index chunk or structuredContent when exact evidence paths are needed",
        }
    graph = product.get("research_graph")
    if isinstance(graph, Mapping):
        result["research_graph_summary"] = graph_summary(graph)
    return result


def _compact_compare_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("asin", "title", "brand", "new_price", "buy_box_price", "sales_rank", "monthly_sold", "rating", "review_count", "risk_flags")
    result = {key: copy.deepcopy(row[key]) for key in keys if key in row}
    taxonomy = row.get("risk_taxonomy")
    if isinstance(taxonomy, Mapping):
        result["risk_taxonomy"] = {
            "codes": copy.deepcopy(taxonomy.get("codes", [])),
            "highest_severity": taxonomy.get("highest_severity"),
            "risk_count": taxonomy.get("risk_count"),
        }
    graph = row.get("research_graph")
    if isinstance(graph, Mapping):
        result["research_graph_summary"] = graph_summary(graph)
    return result


def _recent_evidence(repo_root: Path) -> dict[str, Any]:
    manifest = repo_root / "evidence/manifest.csv"
    if not manifest.exists():
        return {"schema_version": RESOURCE_SCHEMA_VERSION, "items": []}
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    recent = rows[-8:]
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "items": [
            {
                "logical_path": row.get("logical_path"),
                "title": row.get("title"),
                "status": row.get("status"),
                "updated_at": row.get("updated_at"),
                "summary": row.get("summary"),
            }
            for row in recent
        ],
    }


def _zread_current(repo_root: Path) -> dict[str, Any]:
    current_file = repo_root / ".zread/wiki/current"
    current_raw = current_file.read_text(encoding="utf-8").strip()
    version_id = current_raw.removeprefix("versions/").strip()
    toc = _zread_toc(repo_root)
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "version": version_id,
        "current_pointer": current_raw,
        "language": toc.get("language"),
        "page_count": len(toc.get("pages") or []),
        "toc_resource": "keepa://zread/wiki/toc",
        "pages_resource": "keepa://zread/wiki/pages",
        "public_url": "https://zread.ai/cuNuo/Keepa-cli",
        "github_pages_url": "https://cunuo.github.io/Keepa-cli/",
        "local_browse_command": "zread browse",
        "agent_browse_command": "zread browse --stdio",
    }


def _zread_toc(repo_root: Path) -> dict[str, Any]:
    wiki_json = _zread_wiki_json_path(repo_root)
    data = json.loads(wiki_json.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        result = dict(data)
        result.setdefault("schema_version", RESOURCE_SCHEMA_VERSION)
        result.setdefault("resource_uri", "keepa://zread/wiki/toc")
        return result
    raise ValueError(f"zread wiki.json must contain an object: {wiki_json}")


def _zread_pages(repo_root: Path) -> dict[str, Any]:
    toc = _zread_toc(repo_root)
    pages = toc.get("pages") if isinstance(toc.get("pages"), list) else []
    items: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        file_name = str(page.get("file") or "")
        slug = str(page.get("slug") or Path(file_name).stem)
        items.append(
            {
                "slug": slug,
                "title": page.get("title"),
                "file": file_name,
                "section": page.get("section"),
                "group": page.get("group"),
                "level": page.get("level"),
                "resource_uri": f"keepa://zread/wiki/page/{slug}",
                "file_resource_uri": f"keepa://zread/wiki/page/{file_name}",
            }
        )
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "version": toc.get("id"),
        "language": toc.get("language"),
        "page_count": len(items),
        "pages": items,
    }


def _read_zread_page_resource(uri: str, *, repo_root: Path) -> dict[str, str]:
    name = uri.removeprefix("keepa://zread/wiki/page/").strip()
    if not name:
        raise ValueError("zread page resource requires a slug or markdown file name")
    decoded = _base64url_decode(name.removeprefix("b64:")) if name.startswith("b64:") else name
    toc = _zread_toc(repo_root)
    pages = toc.get("pages") if isinstance(toc.get("pages"), list) else []
    target: Mapping[str, Any] | None = None
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        file_name = str(page.get("file") or "")
        slug = str(page.get("slug") or Path(file_name).stem)
        title = str(page.get("title") or "")
        candidates = {slug, file_name, Path(file_name).stem, title}
        if decoded in candidates:
            target = page
            break
    if target is None:
        raise ValueError(f"zread page not found: {decoded}")
    path = (_zread_version_dir(repo_root) / str(target.get("file"))).resolve()
    if not _is_relative_to(path, _zread_version_dir(repo_root).resolve()):
        raise ValueError(f"zread page path is outside wiki version directory: {path}")
    return _read_text_resource(uri, path, "text/markdown")


def _zread_wiki_json_path(repo_root: Path) -> Path:
    return _zread_version_dir(repo_root) / "wiki.json"


def _zread_version_dir(repo_root: Path) -> Path:
    current_file = repo_root / ".zread/wiki/current"
    current_raw = current_file.read_text(encoding="utf-8").strip()
    if not current_raw:
        raise ValueError("zread current pointer is empty")
    version_id = current_raw.removeprefix("versions/").strip()
    if "/" in version_id or "\\" in version_id or ".." in Path(version_id).parts:
        raise ValueError(f"invalid zread version pointer: {current_raw}")
    path = (repo_root / ".zread/wiki/versions" / version_id).resolve()
    if not _is_relative_to(path, (repo_root / ".zread/wiki/versions").resolve()):
        raise ValueError(f"zread version path is outside wiki versions: {path}")
    return path


def _cassette_promotion_guide() -> str:
    return f"""# Keepa Cassette Promotion

Server version: {__version__}

Offline-first workflow:

1. Run a small approved live request and write the raw response under `evidence/runtime-logs/`.
2. Promote it with `kc --json cassettes promote evidence/runtime-logs/live-response.json --name product_B0EXAMPLE_full`.
3. Commit only the sanitized fixtures under `tests/fixtures/` and `keepa_cli/fixtures/`, plus the manifest entry.
4. Never commit raw runtime logs or token-bearing request metadata.

The promote command re-runs cassette redaction, writes synchronized fixtures, and updates `evidence/manifest.csv` idempotently.
"""


def _read_text_limited(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) <= MAX_RESOURCE_TEXT_BYTES:
        return raw.decode("utf-8")
    return raw[:MAX_RESOURCE_TEXT_BYTES].decode("utf-8", errors="replace") + "\n\n[truncated by keepa MCP resource reader]\n"


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".svg":
        return "image/svg+xml"
    return "text/plain"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
