"""
tests/test_phase8_high_value_commands.py
文件说明：验证 Phase 8 高价值 Keepa API 命令。
主要职责：覆盖 finder、deals、sellers、bestsellers 与 topsellers 的 Agent-safe 信息流。
依赖边界：不访问真实 Keepa API，只使用 selection 文件、dry-run 与测试 fixture。
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keepa_cli.service import run_command


FIXTURES = Path("tests/fixtures")


class Phase8HighValueCommandTests(unittest.TestCase):
    def test_finder_query_dry_run_loads_selection_file_and_estimates_budget(self):
        payload = run_command(
            "finder.query",
            {
                "selection_file": str(FIXTURES / "finder_selection.json"),
                "domain": "US",
                "dry_run": True,
                "max_tokens": 25,
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "finder.query")
        self.assertEqual(payload["request"]["endpoint"], "/query")
        self.assertEqual(payload["request"]["params_redacted"]["domain"], "1")
        self.assertIn("current_SALES_gte", payload["request"]["params_redacted"]["selection"])
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 10)
        self.assertEqual(payload["token_bucket"]["estimated"]["worst_case_tokens"], 25)
        self.assertTrue(payload["token_bucket"]["estimated"]["requires_confirmation"])

    def test_deals_query_fixture_can_write_large_result_to_out_file(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "deals.json"
            payload = run_command(
                "deals.query",
                {
                    "selection_file": str(FIXTURES / "deals_selection.json"),
                    "domain": "US",
                    "fixture": "deals_home.json",
                    "out": str(out_path),
                },
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "deals.query")
            self.assertEqual(payload["request"]["endpoint"], "/deal")
            self.assertTrue(out_path.is_file())
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertIn("deals", saved)
            self.assertEqual(payload["data"]["output"]["path"], str(out_path))
            self.assertEqual(payload["data"]["output"]["format"], "json")

    def test_sellers_get_fixture_uses_seller_endpoint(self):
        payload = run_command(
            "sellers.get",
            {
                "seller": ["A2L77EE7U53NWQ"],
                "domain": "US",
                "storefront": True,
                "fixture": "seller_A2L77EE7U53NWQ.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/seller")
        self.assertEqual(payload["request"]["params_redacted"]["seller"], "A2L77EE7U53NWQ")
        self.assertEqual(payload["request"]["params_redacted"]["storefront"], "1")
        self.assertIn("A2L77EE7U53NWQ", payload["data"]["body"]["sellers"])

    def test_bestsellers_dry_run_shows_50_token_prompt(self):
        payload = run_command(
            "bestsellers.get",
            {"category": "172282", "domain": "US", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/bestsellers")
        self.assertEqual(payload["request"]["params_redacted"]["category"], "172282")
        estimate = payload["token_bucket"]["estimated"]
        self.assertEqual(estimate["estimated_tokens"], 50)
        self.assertEqual(estimate["worst_case_tokens"], 50)
        self.assertTrue(estimate["requires_confirmation"])

    def test_topsellers_live_requires_explicit_confirmation_before_auth(self):
        payload = run_command("topsellers.list", {"domain": "US"}, fixture_dir=FIXTURES, env={})

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "confirmation_required")
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 50)

    def test_topsellers_fixture_can_write_large_result_to_out_file(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "topsellers.json"
            payload = run_command(
                "topsellers.list",
                {"domain": "US", "fixture": "topsellers_US.json", "out": str(out_path)},
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["request"]["endpoint"], "/topseller")
            self.assertTrue(out_path.is_file())
            self.assertEqual(payload["data"]["output"]["path"], str(out_path))


if __name__ == "__main__":
    unittest.main()
