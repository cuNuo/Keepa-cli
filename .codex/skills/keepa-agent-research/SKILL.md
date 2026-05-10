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
- `keepa.finder_query`
- `keepa.audit_cost`

## Read Order

For each product, read in this order:

1. `agent_brief`: compact facts, risk codes, missing data, and recommended next actions.
2. `risk_taxonomy`: machine-readable risk enum with severity and evidence paths.
3. `research_graph`: product, brand, category, seller, and variation entities.
4. `selection_signals`: demand, competition, price stability, content quality.
5. `data_quality` and `evidence_index`: missing fields and where to inspect evidence.

Use `risk_taxonomy.known_codes` as the stable enum: `data_missing`, `price_unstable`, `rank_declining`, `low_review_count`, `offer_competition_high`, `buybox_missing`, `category_mismatch`.

## Follow-Up Rules

Use `next_actions[*].tool` and `params` for Agent execution. Treat `cli` as human display only.

Only request `offers`, `rating`, or `buybox` when `data_quality`, `risk_taxonomy`, or the user's goal requires it. Rating is usually better validated from the live page when the user's Agent can browse.

For large outputs, prefer `--view summary`, `--fields`, or `--chunks-dir` instead of loading raw Keepa bodies.

## Evaluation

Use `tests/agent_eval_fixtures/` for semantic checks. Good specs should assert risk codes, graph entity counts, next actions, and evidence paths, not only `ok=true` or field presence.
