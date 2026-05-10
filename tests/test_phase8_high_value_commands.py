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
        self.assertEqual(payload["data"]["agent_brief"]["view"], "finder_query")
        self.assertIn("evidence_index", payload["data"])

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

    def test_categories_products_fixture_returns_agent_candidates(self):
        payload = run_command(
            "categories.products",
            {"category": "172282", "domain": "US", "fixture": "bestsellers_home.json", "limit": 1},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "categories.products")
        self.assertEqual(payload["request"]["endpoint"], "/bestsellers")
        self.assertEqual(payload["data"]["view"], "category_products")
        self.assertEqual(payload["data"]["category_id"], "172282")
        self.assertEqual(payload["data"]["asins"], ["B001GZ6QEC"])
        self.assertEqual(payload["data"]["candidates"][0]["rank"], 1)
        self.assertIn("products compare", payload["data"]["next_actions"][0]["command"])
        self.assertEqual(payload["data"]["next_actions"][0]["tool"], "products.compare")
        self.assertEqual(payload["data"]["agent_brief"]["view"], "category_products")
        self.assertIn("evidence_index", payload["data"])

    def test_categories_search_fixture_adds_candidate_next_actions(self):
        payload = run_command(
            "categories.search",
            {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["view"], "category_search")
        self.assertEqual(payload["data"]["category_candidates"][0]["category_id"], "1055398")
        commands = [item["command"] for item in payload["data"]["next_actions"]]
        self.assertTrue(any(command.startswith("categories products 1055398") for command in commands))
        self.assertTrue(any(command.startswith("categories finder-selection 1055398") for command in commands))
        self.assertEqual(payload["data"]["next_actions"][0]["tool"], "categories.products")
        self.assertEqual(payload["data"]["agent_brief"]["view"], "category_search")

    def test_categories_finder_selection_writes_local_scaffold(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "finder-category.json"
            payload = run_command(
                "categories.finder-selection",
                {"category": "1055398", "domain": "US", "out": str(out_path)},
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["data"]["view"], "finder_selection_scaffold")
            self.assertTrue(out_path.is_file())
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["categories_include"], [1055398])
            self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 0)
            self.assertEqual(payload["data"]["next_actions"][0]["tool"], "finder.query")
            self.assertEqual(payload["data"]["data_quality"]["confidence"], "high")

    def test_categories_products_hydrate_top_is_explicit(self):
        payload = run_command(
            "categories.products",
            {
                "category": "172282",
                "domain": "US",
                "fixture": "bestsellers_home.json",
                "limit": 1,
                "hydrate_top": 1,
                "product_fixture": "product_agent_view_B0TEST.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["hydration"]["enabled"])
        self.assertEqual(payload["data"]["hydration"]["requested"], 1)
        self.assertEqual(payload["data"]["hydration"]["hydrated_count"], 1)
        self.assertEqual(payload["data"]["hydration"]["products"][0]["identity"]["asin"], "B0TESTAGENT")
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 51)

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
