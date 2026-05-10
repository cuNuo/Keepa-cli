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

DEFAULT_TOOLSET = "research"
TOOLSET_GROUPS: dict[str, set[str] | None] = {
    "research": {"research"},
    "audit": {"audit"},
    "reports": {"reports"},
    "tracking-readonly": {"tracking-readonly"},
    "all": None,
}


def toolset_names() -> list[str]:
    return list(TOOLSET_GROUPS)


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
            "enum": ["category-research", "product-research"],
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
        "input": _string_schema("Input JSON path from batch/product/category workflows."),
        "format": {
            "type": "string",
            "enum": ["markdown", "json", "csv"],
            "default": "markdown",
            "description": "Report output format.",
        },
        "out": _string_schema("Optional report output file path."),
        "title": _string_schema("Report title.", default="Keepa Report"),
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


TRACKING_LIST_SCHEMA: JsonSchema = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "asins_only": _boolean_schema("Return only tracking ASIN names where supported."),
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
        description="Fetch Keepa product data and return Agent-safe product views with risk_taxonomy, research_graph, data_quality, and next_actions.",
        input_schema=PRODUCTS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "product"),
    ),
    ToolDefinition(
        name="keepa.products_compare",
        command="products.compare",
        description="Compare ASINs using Agent-safe deal/research rows with unified risk summary and merged research graph.",
        input_schema=PRODUCTS_COMPARE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "product", "compare"),
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
        name="keepa.categories_finder_selection",
        command="categories.finder-selection",
        description="Generate a local Product Finder selection scaffold from a category without calling Keepa.",
        input_schema=CATEGORIES_FINDER_SELECTION_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "category", "finder"),
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
        name="keepa.deals_query",
        command="deals.query",
        description="Run a Deals selection query and return Agent profile plus deal/product research graph when available.",
        input_schema=DEALS_QUERY_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "deals"),
    ),
    ToolDefinition(
        name="keepa.sellers_get",
        command="sellers.get",
        description="Fetch seller information and storefront ASINs with Agent profile and seller/product research graph.",
        input_schema=SELLERS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "seller"),
    ),
    ToolDefinition(
        name="keepa.bestsellers_get",
        command="bestsellers.get",
        description="Fetch Keepa Best Sellers for a category; live calls require explicit confirmation.",
        input_schema=BESTSELLERS_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "category", "rankings"),
    ),
    ToolDefinition(
        name="keepa.topsellers_list",
        command="topsellers.list",
        description="Fetch Keepa Top Sellers; live calls require explicit confirmation.",
        input_schema=TOPSELLERS_LIST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "seller", "rankings"),
    ),
    ToolDefinition(
        name="keepa.workflow_plan",
        command="workflow.plan",
        description="Plan a token-safe Agent workflow without calling Keepa.",
        input_schema=WORKFLOW_PLAN_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "planning"),
    ),
    ToolDefinition(
        name="keepa.research_graph_merge",
        command="research_graph.merge",
        description="Merge research_graph objects from category, product, compare, deal, and seller outputs without calling Keepa.",
        input_schema=RESEARCH_GRAPH_MERGE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("research", "graph"),
    ),
    ToolDefinition(
        name="keepa.audit_cost",
        command="audit.cost",
        description="Estimate token cost and confirmation requirements for Keepa CLI commands.",
        input_schema=AUDIT_COST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("audit",),
    ),
    ToolDefinition(
        name="keepa.cassettes_sanitize",
        command="cassettes.sanitize",
        description="Redact secrets from a raw Keepa cassette JSON file.",
        input_schema=CASSETTES_SANITIZE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("audit", "cassette"),
    ),
    ToolDefinition(
        name="keepa.cassettes_promote",
        command="cassettes.promote",
        description="Sanitize a cassette, write synchronized test/package fixtures, and update evidence manifest.",
        input_schema=CASSETTES_PROMOTE_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("audit", "cassette"),
    ),
    ToolDefinition(
        name="keepa.reports_build",
        command="reports.build",
        description="Build a local markdown/json/csv report from existing Keepa CLI JSON output.",
        input_schema=REPORTS_BUILD_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("reports",),
    ),
    ToolDefinition(
        name="keepa.browse_snapshot",
        command="browse.snapshot",
        description="Create a local HTML browsing snapshot from existing Keepa CLI JSON output.",
        input_schema=BROWSE_SNAPSHOT_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("reports",),
    ),
    ToolDefinition(
        name="keepa.tracking_list",
        command="tracking.list",
        description="Read Keepa tracking list state. This toolset exposes read-only tracking operations only.",
        input_schema=TRACKING_LIST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("tracking-readonly",),
    ),
    ToolDefinition(
        name="keepa.tracking_list_names",
        command="tracking.list-names",
        description="Read Keepa tracking ASIN names only.",
        input_schema=TRACKING_LIST_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("tracking-readonly",),
    ),
    ToolDefinition(
        name="keepa.tracking_get",
        command="tracking.get",
        description="Read tracking details for one ASIN.",
        input_schema=TRACKING_GET_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("tracking-readonly",),
    ),
    ToolDefinition(
        name="keepa.tracking_notifications",
        command="tracking.notifications",
        description="Read tracking notifications without exposing tracking write tools.",
        input_schema=TRACKING_NOTIFICATIONS_SCHEMA,
        output_schema=MCP_ENVELOPE_OUTPUT_SCHEMA,
        groups=("tracking-readonly",),
    ),
)


_TOOL_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}


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


def list_mcp_tools(*, groups: set[str] | None = None, toolsets: str | list[str] | tuple[str, ...] | set[str] | None = None) -> list[dict[str, Any]]:
    tools = TOOL_DEFINITIONS
    if groups is None:
        groups = resolve_toolset_groups(toolsets)
    if groups:
        tools = tuple(tool for tool in tools if groups.intersection(tool.groups))
    return [tool.to_mcp_tool() for tool in tools]


def get_tool_definition(name: str) -> ToolDefinition | None:
    return _TOOL_BY_NAME.get(name)


def tool_params_to_command_params(tool: ToolDefinition, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    params = dict(arguments or {})
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
    allowed = set(tool.input_schema.get("properties") or {})
    required = set(tool.input_schema.get("required") or [])
    errors: list[str] = []
    for key in arguments:
        if key not in allowed:
            errors.append(f"unsupported argument: {key}")
    for key in sorted(required):
        if key not in arguments:
            errors.append(f"missing required argument: {key}")
    if tool.name in {"keepa.finder_query", "keepa.deals_query"} and "selection" not in arguments and "selection_file" not in arguments:
        errors.append("one of selection or selection_file is required")
    if tool.name == "keepa.products_get" and arguments.get("asin") and arguments.get("code"):
        errors.append("asin and code cannot be combined")
    if tool.name == "keepa.products_compare" and len(arguments.get("asin") or []) < 2:
        errors.append("asin must contain at least two ASINs")
    if tool.name == "keepa.workflow_plan":
        name = str(arguments.get("name") or "")
        if name == "category-research" and not arguments.get("term"):
            errors.append("term is required for category-research")
        if name == "product-research" and not arguments.get("asin"):
            errors.append("asin is required for product-research")
    if tool.name == "keepa.research_graph_merge" and not arguments.get("input") and not arguments.get("graph"):
        errors.append("one of input or graph is required")
    return errors


def tool_names() -> list[str]:
    return [tool.name for tool in TOOL_DEFINITIONS]
