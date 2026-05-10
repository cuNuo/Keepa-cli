---
name: keepa-agent-research
description: Run Keepa-cli Agent/MCP product research workflows with fixtures, risk taxonomy, research graph, category discovery, product compare, offer-gap decisions, and token-safe follow-up planning. Use when an agent needs to research Amazon/Keepa products, compare ASINs, derive selection signals, or plan low-token Keepa API calls.
---

# Keepa Agent Research

Use this skill for Agent-first Amazon product research with the local `kc` / `keepa-cli` project.

## Start Safe

Prefer fixture, dry-run, or MCP session cache before any live Keepa request:

```powershell
kc --json doctor
kc --json capabilities
kc --mcp
```

Live calls require explicit user approval when they may cost many tokens. Never print tokens, and never commit `evidence/runtime-logs/`.

## Core Workflow

For keyword/category research:

```powershell
kc --json categories search "home kitchen" --domain US --fixture category_search_home.json
kc --json categories finder-selection 1055398 --domain US --sales-rank-max 15000 --min-reviews 100
kc --json categories products 1055398 --domain US --dry-run
kc --json research-graph merge category.json compare.json seller.json --root agent_selection_research
```

For product research:

```powershell
kc --json products get B0D8W1YVBX --domain US --full --agent-view --view summary --fixture product_B0D8W1YVBX_agent_eval.json
kc --json products compare B0D8W1YVBX B0EVALCMP1 B0EVALCMP2 --domain US --full --view deal --fixture products_compare_agent_eval.json
```

With MCP, call structured tools instead of CLI strings:

- `keepa.products_get`
- `keepa.products_compare`
- `keepa.categories_search`
- `keepa.categories_products`
- `keepa.categories_finder_selection`
- `keepa.finder_query`
- `keepa.deals_query`
- `keepa.sellers_get`
- `keepa.bestsellers_get`
- `keepa.topsellers_list`
- `keepa.workflow_plan`
- `keepa.research_graph_merge`
- `keepa.research_brief_export`

Use `tools/list` with `toolset=research` by default. Switch to `audit` for `keepa.audit_cost` and cassette tools, `reports` for local report/browse builders, and `tracking-readonly` only for read-only tracking state. Add `profile=offline_fixture_only` or `profile=dry_run_default` during early research; inactive tools include `x-keepa.active=false`, and `tools/call` returns `inactive_tool` before service execution when a profile disallows a tool.

Use `resources/list` before loading long docs. Stable resources are `keepa://context/policy`, `keepa://schema/products-agent-view`, `keepa://fixtures/manifest`, `keepa://guides/cassette-promotion`, and `keepa://evidence/recent`. Use `resources/templates/list` to discover `keepa://schema/{name}`, `keepa://fixtures/{name}`, `keepa://workflow/{encoded_params}/policy`, `keepa://research/{cache_key}`, `keepa://research/{cache_key}/brief`, `keepa://research/{cache_key}/graph`, `keepa://graphs/{root}`, `keepa://chunk/{encoded_path}`, and `keepa://output/{encoded_path}`. Use `keepa://workflow/{encoded_params}/policy` to read compact workflow execution policy from base64url JSON workflow params, `keepa://research/{cache_key}` to audit same-session cached results, `keepa://research/{cache_key}/brief` to reload an exported brief, and `keepa://graphs/{root}` to audit graph sources before writing conclusions. For tool results with `mcp_resource_manifest`, load `keepa://chunk/...` or `keepa://output/...` only when the summary is insufficient.

## Research Agent Start

For a general research Agent, start with policy and target resolution before any product/category/deals call:

1. Read `keepa://context/policy` or call `keepa.context_policy`.
2. Call `keepa.resolve_research_target` with the user's raw query and domain.
3. Call `keepa.query_research_context` with the primary resolved target.
4. Only then call `keepa.workflow_plan` and execute the minimum required research tools.
5. Merge graph-bearing outputs with `keepa.research_graph_merge`, then export the final Agent handoff with `keepa.research_brief_export`.

`tools/list` supports `allow_tools`, `exclude_tools`, and `profile`. Use these filters to expose only the current workflow's tools when the client allows filtered tool discovery. Prefer `profile=offline_fixture_only` before live research; inactive tools are marked in discovery and return `inactive_tool` before service execution if called.

After `keepa.workflow_plan`, read `workflow_policy` before running steps. Supported plans are `category-research`, `product-research`, `report-research`, and `tracking-audit`. Use `workflow_policy.tool_discovery.params` for the next `tools/list`, start with the recommended profile, follow `profile_switch_points`, and only add `yes=true` for a confirmation step after the user approves that exact step. Reuse `cache_key` or `from_cache` according to `workflow_policy.cache_policy` before repeating a request. Use `report-research` for local graph/report/brief/browse handoff, and `tracking-audit` only for read-only tracking inspection.

Use `keepa.research_agent_start` prompt when a client supports MCP prompts. It encodes the policy -> resolve -> context -> plan -> execute -> graph merge order.

## Read Order

For each product, read in this order:

1. `agent_brief`: compact facts, risk codes, missing data, and recommended next actions.
2. `risk_taxonomy`: machine-readable risk enum with severity and evidence paths.
3. `research_graph`: product/category/selection/deal/seller entities and typed edges.
4. `selection_signals`: demand, competition, price stability, content quality.
5. `data_quality` and `evidence_index`: missing fields and where to inspect evidence.

Use `risk_taxonomy.known_codes` as the stable enum: `data_missing`, `price_unstable`, `rank_declining`, `low_review_count`, `offer_competition_high`, `buybox_missing`, `category_mismatch`.

## Follow-Up Rules

Use `next_actions[*].tool` and `params` for Agent execution. Treat `cli` as human display only.

Only request `offers`, `rating`, or `buybox` when `data_quality`, `risk_taxonomy`, or the user's goal requires it. Rating is usually better validated from the live page when the user's Agent can browse.

For large outputs, prefer `--view summary`, `--fields`, or `--chunks-dir` instead of loading raw Keepa bodies.

After category discovery, compare, and seller/deals steps, merge graphs with `research_graph.merge` / `keepa.research_graph_merge` so downstream reports and memory read one deduplicated `category -> product -> seller/deal` graph. Read `summary.diagnostics` first; duplicate/orphan/conflict counts indicate whether the Agent should inspect full graph sources before writing conclusions.

Use `research_brief.export` / `keepa.research_brief_export` after graph merge or multi-payload research. The brief gives downstream research Agents a stable `decision_summary`, `risk_summary`, `entity_graph_summary`, `follow_up_plan`, `evidence_links`, and `recommended_read_order` without rereading every raw payload.

Use `reports.build` on the merged graph JSON when a human-readable or downstream relationship report is needed. Markdown includes entity and relationship tables; JSON includes `research_graph_report`.

## Cassette Promotion

After an approved live request, convert the response into regression assets before reusing it:

```powershell
kc --json cassettes promote evidence/runtime-logs/live-response.json --name product_B0EXAMPLE_full
kc --json cassettes promote-and-verify evidence/runtime-logs/live-response.json --name product_B0EXAMPLE_full --run-eval
```

Prefer `promote-and-verify` / `keepa.cassettes_promote_and_verify` for research Agent fixture curation. It sanitizes secrets, writes synchronized fixtures under `tests/fixtures` and `keepa_cli/fixtures`, updates `evidence/manifest.csv`, checks fixture parity, and can run Agent eval fixtures. Never commit raw runtime logs.

## Evaluation

Use `tests/agent_eval_fixtures/` for semantic checks. Good specs should assert risk codes, graph entity counts, executable next actions, MCP resource manifests, session budget ledgers, and evidence paths, not only `ok=true` or field presence.
