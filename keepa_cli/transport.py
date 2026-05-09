"""
keepa_cli/transport.py
文件说明：提供 Keepa HTTP record/replay transport。
主要职责：录制脱敏 HTTP 响应 cassette，并在离线测试中回放相同信息流。
依赖边界：不解析业务 JSON，不读取 API key；只处理 HTTP 请求与响应字节。
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


class CassetteResponse:
    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self._headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name, default)

    def __enter__(self) -> "CassetteResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def _request_method(request: urllib.request.Request) -> str:
    return request.get_method().upper()


def _redacted_url(request: urllib.request.Request) -> str:
    parts = urllib.parse.urlsplit(request.full_url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    redacted_query = [
        (key, "[REDACTED]" if key.lower() in {"key", "api_key", "apikey", "token"} else value)
        for key, value in query
    ]
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(redacted_query, doseq=True),
            parts.fragment,
        )
    )


def _cassette_key(request: urllib.request.Request) -> dict[str, str]:
    return {"method": _request_method(request), "url": _redacted_url(request)}


def _selected_headers(response: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in ("Content-Encoding", "Content-Type"):
        if hasattr(response, "getheader"):
            value = response.getheader(name)
            if value:
                headers[name] = str(value)
    return headers


class RecordingOpener:
    def __init__(
        self,
        cassette_path: Path | str,
        opener: Callable[[urllib.request.Request, float], Any],
    ) -> None:
        self.cassette_path = Path(cassette_path)
        self.opener = opener

    def __call__(self, request: urllib.request.Request, timeout: float) -> CassetteResponse:
        response = self.opener(request, timeout)
        body = response.read()
        headers = _selected_headers(response)
        record = {
            "request": _cassette_key(request),
            "response": {
                "headers": headers,
                "body_base64": base64.b64encode(body).decode("ascii"),
            },
        }
        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)
        self.cassette_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return CassetteResponse(body, headers=headers)


class ReplayOpener:
    def __init__(self, cassette_path: Path | str) -> None:
        self.cassette_path = Path(cassette_path)
        self.record = json.loads(self.cassette_path.read_text(encoding="utf-8"))

    def __call__(self, request: urllib.request.Request, timeout: float) -> CassetteResponse:
        expected = self.record["request"]
        actual = _cassette_key(request)
        if expected != actual:
            raise ValueError(f"cassette request mismatch: expected {expected}, got {actual}")

        response = self.record["response"]
        body = base64.b64decode(response["body_base64"])
        return CassetteResponse(body, headers=response.get("headers") or {})
