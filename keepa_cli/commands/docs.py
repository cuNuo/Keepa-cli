"""
keepa_cli/commands/docs.py
文件说明：提供本地文档资源命令族。
主要职责：让 CLI、stdio 与 MCP tool 能读取 zread/wiki、schema、fixture manifest 与 evidence 资源。
依赖边界：只读仓库内文档资源，不访问 Keepa API，不读取明文凭据。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from keepa_cli.agent.resources import list_mcp_resources, list_mcp_resource_templates, read_mcp_resource
from keepa_cli.envelope import success_envelope
from keepa_cli.research_context import build_context_policy, query_research_context, resolve_research_target


DOCS_COMMANDS = {"docs.index", "docs.read", "context.policy", "research.target.resolve", "research.context.query"}


def _param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


def can_handle(command: str) -> bool:
    return command in DOCS_COMMANDS


def handle_docs_command(command: str, params: Mapping[str, Any]) -> dict[str, Any]:
    if command == "docs.index":
        resources = list_mcp_resources()
        templates = list_mcp_resource_templates()
        data = {
            "schema_version": "2026-05-10.1",
            "summary": "Local Agent documentation resources exposed by Keepa CLI.",
            "stable_entrypoints": {
                "github_pages": "https://cunuo.github.io/Keepa-cli/",
                "zread_public": "https://zread.ai/cuNuo/Keepa-cli",
                "zread_current": "keepa://zread/wiki/current",
                "zread_toc": "keepa://zread/wiki/toc",
                "zread_pages": "keepa://zread/wiki/pages",
                "workflow_runtime_schema": "keepa://schema/workflow-runtime-contract",
            },
            "resources": resources,
            "resource_templates": templates,
            "recommended_read_order": [
                "keepa://zread/wiki/current",
                "keepa://zread/wiki/toc",
                "keepa://schema/products-agent-view",
                "keepa://schema/workflow-runtime-contract",
                "keepa://workflow/runtime-contract",
                "keepa://evidence/recent",
            ],
        }
    elif command == "docs.read":
        uri = str(_param(params, "uri", "resource", default="")).strip()
        page = str(_param(params, "page", "slug", default="")).strip()
        if not uri and page:
            uri = f"keepa://zread/wiki/page/{page}"
        if not uri:
            uri = "keepa://zread/wiki/current"
        content = read_mcp_resource(uri)
        text = str(content.get("text") or "")
        parsed: Any | None = None
        if str(content.get("mimeType")) == "application/json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        data = {
            "uri": content.get("uri", uri),
            "mime_type": content.get("mimeType"),
            "text": text,
            "json": parsed,
            "size_bytes": len(text.encode("utf-8")),
        }
    elif command == "context.policy":
        data = build_context_policy()
    elif command == "research.target.resolve":
        data = resolve_research_target(params)
    elif command == "research.context.query":
        data = query_research_context(params)
    else:
        raise ValueError(f"unsupported docs command: {command}")

    return success_envelope(
        command=command,
        data=data,
        request={"transport": "service"},
        token_bucket={},
    )
