"""
keepa_cli/agent/tools.py
文件说明：定义 Agent/MCP tool registry 与 service command 映射。
主要职责：为 MCP 暴露少量强类型工具，并把 tool params 归一到 run_command 参数。
依赖边界：不执行网络请求，不解析 CLI 字符串。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from keepa_cli.agent.workflow_resolver import workflow_runtime_argument_names


JsonSchema = dict[str, Any]

DEFAULT_TOOLSET = "research"
TOOLSET_GROUPS: dict[str, set[str] | None] = {
    "research": {"research"},
    "audit": {"audit"},
    "docs": {"docs"},
    "reports": {"reports"},
    "business": {"business"},
    "tracking-readonly": {"tracking-readonly"},
    "all": None,
}

PROFILE_ALLOWED_TOOLS: dict[str, set[str] | None] = {
    "offline_fixture_only": {
        "docs_index",
        "docs_read",
        "context_policy",
        "resolve_research_target",
        "query_research_context",
        "workflow_plan",
        "research_graph_merge",
        "research_brief_export",
        "audit_cost",
        "reports_build",
        "browse_snapshot",
        "figures_research",
        "cassettes_sanitize",
        "find_fast_movers",
        "inventory_audit",
        "market_opportunity",
        "agent_profile_generate",
    },
    "dry_run_default": {
        "docs_index",
        "docs_read",
        "context_policy",
        "resolve_research_target",
        "query_research_context",
        "workflow_plan",
        "categories_search",
        "categories_products",
        "categories_finder_selection",
        "finder_query",
        "deals_query",
        "bestsellers_get",
        "topsellers_list",
        "research_graph_merge",
        "research_brief_export",
        "audit_cost",
        "reports_build",
        "browse_snapshot",
        "figures_research",
        "find_fast_movers",
        "inventory_audit",
        "market_opportunity",
        "agent_profile_generate",
    },
    "live_read_allowed": None,
    "tracking_readonly": {
        "docs_index",
        "docs_read",
        "context_policy",
        "audit_cost",
        "tracking_list",
        "tracking_list_names",
        "tracking_get",
        "tracking_notifications",
    },
    "fixture_curation": {
        "docs_index",
        "docs_read",
        "context_policy",
        "audit_cost",
        "cassettes_sanitize",
        "cassettes_promote",
        "cassettes_promote_and_verify",
    },
}


def toolset_names() -> list[str]:
    return list(TOOLSET_GROUPS)


def profile_names() -> list[str]:
    return list(PROFILE_ALLOWED_TOOLS)


def profile_allowed_tools(profile: str | None) -> set[str] | None:
    if not profile:
        return None
    normalized = str(profile).strip()
    if normalized not in PROFILE_ALLOWED_TOOLS:
        raise ValueError(f"unknown profile: {normalized}")
    allowed = PROFILE_ALLOWED_TOOLS[normalized]
    return None if allowed is None else set(allowed)


def is_tool_active_for_profile(tool_name: str, profile: str | None) -> bool:
    allowed = profile_allowed_tools(profile)
    return allowed is None or tool_name in allowed


def future_task_support_contract() -> dict[str, Any]:
    return {
        "target": "required",
        "protocol": "MCP Tasks/progress",
        "reason": "large local file/report/figure generation should not block ordinary tools/call",
        "normal_tools_call_policy": "fixture_or_small_output_only",
        "start": {
            "method": "tools/call",
            "progress_token_source": "_meta.progressToken",
            "returns": "task reference when remote HTTP production mode enables tasks",
        },
        "cancel": {
            "method": "tasks/cancel",
            "required": True,
            "idempotent": True,
            "terminal_state": "cancelled",
        },
        "progress": {
            "notification": "notifications/progress",
            "required": True,
            "token_field": "progressToken",
            "monotonic": True,
            "states": ["queued", "running", "writing_result", "completed", "failed", "cancelled"],
        },
        "result": {
            "method": "tasks/result",
            "required": True,
            "resource_uri_template": "keepa://tasks/{task_id}/result",
            "resource_mime_type": "application/json",
            "retention": "bounded by adapter task retention policy",
        },
    }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    command: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    title: str | None = None
    groups: tuple[str, ...] = ("research",)
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    open_world: bool = False
    workflow_runtime: bool = False
    long_running_candidate: bool = False

    def to_mcp_tool(self) -> dict[str, Any]:
        title = self.title or f"Keepa {self.name.replace('.', ' ').replace('_', ' ').title()}"
        keepa_meta: dict[str, Any] = {
            "service_command": self.command,
            "groups": list(self.groups),
        }
        if self.workflow_runtime:
            keepa_meta["workflow_runtime"] = True
            keepa_meta["workflow_runtime_args"] = sorted(workflow_runtime_argument_names())
        if self.long_running_candidate:
            keepa_meta["long_running_candidate"] = True
            keepa_meta["normal_tools_call_policy"] = "fixture_or_small_output_only"
            keepa_meta["future_task_support"] = future_task_support_contract()
        return {
            "name": self.name,
            "title": title,
            "description": self.description,
            "inputSchema": _schema_with_common_properties(self.input_schema, workflow_runtime=self.workflow_runtime),
            "execution": {"taskSupport": "forbidden"},
            "outputSchema": self.output_schema,
            "annotations": {
                "title": title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
                "openWorldHint": self.open_world,
            },
            "x-keepa": keepa_meta,
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


PROFILE_SCHEMA: JsonSchema = {
    "type": "string",
    "enum": profile_names(),
    "description": "Optional MCP session profile. Inactive tools return inactive_tool before service execution.",
}


def _schema_with_common_properties(schema: JsonSchema, *, workflow_runtime: bool = False) -> JsonSchema:
    patched = dict(schema)
    properties = dict(patched.get("properties") or {})
    properties.setdefault("profile", PROFILE_SCHEMA)
    if workflow_runtime:
        properties.setdefault("artifact", {"type": "object", "description": "Workflow artifact object from a prior MCP tool call."})
        properties.setdefault("artifacts", {"type": "array", "items": {}, "description": "Workflow artifact objects or resource refs from prior MCP tool calls."})
        properties.setdefault("resource_uri", _string_schema("MCP resource URI used to satisfy a workflow input."))
        properties.setdefault("resource_uris", _string_array_schema("MCP resource URIs used to satisfy workflow inputs."))
        properties.setdefault("workflow_inputs", {"type": "object", "description": "workflow.plan workflow_inputs object or subset for late-bound input resolution."})
        properties.setdefault("workflow_context", {"type": "object", "description": "Additional workflow context with artifacts/resource_uris from prior steps."})
    patched["properties"] = properties
    return patched


def _format_schema_path(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]" if path else f"[{key}]"
    return key if not path else f"{path}.{key}"


def _type_label(expected: Any) -> str:
    if isinstance(expected, list):
        return " or ".join(str(item) for item in expected)
    return str(expected)


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_json_schema(schema: Mapping[str, Any], value: Any, *, path: str = "") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_json_type(value, str(item)) for item in expected_types):
            target = path or "arguments"
            return [f"{target}: expected {_type_label(expected_type)}"]

    if "enum" in schema and value not in (schema.get("enum") or []):
        allowed = ", ".join(repr(item) for item in schema.get("enum") or [])
        target = path or "arguments"
        errors.append(f"{target}: value {value!r} is not one of: {allowed}")
    if "const" in schema and value != schema["const"]:
        target = path or "arguments"
        errors.append(f"{target}: value {value!r} must equal {schema['const']!r}")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for key in sorted(str(item) for item in required):
            if key not in value:
                target = _format_schema_path(path, key) if path else key
                errors.append(f"missing required argument: {target}")
        for key, item in value.items():
            child_path = _format_schema_path(path, str(key))
            child_schema = properties.get(key)
            if child_schema is not None:
                errors.extend(_validate_json_schema(child_schema, item, path=child_path))
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                errors.append(f"unsupported argument: {child_path}")
            elif isinstance(additional, Mapping):
                errors.extend(_validate_json_schema(additional, item, path=child_path))

    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        item_schema = schema["items"]
        for index, item in enumerate(value):
            errors.extend(_validate_json_schema(item_schema, item, path=_format_schema_path(path, index)))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            target = path or "arguments"
            errors.append(f"{target}: value {value!r} is less than minimum {schema['minimum']!r}")
        if "maximum" in schema and value > schema["maximum"]:
            target = path or "arguments"
            errors.append(f"{target}: value {value!r} is greater than maximum {schema['maximum']!r}")

    if "oneOf" in schema:
        matches = [subschema for subschema in schema["oneOf"] if not _validate_json_schema(subschema, value, path=path)]
        if len(matches) != 1:
            target = path or "arguments"
            errors.append(f"{target}: must match exactly one schema in oneOf")
    if "anyOf" in schema and not any(not _validate_json_schema(subschema, value, path=path) for subschema in schema["anyOf"]):
        target = path or "arguments"
        errors.append(f"{target}: must match at least one schema in anyOf")

    return errors


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
        "chunks_dir": _string_schema("Directory for per-section Agent view chunks."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm high-cost request execution."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


PRODUCTS_COMPARE_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asin"],
    "properties": {
        "asin": {"type": "array", "items": {"type": "string"}, "description": "Two or more ASINs to compare."},
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "full": _boolean_schema("Use the low-cost complete detail preset."),
        "view": {
            "type": "string",
            "enum": ["summary", "research", "deal", "audit"],
            "default": "deal",
            "description": "Agent view profile used before comparing rows.",
        },
        "fields": _string_schema("Comma-separated Agent view sections."),
        "history_limit": _integer_schema("Recent points retained per history series.", minimum=0, default=5),
        "keep_history_points": _boolean_schema("Retain bounded per-ASIN history points in compare rows for offline multi-ASIN figures.", default=False),
        "temporal_window_days": {
            "oneOf": [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}}, {"type": "string"}],
            "description": "Temporal feature windows in days.",
        },
        "stats_window": _string_schema("--full stats window; 0 means Keepa maximum/all history.", default="0"),
        "offers": _string_schema("Offer count, official range 20..100; high-cost."),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "chunks_dir": _string_schema("Directory for per-section Agent view chunks."),
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


WORKFLOW_PLAN_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {
        "name": {
            "type": "string",
            "enum": [
                "category-research",
                "product-research",
                "report-research",
                "tracking-audit",
                "inventory-audit",
                "velocity-research",
                "market-opportunity",
            ],
            "description": "Agent workflow plan name.",
        },
        "term": _string_schema("Keyword for category-research plans."),
        "asin": _string_schema("ASIN for product-research plans."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "goal": _string_schema("Research goal, for example deal or research.", default="research"),
        "hydrate_top": _integer_schema("Optional explicit top-N hydration step for category plans.", minimum=0, default=0),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


BUSINESS_METRICS_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "input": _string_schema("Local Keepa CLI JSON file containing raw products, Agent view products, or compare rows."),
        "fixture": _string_schema("Fixture file name under tests/fixtures."),
        "domain": _string_schema("Keepa domain code carried for evidence context.", default="US"),
        "payload": {
            "oneOf": [{"type": "object"}, {"type": "array", "items": {}}],
            "description": "Inline Keepa CLI payload, Agent view, product list, or compare rows.",
        },
        "threshold_monthly_sold": _integer_schema("MonthlySold threshold used to mark fast movers.", minimum=0, default=500),
        "target_days": _integer_schema("Inventory risk target window in days.", minimum=1, default=30),
        "max_results": _integer_schema("Optional maximum product rows to return.", minimum=1),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


AGENT_PROFILE_GENERATE_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "server_name": _string_schema("MCP server name in the generated client config snippet.", default="keepa"),
        "profile": _string_schema("Recommended profile for tools/list and tools/call.", default="dry_run_default"),
        "toolset": _string_schema("Recommended toolset for tools/list.", default="research"),
        "python_command": _string_schema("Optional Python command/path for the generated stdio entrypoint."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


RESEARCH_GRAPH_MERGE_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "input": {
            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "One or more JSON files that contain research_graph fields.",
        },
        "graph": {
            "oneOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}],
            "description": "Inline research graph or full Keepa CLI payload containing research_graph fields.",
        },
        "root": _string_schema("Merged graph root id.", default="merged_research_graph"),
        "label": _string_schema("Merged graph label.", default="merged research graph"),
        "prefer_source": _string_schema("Optional source index or source root to prefer when resolving node label/type conflicts."),
        "out": _string_schema("Optional output path for the merged graph JSON."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
    "anyOf": [{"required": ["input"]}, {"required": ["graph"]}],
}


RESEARCH_BRIEF_EXPORT_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "input": {
            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "One or more Keepa CLI JSON files, such as research_graph.merge, products.compare, seller, or category outputs.",
        },
        "payload": {
            "oneOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}],
            "description": "Inline Keepa CLI payloads to summarize.",
        },
        "graph": {
            "oneOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}],
            "description": "Inline research_graph object or graph list.",
        },
        "title": _string_schema("Human-readable brief title.", default="Keepa research brief"),
        "id": _string_schema("Stable brief id. Defaults to graph root or title slug."),
        "out": _string_schema("Optional output path for the research brief JSON."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
    "anyOf": [{"required": ["input"]}, {"required": ["payload"]}, {"required": ["graph"]}],
}


CATEGORIES_FINDER_SELECTION_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category"],
    "properties": {
        "category": _string_schema("Keepa category id."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "per_page": _integer_schema("Finder page size scaffold.", minimum=1, default=50),
        "sales_rank_max": _integer_schema("Maximum current sales rank in the scaffold.", minimum=1, default=20000),
        "min_reviews": _integer_schema("Minimum review count in the scaffold.", minimum=0, default=50),
        "out": _string_schema("Optional path to write the selection JSON scaffold."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


DEALS_QUERY_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selection": {"type": "object", "description": "Keepa Deals selection JSON."},
        "selection_file": _string_schema("Path to a Deals selection JSON file."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm execution when required."),
        "out": _string_schema("Optional path to write the large response body."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
    "anyOf": [{"required": ["selection"]}, {"required": ["selection_file"]}],
}


SELLERS_GET_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["seller"],
    "properties": {
        "seller": {
            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
            "description": "One seller id or a seller id list.",
        },
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "storefront": _boolean_schema("Request seller storefront ASIN list."),
        "update": _string_schema("Refresh threshold in hours."),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "out": _string_schema("Optional path to write the large response body."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


BESTSELLERS_GET_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category"],
    "properties": {
        "category": _string_schema("Keepa category id."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm the 50-token Best Sellers request."),
        "out": _string_schema("Optional path to write the large response body."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


TOPSELLERS_LIST_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": _string_schema("Optional Keepa category id."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "yes": _boolean_schema("Confirm the 50-token Top Sellers request."),
        "out": _string_schema("Optional path to write the large response body."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


REPORTS_BUILD_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input"],
    "properties": {
        "input": _string_schema("Input JSON path from batch/product/category/research_graph.merge workflows."),
        "format": {
            "type": "string",
            "enum": ["markdown", "json", "csv"],
            "default": "markdown",
            "description": "Report output format.",
        },
        "out": _string_schema("Optional report output file path."),
        "title": _string_schema("Report title.", default="Keepa Report"),
        "figure": _string_schema("Optional existing SVG/image path to embed in markdown/json reports."),
        "figures_dir": _string_schema("Optional directory for automatically generated report SVG assets."),
        "figure_set": {
            "type": "string",
            "enum": ["all", "history", "compare", "audit"],
            "default": "all",
            "description": "Generated figure group. Use history, compare, or audit to reduce Agent resource noise.",
        },
        "no_figures": _boolean_schema("Disable automatic local SVG generation and embedding.", default=False),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


BROWSE_SNAPSHOT_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input"],
    "properties": {
        "input": _string_schema("Input JSON path from batch/product/category workflows."),
        "out_dir": _string_schema("Directory for the local HTML snapshot.", default="keepa-browse"),
        "title": _string_schema("Snapshot title.", default="Keepa Local Browse"),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


FIGURES_RESEARCH_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input"],
    "properties": {
        "input": _string_schema("Input JSON path from products.compare, research_graph.merge, or Agent view output."),
        "out_dir": _string_schema("Directory for generated SVG and source JSON.", default="keepa-figures"),
        "title": _string_schema("Figure title.", default="Keepa Agent Research Figures"),
        "figure_set": {
            "type": "string",
            "enum": ["all", "history", "compare", "audit"],
            "default": "all",
            "description": "Figure group to generate. Use history for time-series, compare for product comparison, or audit for risk/graph summary.",
        },
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


DOCS_INDEX_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


DOCS_READ_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "uri": _string_schema("MCP resource URI to read, for example keepa://zread/wiki/current."),
        "page": _string_schema("zread page slug or markdown file name. Used when uri is omitted."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


CONTEXT_POLICY_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


RESOLVE_RESEARCH_TARGET_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": _string_schema("ASIN, UPC/EAN/ISBN, seller id, category id, fixture name, evidence keyword, or research phrase."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "hint_type": {
            "type": "string",
            "enum": ["asin", "code", "seller", "category", "keyword", "fixture", "evidence"],
            "description": "Optional target type hint used only for ranking local candidates.",
        },
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


QUERY_RESEARCH_CONTEXT_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "query": _string_schema("Natural language question or unresolved research target."),
        "question": _string_schema("Question to answer from local schema, fixture, evidence, zread, and cache context."),
        "target_type": {
            "type": "string",
            "enum": ["asin", "code", "seller", "category", "keyword", "fixture", "evidence"],
            "description": "Resolved target type.",
        },
        "target_id": _string_schema("Resolved target id, such as ASIN, category id, fixture path, or evidence logical path."),
        "target": {"type": "object", "description": "Resolved target candidate returned by resolve_research_target."},
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


TRACKING_LIST_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "asins_only": _boolean_schema("Return only tracking ASIN names where supported."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "out": _string_schema("Optional path to write the response body."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


TRACKING_GET_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asin"],
    "properties": {
        "asin": _string_schema("Tracked ASIN to inspect."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


TRACKING_NOTIFICATIONS_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "since": {
            "oneOf": [{"type": "integer"}, {"type": "string"}],
            "description": "Keepa tracking notification cursor or timestamp.",
            "default": 0,
        },
        "revise": _boolean_schema("Ask Keepa to revise notification state."),
        "domain": _string_schema("Keepa domain code, id, or host suffix.", default="US"),
        "fixture": _string_schema("Fixture filename under tests/fixtures."),
        "dry_run": _boolean_schema("Build request spec without calling Keepa."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


CASSETTES_SANITIZE_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input", "out"],
    "properties": {
        "input": _string_schema("Raw cassette JSON path."),
        "out": _string_schema("Redacted cassette JSON output path."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


CASSETTES_PROMOTE_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input", "name"],
    "properties": {
        "input": _string_schema("Raw or redacted cassette JSON path."),
        "name": _string_schema("Fixture filename, with or without .json."),
        "tests_dir": _string_schema("tests fixture directory.", default="tests/fixtures"),
        "package_dir": _string_schema("package fixture directory.", default="keepa_cli/fixtures"),
        "manifest": _string_schema("Evidence manifest path.", default="evidence/manifest.csv"),
        "title": _string_schema("Manifest title."),
        "no_manifest": _boolean_schema("Skip evidence manifest update."),
        "dry_run": _boolean_schema("Preview target files without writing."),
        "from_cache": _string_schema("Session cache key to reuse."),
    },
}


CASSETTES_PROMOTE_AND_VERIFY_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input", "name"],
    "properties": {
        "input": _string_schema("Raw or redacted cassette JSON path."),
        "name": _string_schema("Fixture filename, with or without .json."),
        "tests_dir": _string_schema("tests fixture directory.", default="tests/fixtures"),
        "package_dir": _string_schema("package fixture directory.", default="keepa_cli/fixtures"),
        "eval_dir": _string_schema("Agent eval spec directory.", default="tests/agent_eval_fixtures"),
        "manifest": _string_schema("Evidence manifest path.", default="evidence/manifest.csv"),
        "title": _string_schema("Manifest title."),
        "no_manifest": _boolean_schema("Skip evidence manifest update."),
        "run_eval": _boolean_schema("Run Agent eval fixtures after fixture sync."),
        "dry_run": _boolean_schema("Preview target files without writing or verification."),
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
        name="products_get",
        command="products.get",
        description="Fetch Keepa product data and return Agent-safe product views with risk_taxonomy, research_graph, data_quality, and next_actions.",
        input_schema=PRODUCTS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        open_world=True,
        groups=("research", "product"),
    ),
    ToolDefinition(
        name="products_compare",
        command="products.compare",
        description="Compare ASINs using Agent-safe deal/research rows with unified risk summary and merged research graph.",
        input_schema=PRODUCTS_COMPARE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        open_world=True,
        groups=("research", "product", "compare"),
    ),
    ToolDefinition(
        name="categories_search",
        command="categories.search",
        description="Search Keepa categories by term and return Agent-friendly category candidates.",
        input_schema=CATEGORIES_SEARCH_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("research", "category"),
    ),
    ToolDefinition(
        name="categories_products",
        command="categories.products",
        description="Fetch candidate ASINs for a category via Best Sellers; live calls require confirmation.",
        input_schema=CATEGORIES_PRODUCTS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        open_world=True,
        groups=("research", "category"),
    ),
    ToolDefinition(
        name="categories_finder_selection",
        command="categories.finder-selection",
        description="Generate a local Product Finder selection scaffold from a category without calling Keepa.",
        input_schema=CATEGORIES_FINDER_SELECTION_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        groups=("research", "category", "finder"),
    ),
    ToolDefinition(
        name="finder_query",
        command="finder.query",
        description="Run a Product Finder selection query; prefer dry_run or fixture before live calls.",
        input_schema=FINDER_QUERY_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("research", "finder"),
    ),
    ToolDefinition(
        name="deals_query",
        command="deals.query",
        description="Run a Deals selection query and return Agent profile plus deal/product research graph when available.",
        input_schema=DEALS_QUERY_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("research", "deals"),
    ),
    ToolDefinition(
        name="sellers_get",
        command="sellers.get",
        description="Fetch seller information and storefront ASINs with Agent profile and seller/product research graph.",
        input_schema=SELLERS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("research", "seller"),
    ),
    ToolDefinition(
        name="bestsellers_get",
        command="bestsellers.get",
        description="Fetch Keepa Best Sellers for a category; live calls require explicit confirmation.",
        input_schema=BESTSELLERS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("research", "category", "rankings"),
    ),
    ToolDefinition(
        name="topsellers_list",
        command="topsellers.list",
        description="Fetch Keepa Top Sellers; live calls require explicit confirmation.",
        input_schema=TOPSELLERS_LIST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("research", "seller", "rankings"),
    ),
    ToolDefinition(
        name="workflow_plan",
        command="workflow.plan",
        description="Plan a token-safe Agent workflow without calling Keepa.",
        input_schema=WORKFLOW_PLAN_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "planning"),
    ),
    ToolDefinition(
        name="find_fast_movers",
        command="business.find-fast-movers",
        description="Business alias: rank local Keepa product outputs by monthlySold or velocity proxy with formula confidence metadata.",
        input_schema=BUSINESS_METRICS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        groups=("business", "research"),
    ),
    ToolDefinition(
        name="inventory_audit",
        command="business.inventory-audit",
        description="Business alias: audit local product outputs for inventory and stockout risk with method/input/confidence evidence.",
        input_schema=BUSINESS_METRICS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        groups=("business", "research"),
    ),
    ToolDefinition(
        name="market_opportunity",
        command="business.market-opportunity",
        description="Business alias: combine velocity, seller competition, inventory risk, and cashflow proxy into a conclusion-first opportunity brief.",
        input_schema=BUSINESS_METRICS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        groups=("business", "research"),
    ),
    ToolDefinition(
        name="agent_profile_generate",
        command="agent.profile.generate",
        description="Generate a neutral Agent MCP client config snippet plus recommended toolset/profile choices.",
        input_schema=AGENT_PROFILE_GENERATE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("business", "docs", "research"),
    ),
    ToolDefinition(
        name="research_graph_merge",
        command="research_graph.merge",
        description="Merge research_graph objects from category, product, compare, deal, and seller outputs without calling Keepa.",
        input_schema=RESEARCH_GRAPH_MERGE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        read_only=False,
        groups=("research", "graph", "reports"),
    ),
    ToolDefinition(
        name="research_brief_export",
        command="research_brief.export",
        description="Export a compact decision brief from merged graphs and Agent payloads without calling Keepa.",
        input_schema=RESEARCH_BRIEF_EXPORT_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        read_only=False,
        groups=("research", "graph", "reports"),
    ),
    ToolDefinition(
        name="docs_index",
        command="docs.index",
        description="List stable Keepa CLI documentation resources, including zread wiki, schema, evidence, and templates.",
        input_schema=DOCS_INDEX_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("docs", "research"),
    ),
    ToolDefinition(
        name="docs_read",
        command="docs.read",
        description="Read a local documentation resource by URI or zread page slug for clients that cannot use MCP resources/read.",
        input_schema=DOCS_READ_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("docs", "research"),
    ),
    ToolDefinition(
        name="context_policy",
        command="context.policy",
        description="Read offline-first Agent policy, allowed roots, tool gating hints, and live Keepa safety status.",
        input_schema=CONTEXT_POLICY_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("docs", "research"),
    ),
    ToolDefinition(
        name="resolve_research_target",
        command="research.target.resolve",
        description="Resolve a fuzzy research query into local ASIN, code, seller, category, fixture, evidence, or keyword candidates without calling Keepa.",
        input_schema=RESOLVE_RESEARCH_TARGET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research",),
    ),
    ToolDefinition(
        name="query_research_context",
        command="research.context.query",
        description="Return local resources relevant to a resolved research target or question before any live Keepa request.",
        input_schema=QUERY_RESEARCH_CONTEXT_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "docs"),
    ),
    ToolDefinition(
        name="audit_cost",
        command="audit.cost",
        description="Estimate token cost and confirmation requirements for Keepa CLI commands.",
        input_schema=AUDIT_COST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        groups=("audit", "tracking-readonly"),
    ),
    ToolDefinition(
        name="cassettes_sanitize",
        command="cassettes.sanitize",
        description="Redact secrets from a raw Keepa cassette JSON file.",
        input_schema=CASSETTES_SANITIZE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        read_only=False,
        groups=("audit", "cassette"),
    ),
    ToolDefinition(
        name="cassettes_promote",
        command="cassettes.promote",
        description="Sanitize a cassette, write synchronized test/package fixtures, and update evidence manifest.",
        input_schema=CASSETTES_PROMOTE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        read_only=False,
        destructive=True,
        groups=("audit", "cassette"),
    ),
    ToolDefinition(
        name="cassettes_promote_and_verify",
        command="cassettes.promote_and_verify",
        description="Promote a cassette, verify fixture parity, and optionally run Agent eval fixtures.",
        input_schema=CASSETTES_PROMOTE_AND_VERIFY_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        read_only=False,
        destructive=True,
        groups=("audit", "cassette"),
    ),
    ToolDefinition(
        name="reports_build",
        command="reports.build",
        description="Build a local markdown/json/csv report from existing Keepa CLI JSON output.",
        input_schema=REPORTS_BUILD_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        long_running_candidate=True,
        read_only=False,
        groups=("reports",),
    ),
    ToolDefinition(
        name="browse_snapshot",
        command="browse.snapshot",
        description="Create a local HTML browsing snapshot from existing Keepa CLI JSON output.",
        input_schema=BROWSE_SNAPSHOT_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        read_only=False,
        groups=("reports",),
    ),
    ToolDefinition(
        name="figures_research",
        command="figures.research",
        description="Generate Agent-report-ready SVG figures from product, comparison, or research graph JSON without calling Keepa.",
        input_schema=FIGURES_RESEARCH_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        long_running_candidate=True,
        read_only=False,
        groups=("reports",),
    ),
    ToolDefinition(
        name="tracking_list",
        command="tracking.list",
        description="Read Keepa tracking list state. This toolset exposes read-only tracking operations only.",
        input_schema=TRACKING_LIST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("tracking-readonly",),
    ),
    ToolDefinition(
        name="tracking_list_names",
        command="tracking.list-names",
        description="Read Keepa tracking ASIN names only.",
        input_schema=TRACKING_LIST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("tracking-readonly",),
    ),
    ToolDefinition(
        name="tracking_get",
        command="tracking.get",
        description="Read tracking details for one ASIN.",
        input_schema=TRACKING_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        workflow_runtime=True,
        open_world=True,
        groups=("tracking-readonly",),
    ),
    ToolDefinition(
        name="tracking_notifications",
        command="tracking.notifications",
        description="Read tracking notifications without exposing tracking write tools.",
        input_schema=TRACKING_NOTIFICATIONS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        open_world=True,
        groups=("tracking-readonly",),
    ),
)


_TOOL_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}
_MCP_TOOL_SCHEMA_CACHE = {tool.name: tool.to_mcp_tool() for tool in TOOL_DEFINITIONS}


def resolve_toolset_groups(toolsets: str | list[str] | tuple[str, ...] | set[str] | None = None) -> set[str] | None:
    if toolsets is None:
        toolsets = DEFAULT_TOOLSET
    if isinstance(toolsets, str):
        names = [toolsets]
    else:
        names = [str(item) for item in toolsets]
    resolved: set[str] = set()
    for name in names:
        normalized = name.strip().lower()
        if not normalized:
            continue
        if normalized not in TOOLSET_GROUPS:
            raise ValueError(f"unknown MCP toolset: {name}")
        groups = TOOLSET_GROUPS.get(normalized)
        if normalized == "all" or groups is None:
            return None
        resolved.update(groups)
    return resolved or TOOLSET_GROUPS[DEFAULT_TOOLSET]


def list_mcp_tools(
    *,
    groups: set[str] | None = None,
    toolsets: str | list[str] | tuple[str, ...] | set[str] | None = None,
    allow_tools: list[str] | tuple[str, ...] | set[str] | None = None,
    exclude_tools: list[str] | tuple[str, ...] | set[str] | None = None,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    tools = TOOL_DEFINITIONS
    allowed_by_profile = profile_allowed_tools(profile)
    if groups is None:
        groups = resolve_toolset_groups(toolsets)
    if groups:
        tools = tuple(tool for tool in tools if groups.intersection(tool.groups))
    if allow_tools:
        allowed = {str(name) for name in allow_tools}
        tools = tuple(tool for tool in tools if tool.name in allowed)
    if exclude_tools:
        excluded = {str(name) for name in exclude_tools}
        tools = tuple(tool for tool in tools if tool.name not in excluded)
    result: list[dict[str, Any]] = []
    for tool in tools:
        item = copy.deepcopy(_MCP_TOOL_SCHEMA_CACHE[tool.name])
        active = allowed_by_profile is None or tool.name in allowed_by_profile
        item["x-keepa"]["active"] = active
        item["x-keepa"]["inactive_reason"] = None if active else f"inactive_tool: profile {profile} does not allow this tool"
        result.append(item)
    return result


def get_tool_definition(name: str) -> ToolDefinition | None:
    return _TOOL_BY_NAME.get(name)


def tool_params_to_command_params(tool: ToolDefinition, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    params = dict(arguments or {})
    params.pop("profile", None)
    rename_pairs = (
        ("per_page", "per-page"),
        ("sales_rank_max", "sales-rank-max"),
        ("min_reviews", "min-reviews"),
        ("hydrate_top", "hydrate-top"),
        ("out_dir", "out-dir"),
        ("asins_only", "asins-only"),
        ("no_manifest", "no-manifest"),
        ("tests_dir", "tests-dir"),
        ("package_dir", "package-dir"),
    )
    for source, target in rename_pairs:
        if source in params and target not in params:
            params[target] = params.pop(source)
    if tool.command == "products.get":
        if "temporal_window_days" in params and "temporal_windows" not in params:
            params["temporal_windows"] = params.pop("temporal_window_days")
        if params.get("view") and params.get("view") != "raw":
            params.setdefault("agent_view", True)
        return params
    if tool.command == "products.compare":
        if "temporal_window_days" in params and "temporal_windows" not in params:
            params["temporal_windows"] = params.pop("temporal_window_days")
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
    schema = _schema_with_common_properties(tool.input_schema, workflow_runtime=tool.workflow_runtime)
    errors = _validate_json_schema(schema, dict(arguments))
    if tool.name in {"finder_query", "deals_query"} and "selection" not in arguments and "selection_file" not in arguments:
        errors.append("one of selection or selection_file is required")
    if tool.name == "products_get" and arguments.get("asin") and arguments.get("code"):
        errors.append("asin and code cannot be combined")
    if tool.name == "products_compare" and len(arguments.get("asin") or []) < 2:
        errors.append("asin must contain at least two ASINs")
    if tool.name == "workflow_plan":
        name = str(arguments.get("name") or "")
        if name == "category-research" and not arguments.get("term"):
            errors.append("term is required for category-research")
        if name == "product-research" and not arguments.get("asin"):
            errors.append("asin is required for product-research")
    if tool.name == "research_graph_merge" and not arguments.get("input") and not arguments.get("graph"):
        errors.append("one of input or graph is required")
    if tool.name == "research_brief_export" and not arguments.get("input") and not arguments.get("payload") and not arguments.get("graph"):
        errors.append("one of input, payload, or graph is required")
    if tool.name == "figures_research" and not arguments.get("input"):
        errors.append("input is required")
    return list(dict.fromkeys(errors))


def tool_names() -> list[str]:
    return [tool.name for tool in TOOL_DEFINITIONS]


def workflow_runtime_contract() -> dict[str, Any]:
    args = sorted(workflow_runtime_argument_names())
    tools = [
        {
            "name": tool.name,
            "service_command": tool.command,
            "groups": list(tool.groups),
            "resource_uri": f"keepa://tools/{tool.name}",
            "runtime_args": args,
            "long_running_candidate": tool.long_running_candidate,
            "future_task_support": future_task_support_contract() if tool.long_running_candidate else None,
        }
        for tool in TOOL_DEFINITIONS
        if tool.workflow_runtime
    ]
    return {
        "schema_version": "2026-05-12.1",
        "schema_resource_uri": "keepa://schema/workflow-runtime-contract",
        "argument_names": args,
        "tool_count": len(tools),
        "tools": tools,
        "source_shapes": {
            "artifact": [
                {"payload": {"ok": True, "data": {"research_graph": "<graph>"}}},
                {"graph": {"nodes": [], "edges": []}},
                {"output": {"path": "graph-or-report.json"}},
                {"data": {"output": {"path": "graph-or-report.json"}}},
                {"resource_uri": "keepa://research/{cache_key}"},
                {"cache_key": "products.compare:..."},
            ],
            "workflow_context": {
                "artifact": "<single artifact shape>",
                "artifacts": ["<artifact shape>"],
                "resource_uri": "keepa://research/{cache_key}",
                "resource_uris": ["keepa://research/{cache_key}/graph"],
                "steps": {"step_id": {"artifact": "<artifact shape>"}},
                "outputs": {"step_id": "<artifact shape>"},
                "results": ["<artifact shape>"],
                "step_outputs": {"step_id": "<artifact shape>"},
                "previous_outputs": ["<artifact shape>"],
            },
        },
        "accepted_sources": [
            {
                "argument": "resource_uri",
                "sources": [
                    "keepa://research/{cache_key}",
                    "keepa://research/{cache_key}/graph",
                    "keepa://output/{encoded_path}",
                    "keepa://chunk/{encoded_path}",
                    "other JSON MCP resources",
                ],
            },
            {
                "argument": "resource_uris",
                "sources": ["array of resource_uri values"],
            },
            {
                "argument": "artifact",
                "sources": ["inline payload, graph, path, cache_key, uri, or resource_uri"],
            },
            {
                "argument": "artifacts",
                "sources": ["array of artifact values"],
            },
            {
                "argument": "workflow_inputs",
                "sources": ["workflow.plan workflow_inputs object"],
            },
            {
                "argument": "workflow_context",
                "sources": [
                    "client-managed workflow state object",
                    "workflow_context.steps",
                    "workflow_context.outputs",
                    "workflow_context.results",
                    "workflow_context.step_outputs",
                    "workflow_context.previous_outputs",
                ],
            },
        ],
        "failure_kind": "missing_inputs",
        "success_field": "data.workflow_resolution",
    }
