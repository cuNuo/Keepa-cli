"""
tests/test_client.py
文件说明：验证 KeepaClient 的 dry-run 与 fixture/offline 路径。
主要职责：确保请求规格打码，且离线 fixture 可返回稳定 envelope。
依赖边界：不访问真实网络，也不读取本机 Keepa API key。
"""

import json
import unittest
from pathlib import Path

from keepa_cli.client import KeepaClient


class KeepaClientTests(unittest.TestCase):
    def test_dry_run_request_redacts_secret_key(self):
        client = KeepaClient()

        payload = client.request(
            command="request.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            dry_run=True,
        )

        encoded = json.dumps(payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["request"]["dry_run"])
        self.assertNotIn("SECRET123", encoded)

    def test_fixture_request_returns_offline_payload(self):
        client = KeepaClient(fixture_dir=Path("tests/fixtures"))

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC"},
            fixture="product_B001GZ6QEC.json",
        )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["offline"])
        self.assertEqual(payload["data"]["fixture"], "product_B001GZ6QEC.json")
        self.assertEqual(payload["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")


if __name__ == "__main__":
    unittest.main()
