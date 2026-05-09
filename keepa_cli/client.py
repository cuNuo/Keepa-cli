"""
keepa_cli/client.py
文件说明：封装 Keepa API 请求客户端的 dry-run、fixture 与 live 请求路径。
主要职责：生成 redacted request spec、读取离线 fixture，并统一返回 JSON envelope。
依赖边界：仅使用标准库网络能力；真实 API key 只来自调用参数或环境变量。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.fixture_dir = Path(fixture_dir) if fixture_dir is not None else None
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        *,
        command: str,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        dry_run: bool = False,
        fixture: str | None = None,
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
                data={"dry_run": True},
                request=request_payload,
                token_bucket={"estimated": budget},
            )

        if fixture:
            return self._fixture_response(command, fixture, request_payload, budget)

        api_key = params.get("key") or os.environ.get("KEEPA_API_KEY")
        if not api_key:
            return error_envelope(
                command=command,
                kind="auth_missing",
                message="KEEPA_API_KEY is required for live Keepa requests",
                details={"offline_alternative": "pass fixture=... or use --dry-run"},
                token_bucket={"estimated": budget},
            )

        params["key"] = str(api_key)
        return self._live_response(command, method, spec.endpoint, params, json_body, request_payload, budget)

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
            data={"offline": True, "fixture": fixture, "body": body},
            request=request_payload,
            token_bucket=self._token_bucket_from_body(body, budget),
        )

    def _live_response(
        self,
        command: str,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        json_body: dict[str, Any] | None,
        request_payload: dict[str, Any],
        budget: dict[str, Any],
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base_url}{endpoint}?{query}"
        body_bytes = None
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "keepa-cli/0.1"}
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
        secret_values = [str(params["key"])] if params.get("key") else []
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return error_envelope(
                command=command,
                kind="api_error",
                message=str(exc),
                status_code=exc.code,
                details={"endpoint": endpoint},
                token_bucket={"estimated": budget},
                secret_values=secret_values,
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return error_envelope(
                command=command,
                kind="network_or_parse_error",
                message=str(exc),
                details={"endpoint": endpoint},
                token_bucket={"estimated": budget},
                secret_values=secret_values,
            )

        return success_envelope(
            command=command,
            data=response_body,
            request=request_payload,
            token_bucket=self._token_bucket_from_body(response_body, budget),
        )

    @staticmethod
    def _token_bucket_from_body(body: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
        token_bucket = {"estimated": budget}
        for source_key, target_key in TOKEN_BUCKET_FIELDS.items():
            if source_key in body:
                token_bucket[target_key] = body[source_key]
        return token_bucket
