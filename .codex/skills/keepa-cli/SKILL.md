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

## Raw Escape Hatch

Use raw request only for bounded inspection. Prefer `--dry-run` unless the user explicitly requests a live call:

```powershell
kc --json request get /product --param domain=1 --param asin=B001GZ6QEC --dry-run
```

Do not run raw non-GET live requests without explicit approval.
