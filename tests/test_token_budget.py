"""
tests/test_token_budget.py
文件说明：验证 Keepa token 预算器。
主要职责：覆盖产品查询计数、高成本榜单确认和 Agent 序列化字段。
依赖边界：纯本地估算，不读取真实账户 token bucket。
"""

import unittest

from keepa_cli.token_budget import BudgetEstimate, estimate_request_budget


class TokenBudgetTests(unittest.TestCase):
    def test_product_budget_counts_asins(self):
        estimate = estimate_request_budget("products.get", {"asin": ["A", "B"]})

        self.assertEqual(estimate.estimated_tokens, 2)
        self.assertEqual(estimate.worst_case_tokens, 2)
        self.assertFalse(estimate.requires_confirmation)

    def test_bestsellers_budget_requires_confirmation(self):
        estimate = estimate_request_budget("bestsellers.get", {"category": "123"})

        self.assertEqual(estimate.estimated_tokens, 50)
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
            },
        )


if __name__ == "__main__":
    unittest.main()
