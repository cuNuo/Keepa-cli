"""
keepa_cli/token_budget.py
文件说明：估算 Keepa 命令执行前可能消耗的 token。
主要职责：为 Agent 输出 estimated_tokens、worst_case_tokens 与确认需求。
依赖边界：纯本地估算模块，不读取账户真实 token bucket。
"""

from __future__ import annotations

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

    if normalized in {"bestsellers.get", "topsellers.list", "topseller.list"}:
        return BudgetEstimate(50, 50, True)

    if normalized in {"tracking.list", "tracking.list-names", "tracking.get", "tracking.notifications"}:
        return BudgetEstimate(1, int(params.get("max_tokens") or 1), False)

    if normalized.startswith("tracking."):
        return BudgetEstimate(1, int(params.get("max_tokens") or 1), True)

    return BudgetEstimate(0, 0, False)
