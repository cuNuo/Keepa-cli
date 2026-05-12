"""
keepa_cli/token_budget.py
文件说明：估算 Keepa 命令执行前可能消耗的 token。
主要职责：为 Agent 输出 estimated_tokens、worst_case_tokens 与确认需求。
依赖边界：纯本地估算模块，不读取账户真实 token bucket。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BudgetComponent:
    name: str
    estimated_tokens: int
    worst_case_tokens: int
    reason: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class BudgetEstimate:
    estimated_tokens: int
    worst_case_tokens: int
    requires_confirmation: bool = False
    components: tuple[BudgetComponent, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["components"] = [component.to_dict() for component in self.components]
        data["notes"] = list(self.notes)
        return data


def _count_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len([item for item in value.split(",") if item.strip()])
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 1


def _is_enabled(value: Any) -> bool:
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _retry_seconds(wait_ms: int | None) -> int | None:
    if wait_ms is None:
        return None
    if wait_ms <= 0:
        return 0
    return (wait_ms + 999) // 1000


def _budget_dict(budget: BudgetEstimate | Mapping[str, Any] | None) -> dict[str, Any]:
    if budget is None:
        return BudgetEstimate(0, 0, False).to_dict()
    if isinstance(budget, BudgetEstimate):
        return budget.to_dict()
    return dict(budget)


def _guidance_hints(command: str) -> list[str]:
    normalized = command.lower()
    hints = ["check_tokens_status", "wait_for_plan_refill", "use_cache_fixture_or_dry_run"]
    if normalized in {"products.get", "product.get", "products.compare"}:
        hints.extend(["split_asins", "reduce_offers", "avoid_update_zero_until_refilled"])
    elif normalized in {"categories.products", "category.products"}:
        hints.extend(["set_hydrate_top_zero", "split_category_research_steps"])
    elif normalized in {"finder.query", "query"}:
        hints.append("lower_max_tokens")
    elif normalized.startswith("tracking."):
        hints.append("prefer_tracking_readonly_or_dry_run")
    return hints


def build_token_refill_guidance(
    command: str,
    budget: BudgetEstimate | Mapping[str, Any] | None = None,
    *,
    token_bucket: Mapping[str, Any] | None = None,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    budget_data = _budget_dict(budget)
    bucket = dict(token_bucket or {})
    estimated = _optional_int(budget_data.get("estimated_tokens")) or 0
    worst_case = _optional_int(budget_data.get("worst_case_tokens")) or estimated
    tokens_left = _optional_int(bucket.get("tokens_left", bucket.get("tokensLeft")))
    refill_in_ms = _optional_int(bucket.get("refill_in_ms", bucket.get("refillIn")))
    refill_rate = _optional_int(bucket.get("refill_rate", bucket.get("refillRate")))

    wait_ms = retry_after_ms if retry_after_ms is not None else refill_in_ms
    wait_seconds = _retry_seconds(wait_ms)
    target_tokens = max(estimated, worst_case, 0)
    token_deficit = None
    if tokens_left is not None and target_tokens > tokens_left:
        token_deficit = target_tokens - tokens_left
    if wait_seconds is None and token_deficit and refill_rate and refill_rate > 0:
        wait_seconds = max(60, ((token_deficit + refill_rate - 1) // refill_rate) * 60)

    wait_strategy = "wait_for_refill" if wait_seconds is not None else "check_tokens_status"
    guidance: dict[str, Any] = {
        "status_command": "tokens.status",
        "wait_strategy": wait_strategy,
        "estimated_tokens": estimated,
        "worst_case_tokens": worst_case,
        "hints": _guidance_hints(command),
        "next_actions": [
            {"action": "check_tokens_status", "command": "tokens.status"},
            {"action": "retry_after_refill" if wait_seconds is not None else "retry_when_tokens_available"},
            {"action": "reduce_request_scope"},
            {"action": "use_cache_fixture_or_dry_run"},
        ],
    }
    if tokens_left is not None:
        guidance["tokens_left"] = tokens_left
    if token_deficit is not None:
        guidance["token_deficit"] = token_deficit
    if refill_rate is not None:
        guidance["refill_rate_per_minute"] = refill_rate
    if refill_in_ms is not None:
        guidance["refill_in_ms"] = refill_in_ms
    if retry_after_ms is not None:
        guidance["retry_after_ms"] = retry_after_ms
    if wait_seconds is not None:
        guidance["retry_after_seconds"] = wait_seconds
        guidance["next_actions"][1]["wait_seconds"] = wait_seconds
    return guidance


def _product_budget(params: dict[str, Any]) -> BudgetEstimate:
    asin_count = _count_items(params.get("asin") or params.get("asins"))
    code_count = _count_items(params.get("code") or params.get("codes"))
    item_count = max(asin_count, code_count, 1)
    estimated = item_count
    worst = item_count
    components: list[BudgetComponent] = [
        BudgetComponent(
            "base_product",
            item_count,
            item_count,
            "Keepa Product Request base cost is 1 token per returned product.",
        )
    ]
    notes = [
        "stats, history, days, videos, and aplus change payload shape but are not budgeted as extra token cost.",
    ]

    offers = _to_int(params.get("offers") or params.get("offer"), 0)
    if offers > 0:
        normalized_offers = max(20, min(offers, 100))
        pages_per_product = max(1, (normalized_offers + 9) // 10)
        offer_tokens = item_count * pages_per_product * 6
        estimated += offer_tokens
        worst += offer_tokens
        components.append(
            BudgetComponent(
                "offers",
                offer_tokens,
                offer_tokens,
                "offers requests are billed by offer pages: up to 10 offers per page, 6 tokens per page.",
            )
        )
        if normalized_offers != offers:
            notes.append("offers budget normalized to Keepa's documented 20..100 request range.")

    if _is_enabled(params.get("rating")):
        rating_tokens = item_count
        estimated += rating_tokens
        worst += rating_tokens
        components.append(
            BudgetComponent(
                "rating",
                rating_tokens,
                rating_tokens,
                "rating=1 is treated as an explicit extra product refresh cost; it is not part of --full.",
            )
        )

    if _is_enabled(params.get("buybox")):
        buybox_tokens = item_count
        estimated += buybox_tokens
        worst += buybox_tokens
        components.append(
            BudgetComponent(
                "buybox",
                buybox_tokens,
                buybox_tokens,
                "buybox=1 is budgeted as an explicit extra product-level cost when requested.",
            )
        )

    update = _to_int(params.get("update"), -1)
    if update == 0:
        update_tokens = item_count
        worst += update_tokens
        components.append(
            BudgetComponent(
                "update_refresh",
                0,
                update_tokens,
                "update=0 may force a live refresh and can cost up to 1 extra token per product.",
            )
        )

    confirm_components = {component.name for component in components}
    return BudgetEstimate(
        estimated,
        worst,
        "offers" in confirm_components or "update_refresh" in confirm_components,
        tuple(components),
        tuple(notes),
    )


def _category_products_budget(params: dict[str, Any]) -> BudgetEstimate:
    hydrate_top = max(_to_int(params.get("hydrate_top") or params.get("hydrate-top"), 0), 0)
    components = [
        BudgetComponent(
            "bestsellers",
            50,
            50,
            "categories.products uses Keepa Best Sellers and is budgeted like /bestsellers.",
        )
    ]
    if hydrate_top:
        components.append(
            BudgetComponent(
                "hydrate_top",
                hydrate_top,
                hydrate_top,
                "Explicit --hydrate-top fetches one Agent product summary per hydrated ASIN.",
            )
        )
    estimated = sum(component.estimated_tokens for component in components)
    worst = sum(component.worst_case_tokens for component in components)
    return BudgetEstimate(
        estimated,
        worst,
        True,
        tuple(components),
        ("--hydrate-top defaults to 0 and is never added implicitly.",),
    )


def estimate_request_budget(command: str, params: dict[str, Any] | None = None) -> BudgetEstimate:
    params = params or {}
    normalized = command.lower()

    if normalized in {"products.get", "product.get", "products.compare"}:
        return _product_budget(params)

    if normalized in {"products.search", "product.search"}:
        return BudgetEstimate(10, 10, False)

    if normalized in {"categories.get", "category.get", "categories.search", "category.search"}:
        return BudgetEstimate(1, 2 if params.get("parents") else 1, bool(params.get("parents")))

    if normalized in {"history.export", "history.trend", "history.analyze"}:
        item_count = max(_count_items(params.get("asin") or params.get("asins")), 1)
        return BudgetEstimate(item_count, item_count, False)

    if normalized in {"tokens.status", "token.status"}:
        return BudgetEstimate(0, 0, False)

    if normalized in {
        "workflow.plan",
        "research_graph.merge",
        "research-graph.merge",
        "graph.merge",
        "research_brief.export",
        "research-brief.export",
        "brief.export",
        "cassettes.promote_and_verify",
        "cassettes.promote-and-verify",
    }:
        return BudgetEstimate(0, 0, False)

    if normalized in {"graphs.image", "graph.image"}:
        return BudgetEstimate(1, 1, False)

    if normalized in {"lightningdeals.list", "lightningdeal.list"}:
        return BudgetEstimate(1, 1, False)

    if normalized in {"deals.query", "deal.query"}:
        return BudgetEstimate(5, 5, False)

    if normalized in {"finder.query", "query"}:
        return BudgetEstimate(10, int(params.get("max_tokens") or 10), True)

    if normalized in {"sellers.get", "seller.get"}:
        seller_count = max(_count_items(params.get("seller") or params.get("sellers")), 1)
        return BudgetEstimate(seller_count, seller_count, False)

    if normalized in {"categories.finder-selection", "categories.finder_selection"}:
        return BudgetEstimate(0, 0, False)

    if normalized in {"categories.products", "category.products"}:
        return _category_products_budget(params)

    if normalized in {"bestsellers.get", "topsellers.list", "topseller.list"}:
        return BudgetEstimate(50, 50, True)

    if normalized in {"tracking.list", "tracking.list-names", "tracking.get", "tracking.notifications"}:
        return BudgetEstimate(1, int(params.get("max_tokens") or 1), False)

    if normalized.startswith("tracking."):
        return BudgetEstimate(1, int(params.get("max_tokens") or 1), True)

    return BudgetEstimate(0, 0, False)
