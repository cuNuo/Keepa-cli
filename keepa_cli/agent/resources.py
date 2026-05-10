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
from keepa_cli.research_graph import graph_summary


RESOURCE_SCHEMA_VERSION = "2026-05-10.2"
MAX_RESOURCE_TEXT_BYTES = 1_000_000


STATIC_RESOURCES: tuple[dict[str, str], ...] = (
    {
        "uri": "keepa://schema/products-agent-view",
        "name": "products.agent-view.schema",
        "description": "Generated JSON schema for the product Agent view contract.",
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
)


RESOURCE_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "uriTemplate": "keepa://schema/{name}",
        "name": "schema-by-name",
        "description": "Read a generated schema by stable name. Currently supports products-agent-view.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "keepa://fixtures/{name}",
        "name": "fixture-by-name",
        "description": "Read a sanitized JSON fixture by file name from keepa_cli/fixtures or tests/fixtures.",
        "mimeType": "application/json",
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
)


def list_mcp_resources() -> list[dict[str, str]]:
    return [dict(resource) for resource in STATIC_RESOURCES]


def list_mcp_resource_templates() -> list[dict[str, str]]:
    return [dict(template) for template in RESOURCE_TEMPLATES]


def read_mcp_resource(uri: str, *, root: Path | str | None = None) -> dict[str, str]:
    repo_root = Path(root).resolve() if root is not None else _default_repo_root()
    if uri == "keepa://schema/products-agent-view":
        return _read_text_resource(uri, repo_root / "docs/schema/products.agent-view.schema.json", "application/json")
    if uri == "keepa://fixtures/manifest":
        return _read_text_resource(uri, repo_root / "evidence/manifest.csv", "text/csv")
    if uri == "keepa://guides/cassette-promotion":
        return {"uri": uri, "mimeType": "text/markdown", "text": _cassette_promotion_guide()}
    if uri == "keepa://evidence/recent":
        return {"uri": uri, "mimeType": "application/json", "text": json.dumps(_recent_evidence(repo_root), ensure_ascii=False, indent=2)}
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
    token = base64.urlsafe_b64encode(resolved.encode("utf-8")).decode("ascii").rstrip("=")
    return f"keepa://{kind}/{token}"


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


def _path_from_resource_uri(uri: str, *, kind: str) -> Path:
    prefix = f"keepa://{kind}/"
    token = uri[len(prefix) :]
    padding = "=" * (-len(token) % 4)
    return Path(base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8"))


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
    return "text/plain"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
