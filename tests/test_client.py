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

from keepa_cli.cache import SQLiteResponseCache
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
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.calls += 1
        self.requests.append(request)
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
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["token_bucket"]["tokens_left"], 9)
        self.assertEqual(payload["token_bucket"]["tokens_consumed"], 1)
        self.assertEqual(payload["data"]["body"]["products"], [])
        self.assertFalse(payload["data"]["cache_provenance"]["cache_hit"])

    def test_live_get_response_uses_sqlite_cache_without_second_network_call(self):
        body = json.dumps({"tokensLeft": 9, "tokensConsumed": 1, "products": [{"asin": "B001GZ6QEC"}]}).encode(
            "utf-8"
        )
        opener = SequenceOpener([FakeResponse(body)])
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            client = KeepaClient(opener=opener, response_cache=cache)
            env = {"KEEPA_CLI_CACHE_PATH": str(cache.path)}

            first = client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
            )
            second = client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
            )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(opener.calls, 1)
        self.assertFalse(first["data"]["cache_provenance"]["cache_hit"])
        self.assertTrue(second["data"]["cache_provenance"]["cache_hit"])
        self.assertEqual(second["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")
        self.assertEqual(second["token_bucket"]["tokens_consumed"], 0)
        self.assertEqual(second["token_bucket"]["cached_tokens_consumed"], 1)

    def test_live_cache_can_be_disabled_by_environment(self):
        body = json.dumps({"tokensLeft": 9, "tokensConsumed": 1, "products": []}).encode("utf-8")
        opener = SequenceOpener([FakeResponse(body), FakeResponse(body)])
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            client = KeepaClient(opener=opener, response_cache=cache)
            env = {"KEEPA_CLI_NO_CACHE": "1", "KEEPA_CLI_CACHE_PATH": str(cache.path)}

            client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
            )
            client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
            )

        self.assertEqual(opener.calls, 2)

    def test_live_cache_can_be_disabled_by_explicit_request_option(self):
        body = json.dumps({"tokensLeft": 9, "tokensConsumed": 1, "products": []}).encode("utf-8")
        opener = SequenceOpener([FakeResponse(body), FakeResponse(body)])
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            client = KeepaClient(opener=opener, response_cache=cache)
            env = {"KEEPA_CLI_CACHE_PATH": str(cache.path)}

            client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
                no_cache=True,
            )
            client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
                no_cache=True,
            )

        self.assertEqual(opener.calls, 2)
        self.assertFalse(cache.path.exists())

    def test_live_cache_ttl_can_be_set_per_request(self):
        body = json.dumps({"tokensLeft": 9, "tokensConsumed": 1, "products": []}).encode("utf-8")
        opener = SequenceOpener([FakeResponse(body)])
        with TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "keepa-cache.sqlite")
            client = KeepaClient(opener=opener, response_cache=cache)
            env = {"KEEPA_CLI_CACHE_PATH": str(cache.path), "KEEPA_CLI_CACHE_TTL_SECONDS": "3600"}

            payload = client.request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                env=env,
                cache_ttl_seconds=5,
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["cache_provenance"]["expires_at"] - payload["data"]["cache_provenance"]["created_at"], 5)

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
                env={"KEEPA_CLI_CONFIG": str(config_path), "KEEPA_CLI_NO_CACHE": "1"},
            )

        encoded = json.dumps(payload)
        self.assertTrue(payload["ok"])
        self.assertNotIn("CONFIG_SECRET", encoded)

    def test_http_429_waits_once_then_maps_refill_to_retry_after_without_leaking_key(self):
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
        retry_error = urllib.error.HTTPError(
            url="https://api.keepa.com/product?key=SECRET123",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(body),
        )
        opener = SequenceOpener([error, retry_error])
        client = KeepaClient(opener=opener, sleeper=lambda seconds: None)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        encoded = json.dumps(payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "not_enough_token")
        self.assertEqual(payload["error"]["details"]["retry_after_ms"], 12000)
        self.assertEqual(payload["error"]["details"]["retry_after_seconds"], 12)
        guidance = payload["error"]["details"]["token_refill_guidance"]
        self.assertEqual(guidance["wait_strategy"], "wait_for_refill")
        self.assertEqual(guidance["retry_after_seconds"], 12)
        self.assertEqual(guidance["token_deficit"], 2)
        self.assertEqual(guidance["next_actions"][0]["command"], "tokens.status")
        self.assertEqual(payload["token_bucket"]["refill_in_ms"], 12000)
        self.assertNotIn("SECRET123", encoded)

    def test_http_429_waits_for_refill_once_before_success(self):
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
        waits: list[float] = []
        opener = SequenceOpener(
            [
                error,
                FakeResponse(b'{"tokensLeft":8,"tokensConsumed":1,"products":[]}'),
            ]
        )
        client = KeepaClient(opener=opener, sleeper=waits.append)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(opener.calls, 2)
        self.assertEqual(waits, [12.0])
        self.assertEqual(payload["token_bucket"]["waited_for_refill_ms"], 12000)

    def test_http_429_uses_retry_after_header_when_refill_body_is_absent(self):
        body = json.dumps({"tokensLeft": 0, "error": {"type": "TOKEN_LIMIT"}}).encode("utf-8")
        error = urllib.error.HTTPError(
            url="https://api.keepa.com/product?key=SECRET123",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "30"},
            fp=io.BytesIO(body),
        )
        retry_error = urllib.error.HTTPError(
            url="https://api.keepa.com/product?key=SECRET123",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "30"},
            fp=io.BytesIO(body),
        )
        waits: list[float] = []
        client = KeepaClient(opener=SequenceOpener([error, retry_error]), sleeper=waits.append)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(waits, [30.0])
        self.assertEqual(payload["error"]["details"]["retry_after_ms"], 30000)
        self.assertEqual(payload["error"]["details"]["token_refill_guidance"]["retry_after_seconds"], 30)

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
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(opener.calls, 2)

    def test_live_request_without_api_key_fails_before_network_call(self):
        opener = SequenceOpener([FakeResponse(b"{}")])
        client = KeepaClient(opener=opener)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC"},
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "auth_missing")
        self.assertEqual(opener.calls, 0)
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 1)

    def test_binary_request_requires_output_path_before_network_call(self):
        opener = SequenceOpener([FakeResponse(b"PNG")])
        client = KeepaClient(opener=opener)

        payload = client.request(
            command="graphs.image",
            method="GET",
            path="/graphimage",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            binary=True,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "binary_output_path_required")
        self.assertEqual(opener.calls, 0)

    def test_fixture_errors_are_structured_and_do_not_call_network(self):
        live_opener = SequenceOpener([FakeResponse(b"{}")])
        no_fixture_dir = KeepaClient(opener=live_opener)

        unavailable = no_fixture_dir.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC"},
            fixture="missing.json",
        )

        with TemporaryDirectory() as temp_dir:
            missing_fixture = KeepaClient(fixture_dir=Path(temp_dir), opener=live_opener).request(
                command="products.get",
                method="GET",
                path="/product",
                params={"domain": "1", "asin": "B001GZ6QEC"},
                fixture="missing.json",
            )

        self.assertFalse(unavailable["ok"])
        self.assertEqual(unavailable["error"]["kind"], "fixture_unavailable")
        self.assertFalse(missing_fixture["ok"])
        self.assertEqual(missing_fixture["error"]["kind"], "fixture_not_found")
        self.assertEqual(live_opener.calls, 0)

    def test_live_post_json_body_is_sent_without_sqlite_cache(self):
        opener = SequenceOpener([FakeResponse(b'{"tokensLeft":8,"tokensConsumed":1,"ok":true}')])
        client = KeepaClient(opener=opener)

        payload = client.request(
            command="tracking.add",
            method="POST",
            path="/tracking",
            params={"type": "add", "key": "SECRET123"},
            json_body=[{"asin": "B001GZ6QEC", "threshold": 1200}],
            env={},
        )

        request = opener.requests[0]
        self.assertTrue(payload["ok"])
        self.assertEqual(opener.calls, 1)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertIn(b'"asin": "B001GZ6QEC"', request.data)
        self.assertNotIn("cache_key", payload["data"]["cache_provenance"])

    def test_network_error_retries_once_then_returns_safe_error(self):
        error = urllib.error.URLError("temporary DNS failure")
        opener = SequenceOpener([error, error])
        waits: list[float] = []
        client = KeepaClient(opener=opener, sleeper=waits.append)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        encoded = json.dumps(payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(opener.calls, 2)
        self.assertEqual(waits, [2.0])
        self.assertEqual(payload["error"]["kind"], "network_or_parse_error")
        self.assertNotIn("SECRET123", encoded)

    def test_invalid_json_live_response_maps_to_safe_error(self):
        opener = SequenceOpener([FakeResponse(b"not-json")])
        client = KeepaClient(opener=opener)

        payload = client.request(
            command="products.get",
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            env={"KEEPA_CLI_NO_CACHE": "1"},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "network_or_parse_error")

    def test_token_retry_wait_handles_non_429_invalid_and_zero_refill(self):
        server_error = urllib.error.HTTPError(url="https://api.keepa.com/product", code=500, msg="server", hdrs={}, fp=None)
        invalid_refill = urllib.error.HTTPError(
            url="https://api.keepa.com/product",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(b'{"refillIn":"abc"}'),
        )
        zero_refill = urllib.error.HTTPError(
            url="https://api.keepa.com/product",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=io.BytesIO(b'{"refillIn":0}'),
        )

        self.assertIsNone(KeepaClient._token_retry_wait_ms(server_error))
        self.assertIsNone(KeepaClient._token_retry_wait_ms(invalid_refill))
        self.assertEqual(KeepaClient._token_retry_wait_ms(zero_refill), 0)

    def test_binary_live_response_writes_file_and_supports_post_body(self):
        opener = SequenceOpener([FakeResponse(b"\x89PNG\r\n", headers={"Content-Type": "image/png"})])
        client = KeepaClient(opener=opener)

        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "graph.png"
            payload = client.request(
                command="graphs.image",
                method="POST",
                path="/graphimage",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                json_body={"range": 90},
                binary=True,
                out=str(out_path),
                env={},
            )

            request = opener.requests[0]
            self.assertTrue(payload["ok"])
            self.assertEqual(out_path.read_bytes(), b"\x89PNG\r\n")
            self.assertEqual(payload["data"]["bytes_written"], 6)
            self.assertEqual(payload["data"]["content_type"], "image/png")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_binary_live_response_maps_http_and_network_errors(self):
        http_error = urllib.error.HTTPError(
            url="https://api.keepa.com/graphimage?key=SECRET123",
            code=402,
            msg="Payment Required",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"message":"paid plan required"}}'),
        )
        network_error = urllib.error.URLError("socket closed")

        with TemporaryDirectory() as temp_dir:
            http_payload = KeepaClient(opener=SequenceOpener([http_error])).request(
                command="graphs.image",
                method="GET",
                path="/graphimage",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                binary=True,
                out=str(Path(temp_dir) / "http.png"),
                env={},
            )
            network_payload = KeepaClient(opener=SequenceOpener([network_error])).request(
                command="graphs.image",
                method="GET",
                path="/graphimage",
                params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
                binary=True,
                out=str(Path(temp_dir) / "network.png"),
                env={},
            )

        encoded = json.dumps({"http": http_payload, "network": network_payload})
        self.assertFalse(http_payload["ok"])
        self.assertEqual(http_payload["error"]["kind"], "payment_required")
        self.assertFalse(network_payload["ok"])
        self.assertEqual(network_payload["error"]["kind"], "network_or_parse_error")
        self.assertNotIn("SECRET123", encoded)

    def test_http_error_body_reader_handles_empty_none_and_invalid_body(self):
        no_fp = urllib.error.HTTPError(url="https://api.keepa.com/product", code=400, msg="bad", hdrs={}, fp=None)
        empty = urllib.error.HTTPError(url="https://api.keepa.com/product", code=400, msg="bad", hdrs={}, fp=io.BytesIO(b""))
        invalid = urllib.error.HTTPError(url="https://api.keepa.com/product", code=400, msg="bad", hdrs={}, fp=io.BytesIO(b"not-json"))

        self.assertEqual(KeepaClient._read_http_error_body(no_fp), {})
        self.assertEqual(KeepaClient._read_http_error_body(empty), {})
        self.assertEqual(KeepaClient._read_http_error_body(invalid), {})

    def test_http_error_message_falls_back_to_exception_text(self):
        error = urllib.error.HTTPError(url="https://api.keepa.com/product", code=418, msg="teapot", hdrs={}, fp=io.BytesIO(b"{}"))

        self.assertEqual(KeepaClient._http_error_kind(418), "api_error")
        self.assertIn("HTTP Error 418", KeepaClient._http_error_message(error, {}))


if __name__ == "__main__":
    unittest.main()
