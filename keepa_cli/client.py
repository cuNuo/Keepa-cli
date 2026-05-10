"""
keepa_cli/client.py
文件说明：封装 Keepa API 请求客户端的 dry-run、fixture 与 live 请求路径。
主要职责：生成 redacted request spec、读取离线 fixture，并统一返回 JSON envelope。
依赖边界：仅使用标准库网络能力；真实 API key 只来自调用参数、环境变量或本地配置。
"""

from __future__ import annotations

import json
import os
import gzip
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from keepa_cli.cache import (
    CACHE_DISABLE_ENV,
    SQLiteResponseCache,
    build_cache_provenance,
    build_response_cache_key,
    default_cache_path,
    parse_bool,
    resolve_cache_ttl_seconds,
)
from keepa_cli.config import load_config
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.request_spec import build_request_spec
from keepa_cli.token_budget import estimate_request_budget


TOKEN_BUCKET_FIELDS = {
    "refillRate": "refill_rate",
    "refillIn": "refill_in_ms",
    "tokensLeft": "tokens_left",
    "tokensConsumed": "tokens_consumed",
    "tokenFlowReduction": "token_flow_reduction",
}


class KeepaClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.keepa.com",
        fixture_dir: Path | str | None = None,
        timeout_seconds: float = 20.0,
        opener: Callable[[urllib.request.Request, float], Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        response_cache: SQLiteResponseCache | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.fixture_dir = Path(fixture_dir) if fixture_dir is not None else None
        self.timeout_seconds = timeout_seconds
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper or time.sleep
        self.response_cache = response_cache

    def request(
        self,
        *,
        command: str,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        dry_run: bool = False,
        fixture: str | None = None,
        out: str | None = None,
        binary: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        method = method.upper()
        spec = build_request_spec(
            method=method,
            path=path,
            params=params,
            dry_run=dry_run,
            json_body=json_body,
        )
        request_payload = spec.to_dict()
        budget = estimate_request_budget(command, params).to_dict()

        if dry_run:
            return success_envelope(
                command=command,
                data={
                    "dry_run": True,
                    "cache_provenance": build_cache_provenance(
                        endpoint=spec.endpoint,
                        params=params,
                        source="dry-run",
                    ),
                },
                request=request_payload,
                token_bucket={"estimated": budget},
            )

        if fixture:
            return self._fixture_response(command, fixture, request_payload, budget)

        env = os.environ if env is None else env
        config = load_config(env=env)
        api_key = params.get("key") or env.get("KEEPA_API_KEY") or config.get("api_key")
        if not api_key:
            return error_envelope(
                command=command,
                kind="auth_missing",
                message="KEEPA_API_KEY is required for live Keepa requests",
                details={"offline_alternative": "pass fixture=... or use --dry-run"},
                token_bucket={"estimated": budget},
            )

        params["key"] = str(api_key)
        cache_ttl_seconds = resolve_cache_ttl_seconds(config, env=env)
        cache_disabled = parse_bool(env.get(CACHE_DISABLE_ENV)) or cache_ttl_seconds <= 0
        response_cache = None
        if not cache_disabled and method == "GET" and json_body is None:
            response_cache = self.response_cache or SQLiteResponseCache(default_cache_path(env))
        if binary:
            if not out:
                return error_envelope(
                    command=command,
                    kind="binary_output_path_required",
                    message="binary live response requires an explicit output path",
                    details={"resume_with": "--out <path>"},
                    token_bucket={"estimated": budget},
                )
            return self._live_binary_response(command, method, spec.endpoint, params, json_body, request_payload, budget, out)
        return self._live_response(
            command,
            method,
            spec.endpoint,
            params,
            json_body,
            request_payload,
            budget,
            response_cache=response_cache,
            cache_ttl_seconds=cache_ttl_seconds,
        )

    def _fixture_response(
        self,
        command: str,
        fixture: str,
        request_payload: dict[str, Any],
        budget: dict[str, Any],
    ) -> dict[str, Any]:
        if self.fixture_dir is None:
            return error_envelope(
                command=command,
                kind="fixture_unavailable",
                message="fixture_dir is not configured",
                details={"request": request_payload},
            )

        fixture_path = self.fixture_dir / fixture
        if not fixture_path.is_file():
            return error_envelope(
                command=command,
                kind="fixture_not_found",
                message=f"fixture not found: {fixture}",
                details={"fixture_dir": str(self.fixture_dir)},
                token_bucket={"estimated": budget},
            )

        body = json.loads(fixture_path.read_text(encoding="utf-8"))
        return success_envelope(
            command=command,
            data={
                "offline": True,
                "fixture": fixture,
                "body": body,
                "cache_provenance": build_cache_provenance(
                    endpoint=str(request_payload.get("endpoint", "")),
                    params=dict(request_payload.get("params_redacted") or {}),
                    source="fixture",
                    fixture=fixture,
                ),
            },
            request=request_payload,
            token_bucket=self._token_bucket_from_body(body, budget),
        )

    def _live_response(
        self,
        command: str,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        json_body: dict[str, Any] | list[Any] | None,
        request_payload: dict[str, Any],
        budget: dict[str, Any],
        *,
        response_cache: SQLiteResponseCache | None = None,
        cache_ttl_seconds: int = 0,
    ) -> dict[str, Any]:
        public_params = {key: value for key, value in params.items() if key != "key"}
        cache_key = None
        if response_cache is not None:
            cache_key = build_response_cache_key(
                method=method,
                endpoint=endpoint,
                params=public_params,
                json_body=json_body,
            )
            cached = response_cache.get(cache_key)
            if cached is not None:
                cached_token_bucket = dict(cached["token_bucket"])
                cache_token_bucket: dict[str, Any] = {
                    "estimated": cached_token_bucket.get("estimated", budget),
                    "cache_hit": True,
                    "tokens_consumed": 0,
                }
                if cached_token_bucket.get("tokens_consumed") is not None:
                    cache_token_bucket["cached_tokens_consumed"] = cached_token_bucket["tokens_consumed"]
                return success_envelope(
                    command=command,
                    data={
                        "offline": False,
                        "body": cached["body"],
                        "cache_provenance": build_cache_provenance(
                            endpoint=endpoint,
                            params=public_params,
                            source="sqlite",
                            cache_hit=True,
                            cache_key=cache_key,
                            cache_path=str(response_cache.path),
                            created_at=cached["created_at"],
                            expires_at=cached["expires_at"],
                        ),
                    },
                    request=cached["request"],
                    token_bucket=cache_token_bucket,
                )

        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base_url}{endpoint}?{query}"
        body_bytes = None
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "keepa-cli/0.1"}
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        secret_values = [str(params["key"])] if params.get("key") else []
        attempts = 0
        while True:
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    response_body = self._decode_response_body(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code >= 500 and attempts == 0:
                    attempts += 1
                    self.sleeper(2.0)
                    continue
                return self._http_error_envelope(command, endpoint, exc, budget, secret_values)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempts == 0:
                    attempts += 1
                    self.sleeper(2.0)
                    continue
                return error_envelope(
                    command=command,
                    kind="network_or_parse_error",
                    message=str(exc),
                    details={"endpoint": endpoint},
                    token_bucket={"estimated": budget},
                    secret_values=secret_values,
                )
            except json.JSONDecodeError as exc:
                return error_envelope(
                    command=command,
                    kind="network_or_parse_error",
                    message=str(exc),
                    details={"endpoint": endpoint},
                    token_bucket={"estimated": budget},
                    secret_values=secret_values,
                )

        token_bucket = self._token_bucket_from_body(response_body, budget)
        cache_metadata = None
        if response_cache is not None and cache_key is not None:
            cache_metadata = response_cache.set(
                cache_key=cache_key,
                method=method,
                endpoint=endpoint,
                params=public_params,
                request=request_payload,
                body=response_body,
                token_bucket=token_bucket,
                ttl_seconds=cache_ttl_seconds,
            )

        return success_envelope(
            command=command,
            data={
                "offline": False,
                "body": response_body,
                "cache_provenance": build_cache_provenance(
                    endpoint=endpoint,
                    params=public_params,
                    source="live",
                    cache_hit=False,
                    cache_key=cache_key,
                    cache_path=str(response_cache.path) if response_cache is not None else None,
                    created_at=cache_metadata["created_at"] if cache_metadata else None,
                    expires_at=cache_metadata["expires_at"] if cache_metadata else None,
                ),
            },
            request=request_payload,
            token_bucket=token_bucket,
        )

    def _live_binary_response(
        self,
        command: str,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        json_body: dict[str, Any] | list[Any] | None,
        request_payload: dict[str, Any],
        budget: dict[str, Any],
        out: str,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base_url}{endpoint}?{query}"
        body_bytes = None
        headers = {"Accept": "image/png", "User-Agent": "keepa-cli/0.1"}
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        secret_values = [str(params["key"])] if params.get("key") else []
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                content = response.read()
                content_type = response.getheader("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as exc:
            return self._http_error_envelope(command, endpoint, exc, budget, secret_values)
        except (urllib.error.URLError, TimeoutError) as exc:
            return error_envelope(
                command=command,
                kind="network_or_parse_error",
                message=str(exc),
                details={"endpoint": endpoint},
                token_bucket={"estimated": budget},
                secret_values=secret_values,
            )

        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)
        return success_envelope(
            command=command,
            data={
                "out": str(out_path),
                "bytes_written": len(content),
                "content_type": content_type,
                "cache_provenance": build_cache_provenance(
                    endpoint=endpoint,
                    params={key: value for key, value in params.items() if key != "key"},
                    source="live",
                    out=str(out_path),
                ),
            },
            request=request_payload,
            token_bucket={"estimated": budget},
        )

    @staticmethod
    def _token_bucket_from_body(body: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
        token_bucket = {"estimated": budget}
        for source_key, target_key in TOKEN_BUCKET_FIELDS.items():
            if source_key in body:
                token_bucket[target_key] = body[source_key]
        return token_bucket

    @staticmethod
    def _decode_response_body(response: Any) -> dict[str, Any]:
        raw_body = response.read()
        encoding = ""
        if hasattr(response, "getheader"):
            encoding = str(response.getheader("Content-Encoding", "") or "").lower()
        if encoding == "gzip":
            raw_body = gzip.decompress(raw_body)
        return json.loads(raw_body.decode("utf-8"))

    def _http_error_envelope(
        self,
        command: str,
        endpoint: str,
        exc: urllib.error.HTTPError,
        budget: dict[str, Any],
        secret_values: list[str],
    ) -> dict[str, Any]:
        body = self._read_http_error_body(exc)
        token_bucket = self._token_bucket_from_body(body, budget)
        details: dict[str, Any] = {"endpoint": endpoint}
        if exc.code == 429 and "refillIn" in body:
            details["retry_after_ms"] = body["refillIn"]

        return error_envelope(
            command=command,
            kind=self._http_error_kind(exc.code),
            message=self._http_error_message(exc, body),
            status_code=exc.code,
            details=details,
            token_bucket=token_bucket,
            secret_values=secret_values,
        )

    @staticmethod
    def _read_http_error_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
        if exc.fp is None:
            return {}
        try:
            raw_body = exc.fp.read()
            if not raw_body:
                return {}
            return json.loads(raw_body.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _http_error_kind(status_code: int) -> str:
        return {
            400: "bad_request",
            402: "payment_required",
            405: "invalid_parameter",
            429: "not_enough_token",
            500: "server_error",
        }.get(status_code, "api_error")

    @staticmethod
    def _http_error_message(exc: urllib.error.HTTPError, body: dict[str, Any]) -> str:
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("type")
            if message:
                return str(message)
        return str(exc)
