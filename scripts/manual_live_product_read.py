"""
scripts/manual_live_product_read.py
文件说明：手动产品 live read 验证流程。
主要职责：在显式确认后执行低成本 products.get live read，并输出 token budget、cache provenance 与脱敏摘要。
依赖边界：默认只做 dry-run；只有传入 --yes-live 且存在 KEEPA_API_KEY 时才访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.service import run_command


def _estimated_tokens(payload: dict[str, Any]) -> int:
    estimated = (payload.get("token_bucket") or {}).get("estimated") or {}
    value = estimated.get("worst_case_tokens", estimated.get("estimated_tokens", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_token_status(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        return {"ok": bool(payload.get("ok")), "kind": (payload.get("error") or {}).get("kind")}
    return {
        "ok": bool(payload.get("ok")),
        "tokens_left": body.get("tokensLeft"),
        "refill_in": body.get("refillIn"),
        "refill_rate": body.get("refillRate"),
        "tokens_consumed": (payload.get("token_bucket") or {}).get("tokens_consumed"),
    }


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    provenance = data.get("cache_provenance") if isinstance(data, dict) else None
    body = data.get("body") if isinstance(data, dict) else None
    products = body.get("products") if isinstance(body, dict) else None
    if not isinstance(products, list):
        products = []
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return {
        "ok": bool(payload.get("ok")),
        "error_kind": error.get("kind"),
        "error_message": error.get("message"),
        "cache_provenance": provenance,
        "token_bucket": payload.get("token_bucket") or {},
        "product_count": len(products),
        "cache_hit": bool(((payload.get("token_bucket") or {}).get("cache_hit")) or (isinstance(provenance, dict) and provenance.get("cache_hit"))),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="手动执行低成本 Keepa product live read，并输出脱敏审计摘要。")
    parser.add_argument("--asin", required=True, help="单个 ASIN；脚本不会接受批量 ASIN。")
    parser.add_argument("--domain", default="US", help="Keepa domain code，默认 US。")
    parser.add_argument("--cache-ttl", type=int, default=86400, help="SQLite live response cache TTL seconds。")
    parser.add_argument("--max-estimated-tokens", type=int, default=1, help="允许的 worst-case token 上限。")
    parser.add_argument("--yes-live", action="store_true", help="显式执行 live read；缺省只输出 dry-run 计划。")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args(argv)

    params: dict[str, Any] = {
        "asin": args.asin,
        "domain": args.domain,
        "agent_view": True,
        "view": "summary",
        "history_limit": 5,
        "cache_ttl": args.cache_ttl,
    }
    dry_run = run_command("products.get", {**params, "dry_run": True})
    budget = _estimated_tokens(dry_run)
    if budget > args.max_estimated_tokens:
        summary = {
            "ok": False,
            "live_executed": False,
            "reason": "estimated token budget exceeds limit",
            "asin": args.asin,
            "domain": args.domain,
            "token_budget": {"worst_case_tokens": budget, "max_estimated_tokens": args.max_estimated_tokens},
            "dry_run": _payload_summary(dry_run),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    if not args.yes_live:
        summary = {
            "ok": True,
            "live_executed": False,
            "next_action": "重新运行并添加 --yes-live 后才会访问真实 Keepa API。",
            "asin": args.asin,
            "domain": args.domain,
            "token_budget": {"worst_case_tokens": budget, "max_estimated_tokens": args.max_estimated_tokens},
            "dry_run": _payload_summary(dry_run),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"manual live product read dry-run ok: estimated {budget} token")
        return 0

    if not os.environ.get("KEEPA_API_KEY"):
        summary = {
            "ok": False,
            "live_executed": False,
            "reason": "KEEPA_API_KEY is required for --yes-live",
            "asin": args.asin,
            "domain": args.domain,
            "token_budget": {"worst_case_tokens": budget, "max_estimated_tokens": args.max_estimated_tokens},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    before = run_command("tokens.status", {})
    live = run_command("products.get", params)
    after = run_command("tokens.status", {})
    summary = {
        "ok": bool(live.get("ok")),
        "live_executed": True,
        "asin": args.asin,
        "domain": args.domain,
        "token_budget": {"worst_case_tokens": budget, "max_estimated_tokens": args.max_estimated_tokens},
        "token_status": {
            "before": _safe_token_status(before),
            "after": _safe_token_status(after),
        },
        "result": _payload_summary(live),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) if args.json else f"manual live product read {'ok' if summary['ok'] else 'failed'}: cache_hit={summary['result']['cache_hit']}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
