<p align="center">
  <h1 align="center">Keepa CLI</h1>
  <p align="center">Agent-first Keepa API CLI for product research, safe automation, and MCP-native workflows.</p>
</p>

<p align="center">
  <a href="https://github.com/cuNuo/Keepa-cli/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cuNuo/Keepa-cli/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776ab"></a>
  <a href="https://www.npmjs.com/package/@cunuo/keepa-cli"><img alt="npm" src="https://img.shields.io/badge/npm-%40cunuo%2Fkeepa--cli-cb3837"></a>
  <a href="https://cunuo.github.io/Keepa-cli/"><img alt="Docs" src="https://img.shields.io/badge/docs-pages-2563eb"></a>
  <a href="#agent-mode"><img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-6d28d9"></a>
  <a href="https://zread.ai/cuNuo/Keepa-cli"><img alt="zread" src="https://img.shields.io/badge/docs-zread-14b8a6"></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-111827"></a>
</p>

<p align="center">
  <a href="#installation">Installation</a>
  · <a href="#configure-your-keepa-token">Configure Token</a>
  · <a href="#tui">TUI</a>
  · <a href="#agent-mode">Agent Mode</a>
  · <a href="./README.zh-CN.md">中文</a>
</p>

Keepa CLI wraps Keepa API workflows into a stable command-line surface for agents and humans. It is offline-first by default: dry-runs and fixtures do not call Keepa or spend tokens. Live requests require an explicit Keepa token.

Use it when you need reproducible Amazon product research, category discovery, deal comparison, seller checks, tracking reads, local reports, or Agent pipelines that must account for token cost and evidence provenance.

## Features

- Equivalent `keepa-cli` and `kc` entrypoints.
- Stable `--json` envelopes for automation.
- JSON Lines `--stdio` protocol and MCP `--mcp` server for long-running agent sessions.
- Prompt-toolkit TUI with slash completion, command history, a bottom status bar, and copyable output.
- Fixture/offline mode, dry-run requests, token budget hints, and secret redaction.
- Safe `/graphimage` handling with explicit `--out` for binary PNG output.
- Finder, Deals, Seller, Best Sellers, Top Sellers, Tracking, and webhook command families.
- Local browse snapshots, batch ASIN plans, workflow templates, markdown/JSON/CSV reports, SQLite response cache, cache explain, and cost audit.
- Release gate for compile, tests, fixture sync, Python/Node smoke, and npm pack dry-run.

## Installation

For local development:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\kc.exe --json doctor
```

For the npm wrapper target:

```powershell
npm install -g @cunuo/keepa-cli
kc --json doctor
```

The npm wrapper calls Python. Point it at this project's virtual environment when needed:

```powershell
$env:KEEPA_CLI_PYTHON="D:\github\Keepa-cli\.venv\Scripts\python.exe"
kc --json doctor
```

## Configure Your Keepa Token

Option 1: store the token in the local config file. CLI output is redacted. Keepa access keys are validated locally as 64 visible ASCII characters before they are saved.

```powershell
kc --json config set-token YOUR_KEEPA_64_CHARACTER_ACCESS_KEY
kc --json doctor
```

Default config paths:

- Windows: `%APPDATA%\keepa-cli\config.toml`
- macOS / Linux: `~/.config/keepa-cli/config.toml`

Use a custom config path:

```powershell
kc --json config set-token YOUR_KEEPA_TOKEN --path .\config.local.toml
$env:KEEPA_CLI_CONFIG=(Resolve-Path .\config.local.toml)
kc --json doctor
```

Option 2: use an environment variable. It takes precedence over config files.

```powershell
$env:KEEPA_API_KEY="YOUR_KEEPA_TOKEN"
kc --json doctor
```

Inspect config safely and adjust the per-request token budget hint for higher Keepa plans:

```powershell
kc --json config init --dry-run
kc --json config show
kc --json config set-max-tokens 250
```

## Language

English is the default UI language. Switch the TUI to Chinese with:

```powershell
kc --json config set-language zh
```

Switch back to English:

```powershell
kc --json config set-language en
```

## Quick Start

Fixture-backed commands do not spend live tokens:

```powershell
kc --json products get B001GZ6QEC --domain US --history 0 --fixture product_B001GZ6QEC.json
kc --json history trend B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json
kc --json tokens status --fixture token_status.json
```

For a single-ASIN live product detail request, prefer the low-cost full preset. It asks Keepa for history, max-window stats (`stats=0`), videos, and A+ metadata without enabling offer-page collection or the extra `rating=1` refresh:

```powershell
kc --json products get B001GZ6QEC --domain US --full
```

For large live responses, write the full body to a file and keep the terminal envelope small:

```powershell
kc --json products get B001GZ6QEC --domain US --full --out .\product-full.json
```

For Agent ingestion, prefer the compact product view. It keeps identity, category, pricing, demand, rating, offers, media, A+ content, logistics, stats summaries, and bounded history samples in stable fields while omitting raw `csv` arrays from stdout:

```powershell
kc --json products get B001GZ6QEC --domain US --full --agent-view --history-limit 10 --out .\product-full.json
```

Use profiles and field selection to control context size:

```powershell
kc --json products get B001GZ6QEC --domain US --full --agent-view --view summary
kc --json products get B001GZ6QEC --domain US --full --agent-view --fields identity,pricing,demand,rating
kc --json products get B001GZ6QEC --domain US --full --agent-view --view deal --chunks-dir .\agent-chunks
kc --json products compare B001GZ6QEC B08N5WRWNW --domain US --full --view deal
kc --json research-graph merge .\category.json .\compare.json .\seller.json --root agent_selection_research --out .\research-graph.json
```

Agent profiles are `summary`, `research`, `deal`, and `audit`. Start from `agent_brief` for a compact decision layer, then use `evidence_index` to jump to deeper JSON paths when the Agent needs proof. `agent_brief` includes both series-first `temporal_takeaways` and window-first `temporal_by_window`, so an Agent can compare 7/30/90/180/365 day changes across price, rank, reviews, rating, and offer count without parsing raw Keepa `csv`. Product views also include `data_quality`, `next_actions`, `temporal_features`, and `selection_signals` for deeper audit and research workflows.

Token budgets include component-level hints. Product requests start at `1 token * product count`; explicit `--rating` and `--buybox` are budgeted as additional product-level costs, `--offers` is budgeted as Keepa offer pages (`6 tokens * ceil(offers / 10) * product count`), and `--update 0` is tracked as a worst-case live refresh.

Keepa account tokens refill continuously according to your plan. A `429` / `not_enough_token` response is not treated as a permanent rejection: the error details include `retry_after_ms`, `retry_after_seconds`, and `token_refill_guidance` when Keepa returns refill metadata. High-cost confirmation errors also include `token_refill_guidance` with `tokens.status`, wait/retry, request-scope reduction, cache, fixture, and dry-run next actions.

Use explicit flags when you need tighter history windows or specialized fields:

```powershell
kc --json products get B001GZ6QEC --domain US --history 1 --stats 180 --videos 1 --aplus 1 --days 365 --dry-run
kc --json products by-code 9780786222728 --domain US --code-limit 5 --dry-run
kc --json products summary B0D8W1YVBX --domain US --fixture product_agent_view_B0TEST.json
kc --json products get B001GZ6QEC --domain US --full --stats-window 365 --temporal-window-days 30 --temporal-window-days 180,365 --agent-view
```

Use dry-run for high-cost requests:

```powershell
kc --json categories search "home kitchen" --domain US --fixture category_search_home.json
kc --json categories finder-selection 1055398 --domain US --out .\finder-category-1055398.json
kc --json categories products 172282 --domain US --dry-run --limit 25
kc --json categories products 172282 --domain US --limit 25 --hydrate-top 3 --yes
kc --json bestsellers get 172282 --domain US --dry-run
kc --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
```

`categories search` enriches category results with `category_candidates` and structured `next_actions`. Each action keeps the human `command` string and also exposes `tool`, `params`, `cli`, `estimated_tokens`, and `requires_confirmation` for safe Agent execution. `categories finder-selection` is local-only and writes a Product Finder selection scaffold from a category id. `categories products` uses Keepa Best Sellers and costs 50 tokens for live requests; `--hydrate-top N` is never enabled by default and adds one product-summary token per hydrated ASIN.

Graph Image live downloads must write to a file:

```powershell
kc --json graphs image B09YNQCQKR --domain US --width 800 --height 400 --range 365 --param amazon=1 --dry-run
```

## Local Workflows

Build an offline batch plan, report, and local HTML browse snapshot:

```powershell
kc --json batch asins .\asins.txt --domain US --dry-run --out .\batch.json
kc --json reports build --input .\batch.json --format markdown --out .\report.md
kc --json browse snapshot --input .\batch.json --out-dir .\keepa-browse
kc --json figures research --input .\batch.json --out-dir .\keepa-figures
```

Use built-in workflow templates:

```powershell
kc --json templates list
kc --json templates show finder-basic --out .\finder-basic.json
```

Explain provenance and estimate token cost before live work:

```powershell
kc --json cache explain --input .\batch.json --command products.get
kc --json cache explain-key --endpoint /product --param domain=1 --param asin=B001GZ6QEC
kc --json cache stats
kc --json cache inspect sqlite:<cache-key>
kc --json cache prune-expired --dry-run
kc --json cache clear --dry-run
kc --json audit cost products.get --param asin=B001GZ6QEC
```

Live GET JSON responses are cached in SQLite by default using `cache_ttl_seconds` from config. Dry-run, fixture, binary, POST, and disabled-cache requests are not persisted. Override the cache file for audits with `--cache-path` or `KEEPA_CLI_CACHE_PATH`. Common cacheable live commands also accept `--cache-ttl <seconds>` and `--no-cache`; environment fallbacks remain `KEEPA_CLI_CACHE_TTL_SECONDS` and `KEEPA_CLI_NO_CACHE=1`. `cache explain-key` lets Agents derive the deterministic SQLite cache key from method, endpoint, and sanitized request params; the release gate runs `scripts/check_live_cache_options.py` so new cacheable live CLI commands cannot omit explicit cache controls.

Tracking and webhook write paths stay dry-run by default in examples:

```powershell
kc --json tracking add --tracking-file .\tracking.json --dry-run
kc --json tracking webhook https://example.invalid/keepa --dry-run
```

## TUI

Start the command-first terminal interface:

```powershell
kc
```

The TUI follows the Codex/zread-style CLI pattern:

- `kc ›` stays focused as the bottom composer.
- Typing `/` opens slash completion with arrow-key selection.
- The bottom status bar keeps auth, domain, language, budget, and schema visible.
- Setup is terse: use `/token <64-char Keepa key>`, `/max-tokens 250`, or `/language zh`.
- Command output is normal terminal text, so summaries and full JSON envelopes can be selected and copied.

Force the classic slash TUI:

```powershell
kc tui --classic
```

Piped input automatically uses classic mode:

```powershell
@'
/doctor
/quit
'@ | kc
```

Inspect TUI metadata without launching an interactive UI:

```powershell
kc --json tui
```

## Agent Mode

JSON envelope examples:

```powershell
kc --json capabilities
kc --json domains list
kc --json request get /product --param domain=1 --param asin=B001GZ6QEC --dry-run
kc --json workflow plan category-research --term "home kitchen" --domain US
kc --json workflow plan product-research --asin B0D8W1YVBX --goal deal
kc --json workflow plan report-research --goal deal
kc --json workflow plan tracking-audit --asin B0D8W1YVBX
```

stdio JSON Lines:

```powershell
'{"id":"1","method":"doctor","params":{}}' | kc --stdio
```

MCP JSON-RPC over stdio:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | kc --mcp
'{"jsonrpc":"2.0","id":2,"method":"resources/list","params":{}}' | kc --mcp
'{"jsonrpc":"2.0","id":3,"method":"resources/templates/list","params":{}}' | kc --mcp
'{"jsonrpc":"2.0","id":4,"method":"prompts/list","params":{}}' | kc --mcp
```

MCP defaults to the compact `research` toolset and accepts structured JSON arguments, not CLI strings. `initialize` returns `serverInfo.name=keepa_mcp`; MCP client config aliases may still be named `keepa`, but public tool names no longer carry a `keepa.` prefix. External clients should migrate call names to the new unprefixed names such as `context_policy`, `research_graph_merge`, and `research_brief_export`; old `keepa.*` names are not kept as aliases. Use `tools/list` with `toolset` set to `research`, `docs`, `audit`, `reports`, `tracking-readonly`, or `all` to control context size; `allow_tools` and `exclude_tools` can further narrow the per-workflow schema. `toolset=all` without an explicit `limit` returns an 8-tool starter page headed by `context_policy` plus `nextCursor`; MCP cursors are opaque and cannot be reused across different filters. `profile` can mark tools inactive for a session stage (`offline_fixture_only`, `dry_run_default`, `live_read_allowed`, `tracking_readonly`, `fixture_curation`); `tools/call` returns `inactive_tool` before service execution when a profile disallows a tool. Research tools include context policy, target resolution, local context query, product, category, local Finder scaffold, Finder, Deals, seller, ranking, workflow planning, docs index/read, `research_graph_merge`, and `research_brief_export`; audit tools include cost estimation plus cassette sanitize/promote and `cassettes_promote_and_verify`; reports tools expose graph merge, local report, browse snapshot, SVG figure generation, and brief export builders; tracking exposes read-only tracking plus cost audit. Agent results include `risk_taxonomy` where applicable and a cross-command `research_graph`; tool envelopes include `structuredContent`, compact JSON text fallback, `cache_key`, `cache_hit`, and `budget_ledger`; heavy output fallbacks also include MCP `resource_link` content blocks. Inspector-style protocol regression lives in `tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json`; the official Python MCP SDK adapter comparison lives in `docs/architecture/mcp-python-sdk-adapter-comparison.md`.

The isolated SDK adapter lives in `keepa_cli/agent/mcp_sdk_adapter.py`; run `python scripts/compare_mcp_sdk_adapter_fixture.py` to compare its compatibility handler with the current `--mcp` stdio output, run the same script with `--fixture tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json` for filter/cursor parity, run `python scripts/smoke_mcp_sdk_adapter_client.py` to connect with the official Python MCP SDK `ClientSession`, run `python scripts/check_mcp_sdk_adapter_typed_fixture.py` to map the Inspector fixture into typed SDK calls, and run `python scripts/check_mcp_quality_gate.py --require-sdk` for the aggregated MCP gate. The gate also runs `scripts/check_mcp_output_schema.py` and `scripts/check_mcp_performance_gate.py`, so output schema validation stays out of the hot path while performance stays enforced; CI writes performance artifacts with `--performance-out`, and `scripts/summarize_mcp_performance_history.py` turns several runs into real p95 threshold tightening suggestions. The optional `mcp-sdk` extra enables SDK experiments and the `python -m keepa_cli.agent.mcp_sdk_adapter --stdio` entrypoint, but it does not replace the production stdio entrypoint; before promotion it must keep matching production `toolset/profile/allow_tools/exclude_tools/limit/cursor` filtering and pagination behavior. The SDK adapter keeps `toolset=all` discoverable through cursor pagination, while first pages for tools, resources, resource templates, and prompts are capped to agent starter sets headed by `context_policy`, `keepa://context/policy`, `keepa://toolsets/{toolset}`, and `product_research`. `python scripts/export_mcp_inspector_snapshot.py --check` records a reproducible typed Inspector snapshot without requiring the UI.

Product live-read validation is manual-only: `python scripts/manual_live_product_read.py --asin <ASIN> --json` stays in dry-run mode, while `--yes-live` requires `KEEPA_API_KEY` and emits a redacted token/cache provenance summary instead of the full product body.

MCP resources expose stable reference material without enlarging `tools/list`: `keepa://context/policy`, `keepa://schema/products-agent-view`, `keepa://schema/risk-taxonomy`, `keepa://schema/workflow-runtime-contract`, `keepa://fixtures/manifest`, `keepa://guides/cassette-promotion`, `keepa://evidence/recent`, `keepa://tools/index`, `keepa://prompts/index`, `keepa://zread/wiki/current`, `keepa://zread/wiki/toc`, and `keepa://zread/wiki/pages`. `resources/templates/list` also advertises `keepa://schema/{name}`, `keepa://fixtures/{name}`, `keepa://cache-key/{command}/{encoded_params}`, `keepa://workflow/{encoded_params}/policy`, `keepa://research/{cache_key}`, `keepa://research/{cache_key}/brief`, `keepa://research/{cache_key}/graph`, `keepa://research/{cache_key}/figures`, `keepa://research/{cache_key}/figures/{figure_set}`, `keepa://graphs/{root}`, `keepa://toolsets/{toolset}`, `keepa://tools/{name}`, `keepa://prompts/{name}`, `keepa://asin/{asin}/fixture`, `keepa://evidence/{encoded_logical_path}`, `keepa://zread/wiki/page/{slug_or_file}`, `keepa://chunk/{encoded_path}`, and `keepa://output/{encoded_path}` so Agents can discover resource URI shapes instead of hard-coding them. `keepa://schema/risk-taxonomy` gives external Agents the stable risk enum and evidence-bearing item contract; `keepa://workflow/{encoded_params}/policy` reads the compact `workflow_policy` and step summary from base64url JSON plan params; `keepa://workflow/runtime-contract` now points to `keepa://schema/workflow-runtime-contract` for client-side validation; `keepa://research/{cache_key}` audits a same-session cached result; `keepa://research/{cache_key}/brief` reloads an exported brief; `keepa://research/{cache_key}/figures` generates all SVG figure resources; `keepa://research/{cache_key}/figures/history|compare|audit` generates only one report section's figures; `keepa://graphs/{root}` finds graph summaries in session cache and local fixtures. Large tool responses keep the full payload in `structuredContent`; the text fallback returns a summary plus `mcp_resource_manifest` entries so Agents can load heavy sections only when needed. MCP prompts include product research, category research, deal comparison, project onboarding, and `research_agent_start` playbooks.

Copyable Agent integration example:

```powershell
.\.venv\Scripts\python.exe scripts\mcp_agent_workflow_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_tracking_audit_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json --save-summary evidence\runtime\mcp-report-summary.json
```

These examples start `python -m keepa_cli --mcp` as a stdio server and keep one session alive for cache keys, resource URIs, and budget ledgers. `mcp_agent_workflow_example.py` calls `workflow_plan`, reads `keepa://schema/risk-taxonomy`, executes fixture-backed category products and compare steps through `resource_uri`, validates emitted risk objects, merges the research graph, exports an Agent brief, and builds a JSON report. `mcp_tracking_audit_example.py` demonstrates the `tracking-readonly` toolset/profile boundary and proves tracking write tools are not exposed. `mcp_report_research_example.py` demonstrates the local `reports` toolset by turning an existing graph fixture into graph, brief, browse snapshot, SVG figure resource, and report outputs. All examples support `--save-summary <path>` for controlled Agent pipeline summaries. The shared helper `scripts/mcp_example_support.py` is intentionally standard-library only so other Agents can copy the client pattern without extra dependencies.

`browse.snapshot` reads product rows from raw Keepa product bodies and from `research_graph` product nodes, so merged graphs produce useful HTML even when no raw product rows are present. `figures research` generates SVG resources plus source JSON from product comparison, real price/rank history points when available, temporal window heatmaps, multi-ASIN normalized small multiples, risk taxonomy, and graph entity counts. Use `--figure-set all|history|compare|audit` to control report scope: `all` keeps the backward-compatible overview plus standalone charts, while scoped sets return only the needed history, comparison, or audit figures. `reports build` embeds generated SVG automatically for markdown/json reports unless `--no-figures` is set, and accepts the same `--figure-set`. Through MCP, `figures_research`, `keepa://research/{cache_key}/figures`, and `keepa://research/{cache_key}/figures/{figure_set}` return SVG manifests with `keepa://output/...` resources using `image/svg+xml`, which lets Agents insert stable figures into downstream reports without loading large raw JSON. `reports_build` and `figures_research` are marked as future MCP Tasks/progress candidates; ordinary `tools/call` remains for fixture or small-output use, while large production report generation must wait for `tasks/cancel`, `notifications/progress`, `tasks/result`, and a recoverable `keepa://tasks/{task_id}/result` resource.

Streamable HTTP remains a protocol adapter boundary, not a second business implementation. `StreamableHttpAdapterContract` turns the HTTP fixture into executable adapter cases and routes valid JSON-RPC bodies through the same raw MCP handler while testing Origin, session id, timeout, notification, and error-status mapping.

Contracts:

- [Agent contract](docs/agent-contract.md)
- [MCP Agent tools architecture](docs/architecture/mcp-agent-tools.md)
- [Keepa official API notes](docs/keepa-official-api-notes.md)

Agent-facing result profiles use the same top-level shape where possible: `agent_brief`, `data_quality`, `selection_signals`, `next_actions`, `evidence_index`, and `provenance`. `workflow plan` is local-only and returns `workflow_inputs`, `artifacts`, `resource_templates`, and an execution graph with step dependencies, parallel groups, token budgets, confirmation flags, fixture replay hints, input refs, and artifact refs. It supports `category-research`, `product-research`, `report-research`, and `tracking-audit`. It also includes `workflow_policy` with the recommended MCP `toolset`, session `profile`, allowed/inactive tools, profile switch points, confirmation policy, cache guidance, and a budget ledger seed, so Agents can plan tool discovery and execution without guessing. MCP `tools/call` accepts workflow runtime inputs such as `resource_uri`, `resource_uris`, `artifact`, `artifacts`, `workflow_inputs`, and `workflow_context`; it also scans `workflow_context.steps`, `outputs`, `results`, `step_outputs`, and `previous_outputs`; it resolves same-session `keepa://research/{cache_key}`, `keepa://research/{cache_key}/graph`, output paths, `artifact.output.path`, and inline artifacts into concrete tool params, then returns `workflow_resolution` on success or `missing_inputs` when a required dependency is not available. Read `keepa://workflow/runtime-contract` to discover the exact resolver-enabled tools and accepted runtime sources without loading every tool schema. `keepa://graphs/{root}` remains an audit resource for locating graph sources. `report-research` stays local in the `reports` toolset; `tracking-audit` stays read-only in the `tracking-readonly` toolset. `research-graph merge` can combine category discovery, category products, product compare, deals, and seller outputs into one deduplicated graph for report generation or downstream Agent memory; the merged graph includes source weights, duplicate/orphan/conflict diagnostics, `diff` summaries, and optional `--prefer-source` conflict resolution. `reports build` now reads merged graph JSON directly and adds an entity relationship report section or `research_graph_report` JSON block.

## zread Docs

Stable public docs entry: [GitHub Pages](https://cunuo.github.io/Keepa-cli/). The generated architecture wiki is available at [zread](https://zread.ai/cuNuo/Keepa-cli), with a committed snapshot under `.zread/wiki/`.

Open the generated documentation locally:

```powershell
zread browse
```

Agents and scripts should prefer stdio mode:

```powershell
zread browse --stdio
```

The current local snapshot is indexed by [.zread/wiki/current](.zread/wiki/current) and [.zread/wiki/versions/2026-05-10-215740/wiki.json](.zread/wiki/versions/2026-05-10-215740/wiki.json). Agents can read the same snapshot through `keepa://zread/wiki/current`, `keepa://zread/wiki/toc`, and `keepa://zread/wiki/page/{slug_or_file}`. For local development, regenerate after large architecture changes:

```powershell
zread generate -y --stdio --draft clear --skip-failed
```

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
.\.venv\Scripts\python.exe scripts\install_verify.py --skip-npm-pack
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
git diff --check
```

Smoke checks:

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
node .\bin\keepa-cli.js --json doctor
node .\bin\kc.js --json doctor
npm pack --dry-run --json
```

## Security

- Do not commit Keepa API keys, `.env` files, local caches, or unredacted cassettes.
- Output redacts `key`, `api_key`, `apikey`, `token`, and `authorization`.
- Promote live responses with `kc --json cassettes promote live.json --name fixture_name` so sanitized fixtures are written to both fixture directories and `evidence/manifest.csv`.
- Use `kc --json cassettes promote-and-verify live.json --name fixture_name --run-eval` when turning live samples into regression assets; it promotes, checks fixture parity, and optionally runs Agent eval fixtures.
- Live Keepa smoke tests should use `KEEPA_API_KEY` from GitHub Secrets and manual workflow dispatch.

## Documentation

- [Implementation research report](docs/reports/2026-05-09-keepa-cli-implementation-report.md)
- [Stable documentation entry](https://cunuo.github.io/Keepa-cli/)
- [zread wiki snapshot](.zread/wiki/versions/2026-05-10-215740/wiki.json)
- [Development roadmap](docs/roadmaps/2026-05-09-keepa-cli-development-roadmap.md)
- [service.py / cli.py split plan](docs/architecture/service-cli-split-plan.md)
- [Companion skill](.codex/skills/keepa-cli/SKILL.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
