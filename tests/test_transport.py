"""
tests/test_transport.py
文件说明：验证 Keepa record/replay transport。
主要职责：确保未来 live smoke 可录制、脱敏并离线回放 HTTP 信息流。
依赖边界：使用 fake opener，不访问真实 Keepa API。
"""

import json
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from keepa_cli.client import KeepaClient
from keepa_cli.transport import RecordingOpener, ReplayOpener


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


class TransportTests(unittest.TestCase):
    def test_recording_opener_writes_redacted_cassette_and_replay_reads_it(self):
        with TemporaryDirectory() as temp_dir:
            cassette = Path(temp_dir) / "keepa-product.json"

            def fake_opener(request: urllib.request.Request, timeout: float) -> FakeResponse:
                return FakeResponse(
                    b'{"tokensLeft":7,"tokensConsumed":1,"products":[{"asin":"B001GZ6QEC"}]}',
                    headers={"Content-Type": "application/json"},
                )

            recorder = RecordingOpener(cassette, fake_opener)
            client = KeepaClient(opener=recorder)
            recorded_payload = client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env={"KEEPA_CLI_NO_CACHE": "1"},
            )

            cassette_text = cassette.read_text(encoding="utf-8")
            self.assertTrue(recorded_payload["ok"])
            self.assertNotIn("SECRET123", cassette_text)
            self.assertIn("key=%5BREDACTED%5D", cassette_text)

            replay = ReplayOpener(cassette)
            replay_client = KeepaClient(opener=replay)
            replayed_payload = replay_client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "DIFFERENT_SECRET"},
                env={"KEEPA_CLI_NO_CACHE": "1"},
            )

            self.assertTrue(replayed_payload["ok"])
            self.assertEqual(replayed_payload["token_bucket"]["tokens_left"], 7)
            self.assertEqual(replayed_payload["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")


if __name__ == "__main__":
    unittest.main()
