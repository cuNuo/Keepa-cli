"""
keepa_cli/agent/tools.py
文件说明：定义 Agent/MCP tool registry 与 service command 映射。
主要职责：为 MCP 暴露少量强类型工具，并把 tool params 归一到 run_command 参数。
依赖边界：不执行网络请求，不解析 CLI 字符串。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    command: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    groups: tuple[str, ...] = ("research",)
    read_only: bool = True
    destructive: bool = False

    def to_mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "x-keepa": {
                "service_command": self.command,
                "groups": list(self.groups),
            },
        }


def _string_schema(description: str, *, default: str | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "string", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


def _boolean_schema(description: str, *, default: bool = False) -> JsonSchema:
    return {"type": "boolean", "description": description, "default": default}


def _integer_schema(description: str, *, minimum: int | None = None, default: int | None = None) -> JsonSchema:
    schema: JsonSchema = {"type": "integer", "description": description}
    if minimum is not None:
        schema["minimum"] = minimum
    if default is not None:
        schema["default"] = default
    return schema


def _string_array_schema(description: str) -> JsonSchema:
    return {"type": "array", "items": {"type": "string"}, "description": description}


PRODUCTS_GET_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "asin": {
            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "One ASIN or a short ASIN list.",
        },
        "code": {
            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "UPC, EAN, or ISBN-13 codes. Do not combine with asin.",
        },
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "full": _boolean_schema("Use the low-cost complete detail preset."),
        "agent_view": _boolean_schema("Return the stable Agent product view."),
        "view": {
            "type": "string",
            "enum": ["raw", "agent", "summary", "research", "deal", "audit"],
            "default": "summary",
            "description": "Agent view profile. Prefer summary for broad pipelines.",
        },
        "fields": _string_schema("Comma-separated Agent view sections."),
        "history_limit": _integer_schema("Recent points retained per history series.", minimum=0, default=10),
        "temporal_window_days": {
            "oneOf": [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}}, {"type": "string"}],
            "description": "Temporal feature windows in days.",
        },
        "stats_window": _string_schema("--full stats window; 0 means Keepa maximum/all history.", default="0"),
        "history": _string_schema("Keepa history flag, usually 0 or 1."),
        "stats": _string_schema("Keepa stats parameter."),
        "days": _string_schema("Limit returned history days."),
        "offers": _string_schema("Offer count, official range 20..100; high-cost."),
        "rating": _string_schema("Set 1 only when Keepa rating refresh is required."),
        "buybox": _string_schema("Set 1 only when Buy Box history is required."),
        "videos": _string_schema("Set 1 to include videos."),
        "aplus": _string_schema("Set 1 to include A+ content."),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm high-cost request execution."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


CATEGORIES_SEARCH_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["term"],
    "properties": {
        "term": _string_schema("Category search term. Multiple words must all match."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


CATEGORIES_PRODUCTS_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category"],
    "properties": {
        "category": _string_schema("Keepa category id."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "limit": _integer_schema("Candidate ASIN limit.", minimum=1, default=25),
        "hydrate_top": _integer_schema("Explicitly hydrate top N products. Defaults to 0.", minimum=0, default=0),
        "product_fixture": _string_schema("Product fixture for hydrate_top offline tests."),
        "history_limit": _integer_schema("History points retained in hydrated product summaries.", minimum=0, default=3),
        "temporal_window_days": {
            "oneOf": [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}}, {"type": "string"}],
            "description": "Temporal feature windows for hydrated product summaries.",
        },
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm high-cost request execution."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


FINDER_QUERY_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selection": {"type": "object", "description": "Keepa Product Finder selection JSON."},
        "selection_file": _string_schema("Path to a Product Finder selection JSON file."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "max_tokens": _integer_schema("Agent token budget hint.", minimum=1, default=10),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm high-cost request execution."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
    "anyOf": [{"required": ["selection"]}, {"required": ["selection_file"]}],
}


AUDIT_COST_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_command": _string_schema("Command to estimate, for example products.get."),
        "params": {"type": "object", "description": "Command params for the target command."},
        "commands": {
            "type": "array",
            "description": "Multiple command specs to estimate.",
            "items": {
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": _string_schema("Command name."),
                    "params": {"type": "object"},
                },
            },
        },
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


MCP_ENVELOPE_OUTPUT_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": True,
    "required": ["ok", "command", "cache_key", "cache_hit", "budget_ledger"],
    "properties": {
        "ok": {"type": "boolean"},
        "command": {"type": "string"},
        "cache_key": {"type": "string"},
        "cache_hit": {"type": "boolean"},
        "budget_ledger": {
            "type": "object",
            "required": ["session_estimated", "session_consumed", "remaining_limit", "blocked_actions"],
            "properties": {
                "session_estimated": {"type": "integer"},
                "session_consumed": {"type": "integer"},
                "remaining_limit": {"type": ["integer", "null"]},
                "blocked_actions": {"type": "array"},
                "cache_hits": {"type": "integer"},
                "consumed_source": {"type": "string"},
            },
        },
        "data": {"type": "object"},
        "error": {"type": "object"},
    },
}


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="keepa.products_get",
        command="products.get",
        description="Fetch Keepa product data and optionally return an Agent-safe product view.",
        input_schema=PRODUCTS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "product"),
    ),
    ToolDefinition(
        name="keepa.categories_search",
        command="categories.search",
        description="Search Keepa categories by term and return Agent-friendly category candidates.",
        input_schema=CATEGORIES_SEARCH_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "category"),
    ),
    ToolDefinition(
        name="keepa.categories_products",
        command="categories.products",
        description="Fetch candidate ASINs for a category via Best Sellers; live calls require confirmation.",
        input_schema=CATEGORIES_PRODUCTS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "category"),
    ),
    ToolDefinition(
        name="keepa.finder_query",
        command="finder.query",
        description="Run a Product Finder selection query; prefer dry_run or fixture before live calls.",
        input_schema=FINDER_QUERY_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "finder"),
    ),
    ToolDefinition(
        name="keepa.audit_cost",
        command="audit.cost",
        description="Estimate token cost and confirmation requirements for Keepa CLI commands.",
        input_schema=AUDIT_COST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("audit",),
    ),
)


_TOOL_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}


def list_mcp_tools(*, groups: set[str] | None = None) -> list[dict[str, Any]]:
    tools = TOOL_DEFINITIONS
    if groups:
        tools = tuple(tool for tool in tools if groups.intersection(tool.groups))
    return [tool.to_mcp_tool() for tool in tools]


def get_tool_definition(name: str) -> ToolDefinition | None:
    return _TOOL_BY_NAME.get(name)


def tool_params_to_command_params(tool: ToolDefinition, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    params = dict(arguments or {})
    if tool.command == "products.get":
        if "temporal_window_days" in params and "temporal_windows" not in params:
            params["temporal_windows"] = params.pop("temporal_window_days")
        if params.get("view") and params.get("view") != "raw":
            params.setdefault("agent_view", True)
        return params
    if tool.command == "categories.products":
        if "temporal_window_days" in params and "temporal_windows" not in params:
            params["temporal_windows"] = params.pop("temporal_window_days")
        return params
    if tool.command == "audit.cost":
        if "commands" not in params and "target_command" not in params and "command" not in params:
            params["target_command"] = "products.get"
        return params
    return params


def validate_tool_arguments(tool: ToolDefinition, arguments: Mapping[str, Any] | None) -> list[str]:
    if arguments is None:
        arguments = {}
    allowed = set(tool.input_schema.get("properties") or {})
    required = set(tool.input_schema.get("required") or [])
    errors: list[str] = []
    for key in arguments:
        if key not in allowed:
            errors.append(f"unsupported argument: {key}")
    for key in sorted(required):
        if key not in arguments:
            errors.append(f"missing required argument: {key}")
    if tool.name == "keepa.finder_query" and "selection" not in arguments and "selection_file" not in arguments:
        errors.append("one of selection or selection_file is required")
    if tool.name == "keepa.products_get" and arguments.get("asin") and arguments.get("code"):
        errors.append("asin and code cannot be combined")
    return errors


def tool_names() -> list[str]:
    return [tool.name for tool in TOOL_DEFINITIONS]
