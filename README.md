<p align="center">
  <h1 align="center">Keepa CLI</h1>
  <p align="center">Agent-first Keepa API tooling with JSON, stdio, MCP, fixtures, token budgeting, and a command-first TUI.</p>
</p>

<p align="center">
  <a href="https://github.com/cuNuo/Keepa-cli/actions"><img alt="CI" src="https://img.shields.io/badge/ci-release_gate-2f855a"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776ab"></a>
  <a href="https://www.npmjs.com/package/@cunuo/keepa-cli"><img alt="npm" src="https://img.shields.io/badge/npm-%40cunuo%2Fkeepa--cli-cb3837"></a>
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

## Features

- Equivalent `keepa-cli` and `kc` entrypoints.
- Stable `--json` envelopes for automation.
- JSON Lines `--stdio` protocol and MCP `--mcp` server for long-running agent sessions.
- Prompt-toolkit TUI with slash completion, command history, a bottom status bar, and copyable output.
- Fixture/offline mode, dry-run requests, token budget hints, and secret redaction.
- Safe `/graphimage` handling with explicit `--out` for binary PNG output.
- Finder, Deals, Seller, Best Sellers, Top Sellers, Tracking, and webhook command families.
- Local browse snapshots, batch ASIN plans, workflow templates, markdown/JSON/CSV reports, cache explain, and cost audit.
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
```

Agent profiles are `summary`, `research`, `deal`, and `audit`. Start from `agent_brief` for a compact decision layer, then use `evidence_index` to jump to deeper JSON paths when the Agent needs proof. `agent_brief` includes both series-first `temporal_takeaways` and window-first `temporal_by_window`, so an Agent can compare 7/30/90/180/365 day changes across price, rank, reviews, rating, and offer count without parsing raw Keepa `csv`. Product views also include `data_quality`, `next_actions`, `temporal_features`, and `selection_signals` for deeper audit and research workflows.

Token budgets include component-level hints. Product requests start at `1 token * product count`; explicit `--rating` and `--buybox` are budgeted as additional product-level costs, `--offers` is budgeted as Keepa offer pages (`6 tokens * ceil(offers / 10) * product count`), and `--update 0` is tracked as a worst-case live refresh.

Use explicit flags when you need tighter history windows or specialized fields:

```powershell
kc --json products get B001GZ6QEC --domain US --history 1 --stats 180 --videos 1 --aplus 1 --days 365 --dry-run
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
```

Use built-in workflow templates:

```powershell
kc --json templates list
kc --json templates show finder-basic --out .\finder-basic.json
```

Explain provenance and estimate token cost before live work:

```powershell
kc --json cache explain --input .\batch.json --command products.get
kc --json audit cost products.get --param asin=B001GZ6QEC
```

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
```

stdio JSON Lines:

```powershell
'{"id":"1","method":"doctor","params":{}}' | kc --stdio
```

MCP JSON-RPC over stdio:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | kc --mcp
```

The initial MCP tools are `keepa.products_get`, `keepa.categories_search`, `keepa.categories_products`, `keepa.finder_query`, and `keepa.audit_cost`. They accept structured JSON arguments and call the same command service as the CLI. Tool results include `structuredContent`, a compact JSON text fallback, `cache_key`, `cache_hit`, and `budget_ledger` so Agent sessions can dedupe repeated ASIN/category work and track cumulative token exposure.

Contracts:

- [Agent contract](docs/agent-contract.md)
- [MCP Agent tools architecture](docs/architecture/mcp-agent-tools.md)
- [Keepa official API notes](docs/keepa-official-api-notes.md)

Agent-facing result profiles use the same top-level shape where possible: `agent_brief`, `data_quality`, `selection_signals`, `next_actions`, `evidence_index`, and `provenance`. `workflow plan` is local-only and returns an execution graph with step dependencies, parallel groups, token budgets, confirmation flags, and fixture replay hints.

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
- Live Keepa smoke tests should use `KEEPA_API_KEY` from GitHub Secrets and manual workflow dispatch.

## Documentation

- [Implementation research report](docs/reports/2026-05-09-keepa-cli-implementation-report.md)
- [Development roadmap](docs/roadmaps/2026-05-09-keepa-cli-development-roadmap.md)
- [service.py / cli.py split plan](docs/architecture/service-cli-split-plan.md)
- [Companion skill](.codex/skills/keepa-cli/SKILL.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
