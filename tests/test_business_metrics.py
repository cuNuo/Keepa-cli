"""
tests/test_business_metrics.py
文件说明：验证业务指标、业务别名与 Agent profile 生成器。
主要职责：确保 monthlySold、seller count、库存风险、现金流 proxy 都带公式元数据。
依赖边界：全部使用本地 fixture，不访问真实 Keepa API。
"""

import json
import unittest
from pathlib import Path

from keepa_cli.service import run_command


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class BusinessMetricsTests(unittest.TestCase):
    def test_business_find_fast_movers_returns_auditable_metrics(self):
        payload = run_command(
            "business.find-fast-movers",
            {"fixture": "product_agent_view_B0TEST.json", "threshold_monthly_sold": 500},
            fixture_dir=FIXTURES,
        )

        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["view"], "business_metrics")
        self.assertEqual(data["summary"]["fast_mover_count"], 1)
        product = data["products"][0]
        self.assertEqual(product["asin"], "B0TESTAGENT")
        self.assertTrue(product["decision_signals"]["fast_mover"])
        for metric in product["metrics"].values():
            self.assertIn("method", metric)
            self.assertIn("version", metric)
            self.assertIn("inputs", metric)
            self.assertIn("confidence", metric)
            self.assertIn("evidence_path", metric)
            self.assertTrue(str(metric["evidence_path"]).startswith("$.products[0]"))
        self.assertEqual(product["metrics"]["velocity"]["monthly_units"], 100000.0)
        self.assertEqual(product["metrics"]["seller_metrics"]["estimated_seller_count"], 6)
        self.assertEqual(product["metrics"]["cashflow"]["cashflow_pressure"], "high")

    def test_business_aliases_share_metrics_engine(self):
        for command in ("business.inventory-audit", "business.market-opportunity", "seller-metrics.summary", "velocity.research", "inventory.audit"):
            payload = run_command(command, {"fixture": "product_agent_view_B0TEST.json"}, fixture_dir=FIXTURES)
            self.assertTrue(payload["ok"], command)
            self.assertEqual(payload["data"]["formula_policy"]["required_fields"], ["method", "version", "inputs", "confidence", "evidence_path"])

    def test_agent_profile_generator_uses_agent_neutral_wording(self):
        payload = run_command("agent.profile.generate", {"profile": "offline_fixture_only", "toolset": "business"})

        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["view"], "agent_mcp_profile")
        self.assertEqual(data["recommended_discovery"]["params"]["profile"], "offline_fixture_only")
        self.assertEqual(data["recommended_discovery"]["params"]["toolset"], "business")
        rendered = json.dumps(data, ensure_ascii=False)
        self.assertIn("find_fast_movers", rendered)


if __name__ == "__main__":
    unittest.main()
