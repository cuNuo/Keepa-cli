"""
tests/test_cache.py
文件说明：验证缓存 provenance 元数据。
主要职责：确保 dry-run、fixture 和文件输出路径能向 Agent 解释数据来源。
依赖边界：不访问真实 Keepa API。
"""

import unittest
from pathlib import Path

from keepa_cli.cache import build_cache_provenance
from keepa_cli.service import run_command


FIXTURES = Path("tests/fixtures")


class CacheProvenanceTests(unittest.TestCase):
    def test_build_cache_provenance_has_stable_audit_fields(self):
        provenance = build_cache_provenance(
            endpoint="/product",
            params={"domain": "1", "asin": "B001GZ6QEC"},
            source="fixture",
            fixture="product_B001GZ6QEC.json",
        )

        self.assertEqual(provenance["source"], "fixture")
        self.assertEqual(provenance["endpoint"], "/product")
        self.assertEqual(provenance["fixture"], "product_B001GZ6QEC.json")
        self.assertEqual(provenance["cache_hit"], False)
        self.assertIn("params_hash", provenance)

    def test_dry_run_payload_includes_cache_provenance(self):
        payload = run_command(
            "products.get",
            {"asin": ["B001GZ6QEC"], "domain": "US", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        provenance = payload["data"]["cache_provenance"]
        self.assertEqual(provenance["source"], "dry-run")
        self.assertEqual(provenance["endpoint"], "/product")
        self.assertEqual(provenance["cache_hit"], False)

    def test_fixture_payload_includes_cache_provenance(self):
        payload = run_command(
            "products.get",
            {"asin": ["B001GZ6QEC"], "domain": "US", "fixture": "product_B001GZ6QEC.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        provenance = payload["data"]["cache_provenance"]
        self.assertEqual(provenance["source"], "fixture")
        self.assertEqual(provenance["fixture"], "product_B001GZ6QEC.json")


if __name__ == "__main__":
    unittest.main()
