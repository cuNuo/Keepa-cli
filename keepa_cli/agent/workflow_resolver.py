"""
keepa_cli/agent/workflow_resolver.py
文件说明：解析 Agent workflow 产物引用并补齐 MCP tool 调用参数。
主要职责：把 session cache、MCP resource URI 与本地路径转换成下游命令可执行输入。
依赖边界：纯本地解析，不访问 Keepa API，不读取凭据。
"""

from __future__ import annotations

import base64
import copy
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.research_graph import extract_research_graphs


WORKFLOW_RUNTIME_KEYS = {
    "artifact",
    "artifacts",
    "resource_uri",
    "resource_uris",
    "workflow_context",
    "workflow_inputs",
}

WORKFLOW_CONTEXT_CONTAINER_KEYS = {
    "outputs",
    "previous_outputs",
    "results",
    "step_outputs",
    "steps",
}


def resolve_workflow_arguments(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    session_cache: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve workflow resource/cache/path references before schema validation."""
    params = {key: copy.deepcopy(value) for key, value in arguments.items() if key not in WORKFLOW_RUNTIME_KEYS}
    references = _collect_references(arguments)
    resolved_refs: list[dict[str, Any]] = []
    temp_paths: list[str] = []
    payloads: list[Any] = []
    graphs: list[dict[str, Any]] = []
    paths: list[str] = []
    values: dict[str, Any] = {}

    for index, reference in enumerate(references):
        ref_payload, ref_info = _resolve_reference(reference, session_cache=session_cache, index=index)
        resolved_refs.append(ref_info)
        if ref_info.get("path"):
            paths.append(str(ref_info["path"]))
        if ref_payload is not None:
            payloads.append(ref_payload)
            graphs.extend(extract_research_graphs(ref_payload))
            _merge_values(values, _derived_values(ref_payload))

    _apply_derived_params(tool_name, params, values=values, payloads=payloads, graphs=graphs, paths=paths, temp_paths=temp_paths)
    missing_inputs = _missing_inputs(tool_name, params)
    resolution = {
        "schema_version": "2026-05-11.1",
        "resolved": resolved_refs,
        "derived_values": values,
        "payload_count": len(payloads),
        "graph_count": len(graphs),
        "temp_paths": temp_paths,
        "missing_inputs": missing_inputs,
    }
    if not resolved_refs and not values and not temp_paths and not missing_inputs:
        return params, None
    return params, resolution


def workflow_runtime_argument_names() -> set[str]:
    return set(WORKFLOW_RUNTIME_KEYS)


def _collect_references(arguments: Mapping[str, Any]) -> list[Any]:
    references: list[Any] = []
    for key in ("artifact", "resource_uri"):
        value = arguments.get(key)
        if value:
            references.append(value)
    for key in ("artifacts", "resource_uris"):
        value = arguments.get(key)
        if isinstance(value, list):
            references.extend(value)
        elif value:
            references.append(value)

    workflow_inputs = arguments.get("workflow_inputs")
    if isinstance(workflow_inputs, Mapping):
        for item in workflow_inputs.values():
            if isinstance(item, Mapping):
                value = item.get("value")
                if _looks_like_reference(value):
                    references.append(value)

    workflow_context = arguments.get("workflow_context")
    if isinstance(workflow_context, Mapping):
        references.extend(_collect_workflow_context_references(workflow_context))
    return references


def _collect_workflow_context_references(value: Any) -> list[Any]:
    references: list[Any] = []
    if isinstance(value, Mapping):
        if "payload" in value or "graph" in value or _artifact_path(value):
            references.append(value)
        for key in ("artifact", "resource_uri"):
            item = value.get(key)
            if item:
                references.append(item)
        for key in ("artifacts", "resource_uris"):
            item = value.get(key)
            if isinstance(item, list):
                references.extend(item)
            elif item:
                references.append(item)
        for key in WORKFLOW_CONTEXT_CONTAINER_KEYS:
            nested = value.get(key)
            if isinstance(nested, Mapping):
                for item in nested.values():
                    references.extend(_collect_workflow_context_references(item))
            elif isinstance(nested, list):
                for item in nested:
                    references.extend(_collect_workflow_context_references(item))
    elif isinstance(value, list):
        for item in value:
            references.extend(_collect_workflow_context_references(item))
    elif _looks_like_reference(value):
        references.append(value)
    return references


def _resolve_reference(
    reference: Any,
    *,
    session_cache: Mapping[str, Mapping[str, Any]] | None,
    index: int,
) -> tuple[Any | None, dict[str, Any]]:
    if isinstance(reference, Mapping):
        if "payload" in reference:
            payload = copy.deepcopy(reference["payload"])
            return payload, {"index": index, "kind": "inline_payload", "graph_count": len(extract_research_graphs(payload))}
        if "graph" in reference:
            payload = {"research_graph": copy.deepcopy(reference["graph"])}
            return payload, {"index": index, "kind": "inline_graph", "graph_count": len(extract_research_graphs(payload))}
        artifact_path = _artifact_path(reference)
        if artifact_path:
            return _resolve_reference(artifact_path, session_cache=session_cache, index=index)
        for key in ("resource_uri", "uri", "path", "cache_key"):
            if reference.get(key):
                return _resolve_reference(reference[key], session_cache=session_cache, index=index)

    if not isinstance(reference, str):
        return None, {"index": index, "kind": "unsupported", "value_type": type(reference).__name__}

    value = reference.strip()
    if value.startswith("keepa://"):
        return _resolve_resource_uri(value, session_cache=session_cache, index=index)

    if Path(value).exists():
        return None, {"index": index, "kind": "path", "path": value}

    if session_cache is not None and value in session_cache:
        payload = copy.deepcopy(session_cache[value])
        return payload, {"index": index, "kind": "cache_key", "cache_key": value, "graph_count": len(extract_research_graphs(payload))}

    return None, {"index": index, "kind": "unresolved", "value": value}


def _resolve_resource_uri(
    uri: str,
    *,
    session_cache: Mapping[str, Mapping[str, Any]] | None,
    index: int,
) -> tuple[Any | None, dict[str, Any]]:
    if uri.startswith("keepa://research/"):
        suffix = uri.removeprefix("keepa://research/")
        cache_key = _decode_resource_identifier(suffix.removesuffix("/graph").removesuffix("/brief"))
        cached = session_cache.get(cache_key) if session_cache is not None else None
        if isinstance(cached, Mapping):
            payload = copy.deepcopy(cached)
            if suffix.endswith("/graph"):
                graphs = extract_research_graphs(payload)
                return {"research_graph": graphs}, {"index": index, "kind": "resource", "uri": uri, "cache_key": cache_key, "graph_count": len(graphs)}
            return payload, {"index": index, "kind": "resource", "uri": uri, "cache_key": cache_key, "graph_count": len(extract_research_graphs(payload))}
        return None, {"index": index, "kind": "resource", "uri": uri, "cache_key": cache_key, "found": False}

    if uri.startswith("keepa://graphs/"):
        from keepa_cli.agent.resources import read_mcp_resource

        try:
            content = read_mcp_resource(uri, session_cache=session_cache)
            payload = json.loads(content["text"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return None, {"index": index, "kind": "resource", "uri": uri, "error": str(exc)}
        matches = [match for match in payload.get("matches", []) if isinstance(match, Mapping)]
        return None, {
            "index": index,
            "kind": "graph_audit_resource",
            "uri": uri,
            "match_count": len(matches),
            "resource_uris": [str(match.get("resource_uri")) for match in matches if match.get("resource_uri")],
        }

    if uri.startswith("keepa://output/") or uri.startswith("keepa://chunk/"):
        path = _decode_path_resource(uri)
        return None, {"index": index, "kind": "resource_path", "uri": uri, "path": str(path)}

    from keepa_cli.agent.resources import read_mcp_resource

    try:
        content = read_mcp_resource(uri, session_cache=session_cache)
        payload = json.loads(content["text"]) if content.get("mimeType") == "application/json" else content.get("text")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, {"index": index, "kind": "resource", "uri": uri, "error": str(exc)}
    return payload, {"index": index, "kind": "resource", "uri": uri, "graph_count": len(extract_research_graphs(payload))}


def _apply_derived_params(
    tool_name: str,
    params: dict[str, Any],
    *,
    values: Mapping[str, Any],
    payloads: list[Any],
    graphs: list[dict[str, Any]],
    paths: list[str],
    temp_paths: list[str],
) -> None:
    if tool_name in {"keepa.categories_products", "keepa.categories_finder_selection"} and not params.get("category"):
        category = _first(values.get("category_ids"))
        if category:
            params["category"] = category

    if tool_name in {"keepa.products_compare", "keepa.products_get"} and not params.get("asin"):
        asins = list(values.get("asins") or [])
        if tool_name == "keepa.products_compare" and len(asins) >= 2:
            params["asin"] = asins[:10]
        elif tool_name == "keepa.products_get" and asins:
            params["asin"] = asins[0]

    if tool_name == "keepa.tracking_get" and not params.get("asin"):
        asin = _first(values.get("tracking_asins")) or _first(values.get("asins"))
        if asin:
            params["asin"] = asin

    if tool_name == "keepa.audit_cost":
        nested = params.get("params")
        if isinstance(nested, dict) and not nested.get("asin"):
            asin = _first(values.get("tracking_asins")) or _first(values.get("asins"))
            if asin:
                nested["asin"] = asin

    if tool_name == "keepa.research_graph_merge" and not params.get("input") and not params.get("graph"):
        if paths:
            params["input"] = paths[0] if len(paths) == 1 else paths
        elif graphs:
            params["graph"] = graphs
    if tool_name == "keepa.research_brief_export" and not params.get("input") and not params.get("payload") and not params.get("graph"):
        if paths:
            params["input"] = paths[0] if len(paths) == 1 else paths
        elif payloads:
            params["payload"] = payloads

    if tool_name in {"keepa.reports_build", "keepa.browse_snapshot", "keepa.figures_research"} and not params.get("input"):
        if paths:
            params["input"] = paths[0]
        elif graphs:
            params["input"] = _write_temp_json({"research_graph": graphs[0]}, prefix="keepa-workflow-graph-")
            temp_paths.append(params["input"])
        elif payloads:
            params["input"] = _write_temp_json(payloads[0], prefix="keepa-workflow-payload-")
            temp_paths.append(params["input"])


def _missing_inputs(tool_name: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    if tool_name in {"keepa.categories_products", "keepa.categories_finder_selection"} and not params.get("category"):
        missing.append({"field": "category", "accepts": ["artifact category_candidates", "workflow_inputs.selected_category_id", "resource_uri"]})
    if tool_name == "keepa.products_compare" and len(params.get("asin") or []) < 2:
        missing.append({"field": "asin", "accepts": ["artifact category_products.asins", "resource_uri keepa://research/{cache_key}"]})
    if tool_name == "keepa.products_get" and not params.get("asin") and not params.get("code"):
        missing.append({"field": "asin", "accepts": ["artifact category_products.asins", "workflow_inputs.asin"]})
    if tool_name == "keepa.tracking_get" and not params.get("asin"):
        missing.append({"field": "asin", "accepts": ["artifact tracking_list", "workflow_inputs.asin"]})
    if tool_name == "keepa.research_graph_merge" and not params.get("input") and not params.get("graph"):
        missing.append({"field": "graph", "accepts": ["resource_uri keepa://research/{cache_key}", "resource_uri keepa://research/{cache_key}/graph", "artifact graph", "artifact output.path"]})
    if tool_name == "keepa.research_brief_export" and not params.get("input") and not params.get("payload") and not params.get("graph"):
        missing.append({"field": "payload", "accepts": ["resource_uri keepa://research/{cache_key}", "artifact merged_graph.path", "artifact payload"]})
    if tool_name in {"keepa.reports_build", "keepa.browse_snapshot", "keepa.figures_research"} and not params.get("input"):
        missing.append({"field": "input", "accepts": ["resource_uri keepa://research/{cache_key}", "resource_uri keepa://output/{encoded_path}", "artifact merged_graph.path"]})
    return missing


def _derived_values(payload: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    _collect_asins(payload, values.setdefault("asins", []))
    _collect_category_ids(payload, values.setdefault("category_ids", []))
    _collect_tracking_asins(payload, values.setdefault("tracking_asins", []))
    return {key: _dedupe(items) for key, items in values.items() if items}


def _collect_asins(value: Any, found: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered == "asin":
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, list):
                    found.extend(str(entry) for entry in item if entry)
            elif lowered == "asins" and isinstance(item, list):
                found.extend(str(entry) for entry in item if entry)
            else:
                _collect_asins(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_asins(item, found)


def _collect_category_ids(value: Any, found: list[str]) -> None:
    if isinstance(value, Mapping):
        for key in ("category_id", "catId", "categoryId", "category"):
            item = value.get(key)
            if item is not None and str(item).strip() and str(item).strip() not in {"0", "<CATEGORY_ID>"}:
                found.append(str(item).strip())
        for item in value.values():
            _collect_category_ids(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_category_ids(item, found)


def _collect_tracking_asins(value: Any, found: list[str]) -> None:
    if isinstance(value, Mapping):
        trackings = value.get("trackings")
        if isinstance(trackings, list):
            for item in trackings:
                if isinstance(item, Mapping) and item.get("asin"):
                    found.append(str(item["asin"]))
        for item in value.values():
            _collect_tracking_asins(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_tracking_asins(item, found)


def _merge_values(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, list):
            target[key] = _dedupe([*(target.get(key) or []), *value])
        elif key not in target:
            target[key] = value


def _artifact_path(value: Mapping[str, Any]) -> str | None:
    for key in ("output", "merged_graph", "brief", "report"):
        nested = value.get(key)
        if isinstance(nested, Mapping) and nested.get("path"):
            return str(nested["path"])
    data = value.get("data")
    if isinstance(data, Mapping):
        return _artifact_path(data)
    raw = value.get("raw")
    if isinstance(raw, Mapping):
        return _artifact_path(raw)
    return None


def _looks_like_reference(value: Any) -> bool:
    return isinstance(value, str) and (value.startswith("keepa://") or value.startswith("products.") or Path(value).suffix == ".json")


def _decode_resource_identifier(token: str) -> str:
    if token.startswith("b64:"):
        return _base64url_decode(token.removeprefix("b64:")).strip()
    return token.strip()


def _decode_path_resource(uri: str) -> Path:
    prefix = "keepa://output/" if uri.startswith("keepa://output/") else "keepa://chunk/"
    return Path(_base64url_decode(uri.removeprefix(prefix)))


def _base64url_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _write_temp_json(payload: Any, *, prefix: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", prefix=prefix, delete=False)
    with handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return handle.name


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen or text.startswith("<"):
            continue
        seen.add(text)
        result.append(text)
    return result


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value:
        return value
    return None
