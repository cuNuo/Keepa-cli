---
name: keepa-cli
description: Use the Keepa CLI safely from Codex for offline-first product, finder, deals, seller, graph, tracking, batch, report, cache, and cost-audit workflows.
---

# Keepa CLI Companion

Use this skill when a Codex thread needs to operate the local `keepa-cli` / `kc` tool.

## First Checks

Run these from any repo before live work:

```powershell
kc --json doctor
kc --json capabilities
```

If `kc` is not on PATH inside this repo, use:

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
```

## Auth

Prefer fixture or `--dry-run` mode first. Live Keepa calls require `KEEPA_API_KEY` or a local config token:

```powershell
kc --json config set-token YOUR_64_CHARACTER_KEEPA_KEY
kc --json doctor
```

Never print or commit tokens. CLI output should redact token-like fields.

## Safe Read Path

Start with discovery and dry-run:

```powershell
kc --json domains list
kc --json products get B001GZ6QEC --domain US --history 0 --fixture product_B001GZ6QEC.json
kc --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run
```

For Agent sessions, prefer MCP when the client supports it:

```powershell
kc --mcp
```

Use `keepa.products_get` for single-product research and `keepa.products_compare` for multi-ASIN deal comparison. Product Agent views include `agent_brief`, `risk_taxonomy`, `research_graph`, `data_quality`, `selection_signals`, `next_actions`, and `evidence_index`; read those before loading raw output or chunks.

MCP `tools/list` defaults to `toolset=research`. Use `toolset=audit` for `keepa.audit_cost` and cassette tools, `toolset=reports` for local report/browse/SVG figure/brief export tools, `toolset=tracking-readonly` for read-only tracking, and `toolset=all` only when debugging schema discovery. Add `profile=offline_fixture_only`, `dry_run_default`, `live_read_allowed`, `tracking_readonly`, or `fixture_curation` when a client supports staged tool discovery. Inactive tools are marked with `x-keepa.active=false`, and `tools/call` with the same profile returns `inactive_tool` before service execution. Research tools include `keepa.categories_finder_selection`, `keepa.research_graph_merge`, and `keepa.research_brief_export`.

MCP `resources/list` exposes `keepa://context/policy`, `keepa://schema/products-agent-view`, `keepa://schema/risk-taxonomy`, `keepa://schema/workflow-runtime-contract`, `keepa://fixtures/manifest`, `keepa://guides/cassette-promotion`, `keepa://evidence/recent`, and `keepa://workflow/runtime-contract`. `resources/templates/list` exposes `keepa://schema/{name}`, `keepa://fixtures/{name}`, `keepa://workflow/{encoded_params}/policy`, `keepa://research/{cache_key}`, `keepa://research/{cache_key}/brief`, `keepa://research/{cache_key}/graph`, `keepa://research/{cache_key}/figures`, `keepa://graphs/{root}`, `keepa://chunk/{encoded_path}`, and `keepa://output/{encoded_path}`. Use `keepa://schema/risk-taxonomy` when an Agent needs to validate risk codes, severity, and evidence paths without loading the full product schema; use `keepa://workflow/runtime-contract` to discover resolver-enabled tools and follow its `schema_resource_uri` for validation, `keepa://workflow/{encoded_params}/policy` to read a compact `workflow_policy` from base64url JSON workflow params, `keepa://research/{cache_key}` to audit same-session cached results, `keepa://research/{cache_key}/brief` to reload an exported brief, `keepa://research/{cache_key}/figures` to generate report-ready SVG resources from cached data, and `keepa://graphs/{root}` to audit graph sources before writing conclusions. If a tool text fallback includes `mcp_resource_manifest`, load `keepa://chunk/...` or `keepa://output/...` with `resources/read` instead of asking for the whole raw body again.

For general research Agents, read `keepa://context/policy`, call `keepa.resolve_research_target`, then call `keepa.query_research_context` before running live-capable product/category tools. `tools/list` accepts `allow_tools`, `exclude_tools`, and `profile` filters for small per-workflow schemas; use `profile=offline_fixture_only` when the Agent must not execute live-capable tools.

`workflow.plan` returns `workflow_inputs`, `artifacts`, `resource_templates`, and `workflow_policy` for MCP execution control. It supports `category-research`, `product-research`, `report-research`, and `tracking-audit`. Read it before running steps: apply `tool_discovery.params` to `tools/list`, follow `profile_switch_points`, treat `inactive_tools` as deliberate stage gates, connect steps with `input_refs` / `artifact_refs`, and only add `yes=true` after explicit confirmation for the listed `confirmation_policy.step_ids`. MCP `tools/call` accepts `resource_uri`, `resource_uris`, `artifact`, `artifacts`, `workflow_inputs`, and `workflow_context` to resolve prior outputs into concrete params; it also understands `artifact.output.path` / `artifact.data.output.path` and nested `workflow_context.steps` / `outputs` / `results` for local graph -> brief -> reports chains. Inspect `data.workflow_resolution` or `error.kind=missing_inputs`. `report-research` is local-only through the `reports` toolset; `tracking-audit` is read-only through `tracking-readonly`.

For a copyable Agent MCP client example:

```powershell
.\.venv\Scripts\python.exe scripts\mcp_agent_workflow_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_tracking_audit_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json --save-summary evidence\runtime\mcp-report-summary.json
```

The scripts use a single `python -m keepa_cli --mcp` stdio session to run `workflow.plan -> resource_uri -> risk schema validation -> graph/brief/report`, tracking-readonly audit, and local report-research handoff with fixtures only. `--save-summary` writes the compact integration summary to a controlled path for Agent pipelines.

For local workflows:

```powershell
kc --json batch asins asins.txt --domain US --dry-run --out batch.json
kc --json reports build --input batch.json --format markdown --out report.md
kc --json browse snapshot --input batch.json --out-dir keepa-browse
kc --json figures research --input batch.json --out-dir keepa-figures
```

`browse.snapshot` can render rows from raw product bodies or `research_graph` product nodes. `figures research` emits one SVG plus source JSON with product comparison, real price/rank history lines when present, temporal window heatmaps, multi-ASIN normalized small multiples, risk codes, and graph entity summaries. Through MCP, `keepa.figures_research` and `keepa://research/{cache_key}/figures` expose SVG as `image/svg+xml` `keepa://output/...` resources suitable for reports. `reports build` embeds that SVG automatically for markdown/json unless `--no-figures` is set.

`reports build` can also consume a merged research graph JSON and emit entity/relationship report sections:

```powershell
kc --json research-graph merge category.json compare.json seller.json --root agent_selection_research --out graph.json
kc --json research brief graph.json --title "Agent selection brief" --out brief.json
kc --json reports build --input graph.json --format markdown --out graph-report.md
```

## Tracking And Writes

Tracking can reduce Keepa token refill rate. Use dry-run first and require explicit user approval before live writes:

```powershell
kc --json tracking add --tracking-file tracking.json --dry-run
kc --json tracking webhook https://example.invalid/hook --dry-run
```

Only run live `tracking add/remove/remove-all/webhook` with `--yes` after the user approves the exact action.

## Cost And Cache Audit

```powershell
kc --json audit cost products.get --param asin=B001GZ6QEC
kc --json cache explain --input envelope.json --command products.get
```

## Agent Semantics

`risk_taxonomy.known_codes` is the stable risk enum. Treat `data_missing`, `price_unstable`, `rank_declining`, `low_review_count`, `offer_competition_high`, `buybox_missing`, and `category_mismatch` as machine-readable codes, not prose labels.

`research_graph` exposes product, brand, category, seller, variation, selection, deal, and ranking nodes with typed edges. Use it for reports, comparison graphs, and downstream entity memory.

Merge multi-step research outputs locally:

```powershell
kc --json research-graph merge category.json compare.json seller.json --root agent_selection_research
```

This command does not call Keepa. It recursively extracts `research_graph` objects, dedupes nodes/edges, and returns a merged graph plus sources, source weights, duplicate/orphan/conflict diagnostics, and data quality.

Export the final Agent handoff with `research brief` / `keepa.research_brief_export` after graph merge or multi-payload research. It returns `decision_summary`, `risk_summary`, `entity_graph_summary`, `follow_up_plan`, `evidence_links`, and `recommended_read_order` without rereading raw payloads.

Do not commit `evidence/runtime-logs/`. Sanitize and promote live responses to fixtures before using them in tests:

```powershell
kc --json cassettes promote evidence/runtime-logs/live-response.json --name product_B0EXAMPLE_full
kc --json cassettes promote-and-verify evidence/runtime-logs/live-response.json --name product_B0EXAMPLE_full --run-eval
```

Prefer `promote-and-verify` / `keepa.cassettes_promote_and_verify` when turning a live sample into regression assets. It sanitizes, writes synchronized fixtures, checks fixture parity, and can run Agent eval fixtures in one local workflow.

## Raw Escape Hatch

Use raw request only for bounded inspection. Prefer `--dry-run` unless the user explicitly requests a live call:

```powershell
kc --json request get /product --param domain=1 --param asin=B001GZ6QEC --dry-run
```

Do not run raw non-GET live requests without explicit approval.
