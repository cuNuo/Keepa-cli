"""
keepa_cli/capabilities.py
文件说明：定义 Agent 能力发现协议。
主要职责：暴露命令、预算、确认要求、fixture/live 支持和输出类型。
依赖边界：纯静态能力清单，不访问 Keepa API。
"""

from __future__ import annotations

from typing import Any

from keepa_cli.agent.resources import list_mcp_resources
from keepa_cli.agent.tools import list_mcp_tools, toolset_names
from keepa_cli.token_budget import estimate_request_budget


SCHEMA_VERSION = "2026-05-10.13"

COMMANDS: tuple[dict[str, Any], ...] = (
    {"name": "doctor", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "config.show", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "config.init", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "config.set-token", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "config.set-language", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "config.set-max-tokens", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "domains.list", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "browse.snapshot", "supports_fixture": True, "supports_live": False, "output": "html-directory"},
    {"name": "batch.asins", "supports_fixture": True, "supports_live": False, "output": "json-file-optional"},
    {"name": "templates.list", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "templates.show", "supports_fixture": False, "supports_live": False, "output": "json-file-optional"},
    {"name": "reports.build", "supports_fixture": True, "supports_live": False, "output": "text-json-csv-file-optional"},
    {"name": "cache.explain", "supports_fixture": True, "supports_live": False, "output": "json"},
    {"name": "cache.explain-key", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "cache.stats", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "cache.inspect", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "cache.prune-expired", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "cache.clear", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "audit.cost", "supports_fixture": False, "supports_live": False, "output": "json"},
    {"name": "workflow.plan", "supports_fixture": False, "supports_live": False, "output": "json-agent-plan"},
    {"name": "research_graph.merge", "supports_fixture": True, "supports_live": False, "output": "json-agent-graph"},
    {"name": "products.get", "supports_fixture": True, "supports_live": True, "output": "json-or-agent-view"},
    {"name": "products.compare", "supports_fixture": True, "supports_live": True, "output": "json-agent-view"},
    {"name": "products.search", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "categories.get", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "categories.search", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "categories.finder-selection", "supports_fixture": False, "supports_live": False, "output": "json-file-optional"},
    {"name": "categories.products", "supports_fixture": True, "supports_live": True, "output": "json-agent-candidates"},
    {"name": "history.export", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "history.trend", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "finder.query", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "deals.query", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "sellers.get", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "bestsellers.get", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "topsellers.list", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "tokens.status", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "graphs.image", "supports_fixture": True, "supports_live": True, "output": "binary-file"},
    {"name": "lightningdeals.list", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "tracking.list", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "tracking.list-names", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "tracking.get", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "tracking.add", "supports_fixture": True, "supports_live": True, "output": "json-file-optional"},
    {"name": "tracking.remove", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "tracking.remove-all", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "tracking.notifications", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "tracking.webhook", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "schema.generate", "supports_fixture": False, "supports_live": False, "output": "json-file"},
    {"name": "cassettes.sanitize", "supports_fixture": False, "supports_live": False, "output": "json-file"},
    {"name": "cassettes.promote", "supports_fixture": False, "supports_live": False, "output": "json-file"},
    {"name": "request.get", "supports_fixture": True, "supports_live": True, "output": "json"},
    {"name": "request.post", "supports_fixture": True, "supports_live": True, "output": "json"},
)


def build_capabilities() -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    for item in COMMANDS:
        budget = estimate_request_budget(item["name"]).to_dict()
        commands.append(
            {
                **item,
                "estimated_tokens": budget["estimated_tokens"],
                "worst_case_tokens": budget["worst_case_tokens"],
                "requires_confirmation": budget["requires_confirmation"],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "protocols": ["json", "stdio", "mcp", "tui"],
        "entrypoints": ["keepa-cli", "kc", "python -m keepa_cli"],
        "mcp": {
            "server_name": "keepa",
            "transport": "stdio",
            "entrypoint": "keepa-cli --mcp",
            "default_toolset": "research",
            "toolsets": toolset_names(),
            "tools": list_mcp_tools(toolsets="all"),
            "resources": list_mcp_resources(),
        },
        "commands": commands,
    }
