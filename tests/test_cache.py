"""
tests/test_cache.py
文件说明：验证缓存 provenance 元数据。
主要职责：确保 dry-run、fixture 和文件输出路径能向 Agent 解释数据来源。
依赖边界：不访问真实 Keepa API。
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keepa_cli.cache import build_cache_provenance
from keepa_cli.cache import SQLiteResponseCache, build_response_cache_key, explain_response_cache_key
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

    def test_sqlite_response_cache_stats_and_clear(self):
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            cache_key = build_response_cache_key(
                method="GET",
                endpoint="/product",
                params={"domain": "1", "asin": "B001GZ6QEC"},
            )
            cache.set(
                cache_key=cache_key,
                method="GET",
                endpoint="/product",
                params={"domain": "1", "asin": "B001GZ6QEC"},
                request={"endpoint": "/product", "params_redacted": {"domain": "1", "asin": "B001GZ6QEC"}},
                body={"products": [{"asin": "B001GZ6QEC"}]},
                token_bucket={"tokens_consumed": 1},
                ttl_seconds=3600,
                now=1000,
            )

            stats = cache.stats(now=1001)
            self.assertTrue(stats["persistent_cache_enabled"])
            self.assertEqual(stats["entries"], 1)
            self.assertGreater(stats["bytes"], 0)

            dry_run = cache.clear(dry_run=True, now=1001)
            self.assertFalse(dry_run["cleared"])
            self.assertEqual(dry_run["entries_removed"], 1)
            self.assertEqual(cache.stats(now=1001)["entries"], 1)

            cleared = cache.clear(dry_run=False, now=1001)
            self.assertTrue(cleared["cleared"])
            self.assertEqual(cleared["entries_removed"], 1)
            self.assertEqual(cache.stats(now=1001)["entries"], 0)

    def test_sqlite_response_cache_expires_entries(self):
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            cache_key = build_response_cache_key(method="GET", endpoint="/product", params={"asin": "B001GZ6QEC"})
            cache.set(
                cache_key=cache_key,
                method="GET",
                endpoint="/product",
                params={"asin": "B001GZ6QEC"},
                request={"endpoint": "/product"},
                body={"products": []},
                token_bucket={},
                ttl_seconds=1,
                now=1000,
            )

            self.assertIsNotNone(cache.get(cache_key, now=1000))
            self.assertIsNone(cache.get(cache_key, now=1002))
            self.assertEqual(cache.stats(now=1002)["entries"], 0)

    def test_sqlite_response_cache_inspect_and_prune_expired(self):
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            fresh_key = build_response_cache_key(method="GET", endpoint="/product", params={"asin": "FRESH"})
            expired_key = build_response_cache_key(method="GET", endpoint="/product", params={"asin": "OLD"})
            cache.set(
                cache_key=fresh_key,
                method="GET",
                endpoint="/product",
                params={"asin": "FRESH"},
                request={"endpoint": "/product"},
                body={"products": [{"asin": "FRESH"}]},
                token_bucket={},
                ttl_seconds=3600,
                now=1000,
            )
            cache.set(
                cache_key=expired_key,
                method="GET",
                endpoint="/product",
                params={"asin": "OLD"},
                request={"endpoint": "/product"},
                body={"products": [{"asin": "OLD"}]},
                token_bucket={},
                ttl_seconds=1,
                now=1000,
            )

            inspected = cache.inspect(expired_key, now=1002)
            self.assertTrue(inspected["found"])
            self.assertTrue(inspected["expired"])
            self.assertEqual(inspected["method"], "GET")
            self.assertEqual(inspected["endpoint"], "/product")
            self.assertNotIn("body", inspected)

            dry_run = cache.prune_expired(dry_run=True, now=1002)
            self.assertFalse(dry_run["pruned"])
            self.assertEqual(dry_run["expired_entries_removed"], 1)
            self.assertEqual(cache.stats(now=1002)["entries"], 2)

            pruned = cache.prune_expired(dry_run=False, now=1002)
            self.assertTrue(pruned["pruned"])
            self.assertEqual(pruned["expired_entries_removed"], 1)
            self.assertEqual(cache.stats(now=1002)["entries"], 1)
            self.assertFalse(cache.inspect(fresh_key, now=1002)["expired"])

    def test_explain_response_cache_key_matches_builder_and_redacts_secret(self):
        explained = explain_response_cache_key(
            method="GET",
            endpoint="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
        )
        expected = build_response_cache_key(
            method="GET",
            endpoint="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
        )

        self.assertEqual(explained["cache_key"], expected)
        self.assertEqual(explained["params"]["key"], "[REDACTED]")
        self.assertNotIn("SECRET123", json.dumps(explained))

    def test_service_cache_explain_key_returns_deterministic_key(self):
        payload = run_command(
            "cache.explain-key",
            {"method": "GET", "endpoint": "/product", "params": {"domain": "1", "asin": "B001GZ6QEC"}},
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "cache.explain-key")
        self.assertEqual(
            payload["data"]["cache_key"],
            build_response_cache_key(method="GET", endpoint="/product", params={"domain": "1", "asin": "B001GZ6QEC"}),
        )

    def test_service_cache_stats_and_clear_use_sqlite_path(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "keepa-cache.sqlite"
            cache = SQLiteResponseCache(cache_path)
            cache.set(
                cache_key=build_response_cache_key(method="GET", endpoint="/product", params={"asin": "B001GZ6QEC"}),
                method="GET",
                endpoint="/product",
                params={"asin": "B001GZ6QEC"},
                request={"endpoint": "/product"},
                body={"products": []},
                token_bucket={},
                ttl_seconds=3600,
                now=1000,
            )

            stats = run_command("cache.stats", {"cache_path": str(cache_path)}, env={})
            self.assertTrue(stats["ok"])
            self.assertTrue(stats["data"]["persistent_cache_enabled"])
            self.assertEqual(stats["data"]["entries"], 1)

            clear = run_command("cache.clear", {"cache_path": str(cache_path), "dry_run": False}, env={})
            self.assertTrue(clear["ok"])
            self.assertTrue(clear["data"]["cleared"])
            self.assertEqual(run_command("cache.stats", {"cache_path": str(cache_path)}, env={})["data"]["entries"], 0)

    def test_service_cache_inspect_and_prune_expired_use_sqlite_path(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "keepa-cache.sqlite"
            cache = SQLiteResponseCache(cache_path)
            cache_key = build_response_cache_key(method="GET", endpoint="/product", params={"asin": "OLD"})
            cache.set(
                cache_key=cache_key,
                method="GET",
                endpoint="/product",
                params={"asin": "OLD"},
                request={"endpoint": "/product"},
                body={"products": []},
                token_bucket={},
                ttl_seconds=1,
                now=1000,
            )

            inspected = run_command("cache.inspect", {"cache_path": str(cache_path), "cache_key": cache_key}, env={})
            self.assertTrue(inspected["ok"])
            self.assertTrue(inspected["data"]["found"])
            self.assertEqual(inspected["data"]["cache_key"], cache_key)

            pruned = run_command("cache.prune-expired", {"cache_path": str(cache_path), "dry_run": False}, env={})
            self.assertTrue(pruned["ok"])
            self.assertTrue(pruned["data"]["pruned"])
            self.assertEqual(run_command("cache.stats", {"cache_path": str(cache_path)}, env={})["data"]["entries"], 0)

    def test_service_cache_stats_honors_environment_cache_path(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "env-cache.sqlite"
            stats = run_command("cache.stats", env={"KEEPA_CLI_CACHE_PATH": str(cache_path)})

        self.assertTrue(stats["ok"])
        self.assertEqual(stats["data"]["path"], str(cache_path))


if __name__ == "__main__":
    unittest.main()
