"""
tests/test_service_commands.py
文件说明：验证 Agent-safe command service 的正式业务命令。
主要职责：覆盖 products/categories 的 dry-run、fixture/offline 和预算信息流。
依赖边界：不访问真实 Keepa API，只使用测试 fixture。
"""

import unittest
from pathlib import Path

from keepa_cli.service import run_command


FIXTURES = Path("tests/fixtures")


class ServiceCommandTests(unittest.TestCase):
    def test_products_get_builds_official_product_request_with_fixture(self):
        payload = run_command(
            "products.get",
            {
                "asin": ["B001GZ6QEC"],
                "domain": "US",
                "history": "0",
                "fixture": "product_B001GZ6QEC.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "products.get")
        self.assertEqual(payload["request"]["endpoint"], "/product")
        self.assertEqual(payload["request"]["params_redacted"]["domain"], "1")
        self.assertEqual(payload["request"]["params_redacted"]["asin"], "B001GZ6QEC")
        self.assertEqual(payload["request"]["params_redacted"]["history"], "0")
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 1)
        self.assertEqual(payload["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")

    def test_products_get_rejects_asin_and_code_together(self):
        payload = run_command(
            "products.get",
            {"asin": ["B001GZ6QEC"], "code": ["9780786222728"], "domain": "US", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "invalid_argument")

    def test_categories_get_uses_category_endpoint_and_parents_flag(self):
        payload = run_command(
            "categories.get",
            {"category": ["0"], "domain": "US", "parents": True, "fixture": "category_roots_US.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/category")
        self.assertEqual(payload["request"]["params_redacted"]["category"], "0")
        self.assertEqual(payload["request"]["params_redacted"]["parents"], "1")
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 1)
        self.assertIn("172282", payload["data"]["body"]["categories"])

    def test_categories_search_uses_official_search_type_category(self):
        payload = run_command(
            "categories.search",
            {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/search")
        self.assertEqual(payload["request"]["params_redacted"]["type"], "category")
        self.assertEqual(payload["request"]["params_redacted"]["term"], "home kitchen")
        self.assertIn("1055398", payload["data"]["body"]["categories"])


if __name__ == "__main__":
    unittest.main()
