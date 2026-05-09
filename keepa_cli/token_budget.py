"""
keepa_cli/token_budget.py
文件说明：估算 Keepa 命令执行前可能消耗的 token。
主要职责：为 Agent 输出 estimated_tokens、worst_case_tokens 与确认需求。
依赖边界：纯本地估算模块，不读取账户真实 token bucket。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetEstimate:
    estimated_tokens: int
    worst_case_tokens: int
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


def _count_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len([item for item in value.split(",") if item.strip()])
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 1


def estimate_request_budget(command: str, params: dict[str, Any] | None = None) -> BudgetEstimate:
    params = params or {}
    normalized = command.lower()

    if normalized in {"products.get", "product.get"}:
        asin_count = _count_items(params.get("asin") or params.get("asins"))
        code_count = _count_items(params.get("code") or params.get("codes"))
        item_count = max(asin_count, code_count, 1)
        offers = int(params.get("offers") or 0)
        if offers > 0:
            pages_per_product = max(1, (offers + 9) // 10)
            worst = item_count * pages_per_product * 6
            return BudgetEstimate(item_count, worst, worst > item_count)
        return BudgetEstimate(item_count, item_count, False)

    if normalized in {"products.search", "product.search"}:
        return BudgetEstimate(10, 10, False)

    if normalized in {"categories.get", "category.get", "categories.search", "category.search"}:
        return BudgetEstimate(1, 2 if params.get("parents") else 1, bool(params.get("parents")))

    if normalized in {"deals.query", "deal.query"}:
        return BudgetEstimate(5, 5, False)

    if normalized in {"finder.query", "query"}:
        return BudgetEstimate(10, int(params.get("max_tokens") or 10), True)

    if normalized in {"bestsellers.get", "topsellers.list", "topseller.list"}:
        return BudgetEstimate(50, 50, True)

    if normalized.startswith("tracking."):
        return BudgetEstimate(1, int(params.get("max_tokens") or 1), True)

    return BudgetEstimate(0, 0, False)
