"""
tests/test_token_budget.py
文件说明：验证 Keepa token 预算器。
主要职责：覆盖产品查询计数、高成本榜单确认和 Agent 序列化字段。
依赖边界：纯本地估算，不读取真实账户 token bucket。
"""

import unittest

from keepa_cli.token_budget import BudgetEstimate, build_token_refill_guidance, estimate_request_budget


class TokenBudgetTests(unittest.TestCase):
    def test_product_budget_counts_asins(self):
        estimate = estimate_request_budget("products.get", {"asin": ["A", "B"]})

        self.assertEqual(estimate.estimated_tokens, 2)
        self.assertEqual(estimate.worst_case_tokens, 2)
        self.assertFalse(estimate.requires_confirmation)
        self.assertEqual(estimate.components[0].name, "base_product")

    def test_product_budget_counts_rating_and_buybox_when_explicit(self):
        estimate = estimate_request_budget("products.get", {"asin": ["A", "B"], "rating": "1", "buybox": "1"})

        self.assertEqual(estimate.estimated_tokens, 6)
        self.assertEqual(estimate.worst_case_tokens, 6)
        self.assertFalse(estimate.requires_confirmation)
        self.assertEqual([component.name for component in estimate.components], ["base_product", "rating", "buybox"])

    def test_product_budget_counts_offer_pages_on_top_of_base_cost(self):
        estimate = estimate_request_budget("products.get", {"asin": "A", "offers": "20"})

        self.assertEqual(estimate.estimated_tokens, 13)
        self.assertEqual(estimate.worst_case_tokens, 13)
        self.assertTrue(estimate.requires_confirmation)
        self.assertEqual([component.name for component in estimate.components], ["base_product", "offers"])

    def test_product_budget_tracks_update_zero_as_worst_case_refresh(self):
        estimate = estimate_request_budget("products.get", {"asin": ["A", "B"], "update": "0"})

        self.assertEqual(estimate.estimated_tokens, 2)
        self.assertEqual(estimate.worst_case_tokens, 4)
        self.assertTrue(estimate.requires_confirmation)
        self.assertEqual([component.name for component in estimate.components], ["base_product", "update_refresh"])

    def test_bestsellers_budget_requires_confirmation(self):
        estimate = estimate_request_budget("bestsellers.get", {"category": "123"})

        self.assertEqual(estimate.estimated_tokens, 50)
        self.assertTrue(estimate.requires_confirmation)

    def test_category_products_budget_requires_confirmation(self):
        estimate = estimate_request_budget("categories.products", {"category": "123"})

        self.assertEqual(estimate.estimated_tokens, 50)
        self.assertTrue(estimate.requires_confirmation)

    def test_category_products_hydrate_top_adds_explicit_product_cost(self):
        estimate = estimate_request_budget("categories.products", {"category": "123", "hydrate_top": 3})

        self.assertEqual(estimate.estimated_tokens, 53)
        self.assertEqual(estimate.worst_case_tokens, 53)
        self.assertEqual([component.name for component in estimate.components], ["bestsellers", "hydrate_top"])
        self.assertTrue(estimate.requires_confirmation)

    def test_history_budget_counts_asins_without_confirmation(self):
        estimate = estimate_request_budget("history.trend", {"asin": "B001GZ6QEC"})

        self.assertEqual(estimate.estimated_tokens, 1)
        self.assertFalse(estimate.requires_confirmation)

    def test_budget_can_be_serialized_for_agent(self):
        estimate = BudgetEstimate(estimated_tokens=1, worst_case_tokens=6, requires_confirmation=True)

        self.assertEqual(
            estimate.to_dict(),
            {
                "estimated_tokens": 1,
                "worst_case_tokens": 6,
                "requires_confirmation": True,
                "components": [],
                "notes": [],
            },
        )

    def test_refill_guidance_maps_bucket_wait_and_deficit(self):
        guidance = build_token_refill_guidance(
            "products.get",
            BudgetEstimate(estimated_tokens=13, worst_case_tokens=13, requires_confirmation=True),
            token_bucket={"tokens_left": -1, "refill_in_ms": 12000, "refill_rate": 20},
        )

        self.assertEqual(guidance["wait_strategy"], "wait_for_refill")
        self.assertEqual(guidance["retry_after_seconds"], 12)
        self.assertEqual(guidance["token_deficit"], 14)
        self.assertIn("reduce_offers", guidance["hints"])
        self.assertEqual(guidance["next_actions"][0]["command"], "tokens.status")

    def test_refill_guidance_without_live_bucket_points_to_status_check(self):
        guidance = build_token_refill_guidance(
            "categories.products",
            {"estimated_tokens": 50, "worst_case_tokens": 50, "requires_confirmation": True},
        )

        self.assertEqual(guidance["wait_strategy"], "check_tokens_status")
        self.assertEqual(guidance["status_command"], "tokens.status")
        self.assertIn("official_bestsellers_cost_50_tokens", guidance["hints"])
        self.assertIn("set_hydrate_top_zero", guidance["hints"])
        self.assertEqual(guidance["next_actions"][1]["action"], "retry_when_tokens_available")
        self.assertEqual(guidance["alternative_actions"][0]["action"], "confirm_live_bestsellers")


if __name__ == "__main__":
    unittest.main()
