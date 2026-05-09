"""
tests/test_client.py
文件说明：验证 KeepaClient 的 dry-run 与 fixture/offline 路径。
主要职责：确保请求规格打码，且离线 fixture 可返回稳定 envelope。
依赖边界：不访问真实网络，也不读取本机 Keepa API key。
"""

import json
import gzip
import io
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from keepa_cli.client import KeepaClient


class FakeResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self.body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class SequenceOpener:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls = 0

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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

    def test_live_response_decodes_gzip_without_real_network(self):
        body = json.dumps({"tokensLeft": 9, "tokensConsumed": 1, "products": []}).encode("utf-8")
        opener = SequenceOpener([FakeResponse(gzip.compress(body), headers={"Content-Encoding": "gzip"})])
        client = KeepaClient(opener=opener)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["token_bucket"]["tokens_left"], 9)
        self.assertEqual(payload["token_bucket"]["tokens_consumed"], 1)

    def test_live_response_can_read_api_key_from_config_without_leaking_it(self):
        body = json.dumps({"tokensLeft": 9, "tokensConsumed": 1, "products": []}).encode("utf-8")
        opener = SequenceOpener([FakeResponse(body)])
        client = KeepaClient(opener=opener)

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('api_key = "CONFIG_SECRET"\n', encoding="utf-8")
            payload = client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC"},
                env={"KEEPA_CLI_CONFIG": str(config_path)},
            )

        encoded = json.dumps(payload)
        self.assertTrue(payload["ok"])
        self.assertNotIn("CONFIG_SECRET", encoded)

    def test_http_429_maps_refill_to_retry_after_without_leaking_key(self):
        body = json.dumps({"refillIn": 12000, "tokensLeft": -1, "error": {"type": "TOKEN_LIMIT"}}).encode(
            "utf-8"
        )
        error = urllib.error.HTTPError(
            url="https://api.keepa.com/product?key=SECRET123",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(body),
        )
        opener = SequenceOpener([error])
        client = KeepaClient(opener=opener, sleeper=lambda seconds: None)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
        )

        encoded = json.dumps(payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "not_enough_token")
        self.assertEqual(payload["error"]["details"]["retry_after_ms"], 12000)
        self.assertEqual(payload["token_bucket"]["refill_in_ms"], 12000)
        self.assertNotIn("SECRET123", encoded)

    def test_server_error_retries_once_before_success(self):
        server_error = urllib.error.HTTPError(
            url="https://api.keepa.com/product",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"type":"SERVER"}}'),
        )
        opener = SequenceOpener(
            [
                server_error,
                FakeResponse(b'{"tokensLeft":8,"tokensConsumed":1,"products":[]}'),
            ]
        )
        client = KeepaClient(opener=opener, sleeper=lambda seconds: None)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(opener.calls, 2)


if __name__ == "__main__":
    unittest.main()
