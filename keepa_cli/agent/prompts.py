"""
keepa_cli/agent/prompts.py
文件说明：定义 Keepa MCP prompts，给 Agent 提供稳定研究起手式。
主要职责：暴露 prompts/list 与 prompts/get 的静态契约，不访问 Keepa API。
依赖边界：只返回文本模板，不执行命令、不读取凭据。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    description: str
    arguments: tuple[dict[str, Any], ...]
    template: str

    def to_mcp_prompt(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": list(self.arguments),
        }

    def render(self, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        values = {key: "" for key in self.argument_names()}
        values.update({str(key): value for key, value in dict(arguments or {}).items()})
        text = self.template.format(**values)
        return {
            "description": self.description,
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text.strip() + "\n"},
                }
            ],
        }

    def argument_names(self) -> list[str]:
        return [str(argument["name"]) for argument in self.arguments]


PROMPT_DEFINITIONS: tuple[PromptDefinition, ...] = (
    PromptDefinition(
        name="keepa.product_research",
        description="Plan and run a token-safe single product research workflow.",
        arguments=(
            {"name": "asin", "description": "Target ASIN.", "required": True},
            {"name": "domain", "description": "Keepa domain code, usually US.", "required": False},
            {"name": "goal", "description": "Research goal such as deal, audit, or content.", "required": False},
        ),
        template="""
Research ASIN {asin} on domain {domain}.

Use this order:
1. Read `keepa://zread/wiki/current` or `keepa://zread/wiki/toc` if you need project context.
2. Call `keepa.workflow_plan` with name `product-research`, then inspect its budget and confirmation flags.
3. Prefer `keepa.products_get` with `full=true`, `agent_view=true`, `view=research`, `stats_window=0`, and explicit temporal windows.
4. Do not request `rating`, `offers`, or `buybox` unless the returned `data_quality` or `next_actions` says it is needed.
5. Return a concise decision brief with data quality, risk taxonomy, temporal takeaways, evidence references, and next safe action.

Goal: {goal}
""",
    ),
    PromptDefinition(
        name="keepa.category_research",
        description="Discover category candidates, build a Finder scaffold, and avoid implicit token spend.",
        arguments=(
            {"name": "term", "description": "Category search term.", "required": True},
            {"name": "domain", "description": "Keepa domain code, usually US.", "required": False},
            {"name": "hydrate_top", "description": "Optional explicit top-N hydration count.", "required": False},
        ),
        template="""
Research category candidates for `{term}` on domain {domain}.

Use this order:
1. Call `keepa.workflow_plan` with name `category-research`, term `{term}`, domain `{domain}`, and hydrate_top `{hydrate_top}`.
2. Call `keepa.categories_search` with a fixture or dry_run first when possible.
3. Generate a local Finder scaffold with `keepa.categories_finder_selection` for the best candidate category.
4. Do not call `keepa.categories_products` live unless the user explicitly accepts the 50-token Best Sellers cost.
5. Summarize candidate categories, selected category rationale, Finder scaffold parameters, budget ledger, and next actions.
""",
    ),
    PromptDefinition(
        name="keepa.deal_compare",
        description="Compare multiple ASINs using Agent-safe deal views and explainable selection signals.",
        arguments=(
            {"name": "asins", "description": "Comma-separated ASIN list.", "required": True},
            {"name": "domain", "description": "Keepa domain code, usually US.", "required": False},
        ),
        template="""
Compare these ASINs on domain {domain}: {asins}

Use this order:
1. Call `keepa.audit_cost` for the planned compare request.
2. Call `keepa.products_compare` with `view=deal`, `full=true`, and conservative temporal windows.
3. Review `selection_signals`, `risk_taxonomy`, `data_quality`, and `research_graph`.
4. If offer details are missing, report the structured next_action rather than guessing.
5. Return a ranked comparison table plus evidence-backed caveats. Do not invent scores that are not in the response.
""",
    ),
    PromptDefinition(
        name="keepa.project_onboarding",
        description="Use zread and MCP resources to understand the Keepa-cli project before editing.",
        arguments=(),
        template="""
Understand this Keepa-cli repository before making changes.

Use this order:
1. Read `keepa://zread/wiki/current`.
2. Read `keepa://zread/wiki/toc` and choose only the relevant page resources.
3. Use `keepa.docs_index` or `keepa.docs_read` only if your client cannot call MCP resources.
4. Check `keepa://schema/products-agent-view`, `keepa://fixtures/manifest`, and `keepa://evidence/recent` when changing Agent contracts.
5. Summarize the relevant architecture, exact files to edit, required tests, and risks before implementing.
""",
    ),
    PromptDefinition(
        name="keepa.research_agent_start",
        description="Start an offline-first Keepa research Agent workflow with policy, target resolution, context query, planning, and graph merge.",
        arguments=(
            {"name": "query", "description": "User research query, ASIN, category term, seller id, fixture name, or evidence keyword.", "required": True},
            {"name": "domain", "description": "Keepa domain code, usually US.", "required": False},
            {"name": "goal", "description": "Research goal such as product, category, deal, seller, audit, or report.", "required": False},
        ),
        template="""
Start a Keepa research Agent workflow for `{query}` on domain {domain}. Goal: {goal}.

Use this order:
1. Read `keepa://context/policy` or call `keepa.context_policy`.
2. Call `keepa.resolve_research_target` with query `{query}` and domain `{domain}`.
3. Call `keepa.query_research_context` with the primary resolved target before live Keepa calls.
4. If execution is needed, call `keepa.workflow_plan` and inspect token estimates and confirmation flags.
5. Prefer fixture, dry_run, from_cache, and local resources before any live call.
6. Execute only the minimum required tools, then merge outputs with `keepa.research_graph_merge`.
7. Summarize risk taxonomy, research graph entities, evidence links, missing data, and low-token follow-up actions.
""",
    ),
)


_PROMPT_BY_NAME = {prompt.name: prompt for prompt in PROMPT_DEFINITIONS}


def list_mcp_prompts() -> list[dict[str, Any]]:
    return [prompt.to_mcp_prompt() for prompt in PROMPT_DEFINITIONS]


def get_mcp_prompt(name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
    prompt = _PROMPT_BY_NAME.get(name)
    if prompt is None:
        raise ValueError(f"unknown MCP prompt: {name}")
    provided = set(arguments or {})
    required = {argument["name"] for argument in prompt.arguments if argument.get("required")}
    missing = sorted(str(name) for name in required - provided)
    if missing:
        raise ValueError(f"missing prompt arguments: {', '.join(missing)}")
    return prompt.render(arguments)


def prompt_names() -> list[str]:
    return [prompt.name for prompt in PROMPT_DEFINITIONS]
