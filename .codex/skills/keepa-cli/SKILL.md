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

MCP `tools/list` defaults to `toolset=research`. Use `toolset=audit` for `keepa.audit_cost` and cassette tools, `toolset=reports` for local report/browse tools, `toolset=tracking-readonly` for read-only tracking, and `toolset=all` only when debugging schema discovery. Research tools include `keepa.categories_finder_selection` and `keepa.research_graph_merge`.

MCP `resources/list` exposes `keepa://schema/products-agent-view`, `keepa://fixtures/manifest`, `keepa://guides/cassette-promotion`, and `keepa://evidence/recent`. `resources/templates/list` exposes `keepa://schema/{name}`, `keepa://fixtures/{name}`, `keepa://chunk/{encoded_path}`, and `keepa://output/{encoded_path}`. If a tool text fallback includes `mcp_resource_manifest`, load `keepa://chunk/...` or `keepa://output/...` with `resources/read` instead of asking for the whole raw body again.

For local workflows:

```powershell
kc --json batch asins asins.txt --domain US --dry-run --out batch.json
kc --json reports build --input batch.json --format markdown --out report.md
kc --json browse snapshot --input batch.json --out-dir keepa-browse
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

Do not commit `evidence/runtime-logs/`. Sanitize and promote live responses to fixtures before using them in tests:

```powershell
kc --json cassettes promote evidence/runtime-logs/live-response.json --name product_B0EXAMPLE_full
```

## Raw Escape Hatch

Use raw request only for bounded inspection. Prefer `--dry-run` unless the user explicitly requests a live call:

```powershell
kc --json request get /product --param domain=1 --param asin=B001GZ6QEC --dry-run
```

Do not run raw non-GET live requests without explicit approval.
