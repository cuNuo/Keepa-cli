"""
keepa_cli/agent/mcp_http.py
文件说明：提供 Keepa MCP Streamable HTTP adapter 的标准库实现。
主要职责：把 HTTP 方法、Origin、session、CORS 和 JSON 编解码映射到 MCP JSON-RPC handler。
依赖边界：只实现协议层，不复制工具、资源、提示词或 Keepa service 业务逻辑。
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from keepa_cli import __version__
from keepa_cli.agent.mcp_core import JSONRPC_VERSION, MCP_PROTOCOL_VERSION
from keepa_cli.agent.mcp_http_contract import (
    MCP_ENDPOINT_PATH,
    MCP_PROTOCOL_VERSION_HEADER,
    MCP_REQUEST_TIMEOUT_HEADER,
    MCP_SESSION_HEADER,
    StreamableHttpAdapterContract,
    is_origin_allowed,
)

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
MAX_HTTP_BODY_BYTES = 2_000_000
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:3000", "http://localhost:3000")


class KeepaMcpHttpServer(ThreadingHTTPServer):
    """携带 MCP adapter 状态的 ThreadingHTTPServer。"""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        adapter: StreamableHttpAdapterContract,
        endpoint_path: str = MCP_ENDPOINT_PATH,
        quiet: bool = False,
    ) -> None:
        super().__init__(server_address, KeepaMcpHttpHandler)
        self.adapter = adapter
        self.endpoint_path = endpoint_path
        self.quiet = quiet


class KeepaMcpHttpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"KeepaMCPHTTP/{__version__}"

    def log_message(self, format: str, *args: Any) -> None:
        if not getattr(self.server, "quiet", False):
            super().log_message(format, *args)

    @property
    def mcp_server(self) -> KeepaMcpHttpServer:
        return self.server  # type: ignore[return-value]

    def do_OPTIONS(self) -> None:
        if not self._path_matches():
            self._send_json(404, self._http_error("not_found", "MCP endpoint not found"))
            return
        origin = self.headers.get("Origin")
        if not is_origin_allowed(origin, self.mcp_server.adapter.allowed_origins):
            self._send_json(403, self._http_error("origin_rejected", "Origin rejected"))
            return
        headers = self._base_headers()
        headers.update(
            {
                "Allow": "POST, GET, DELETE, OPTIONS",
                "Access-Control-Allow-Methods": "POST, GET, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": (
                    "Content-Type, Accept, "
                    f"{MCP_SESSION_HEADER}, {MCP_PROTOCOL_VERSION_HEADER}, {MCP_REQUEST_TIMEOUT_HEADER}"
                ),
                "Access-Control-Expose-Headers": f"{MCP_SESSION_HEADER}, {MCP_PROTOCOL_VERSION_HEADER}",
            }
        )
        self._send_empty(204, headers=headers)

    def do_GET(self) -> None:
        self._handle_adapter_request("GET")

    def do_DELETE(self) -> None:
        self._handle_adapter_request("DELETE")

    def do_POST(self) -> None:
        self._handle_adapter_request("POST")

    def _handle_adapter_request(self, method: str) -> None:
        if not self._path_matches():
            self._send_json(404, self._http_error("not_found", "MCP endpoint not found"))
            return
        try:
            body = self._read_body() if method == "POST" else b""
        except ValueError as exc:
            self._send_json(413, self._http_error("body_too_large", str(exc)))
            return
        response = self.mcp_server.adapter.handle(method=method, headers=dict(self.headers.items()), body=body)
        headers = self._base_headers()
        headers.update({str(key): str(value) for key, value in response.get("headers", {}).items()})
        headers.setdefault("Allow", "POST, GET, DELETE, OPTIONS")
        body_payload = response.get("body")
        if body_payload is None:
            self._send_empty(int(response["http_status"]), headers=headers)
            return
        self._send_json(int(response["http_status"]), body_payload, headers=headers)

    def _path_matches(self) -> bool:
        return urlsplit(self.path).path == self.mcp_server.endpoint_path

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0:
            raise ValueError("invalid Content-Length")
        if length > MAX_HTTP_BODY_BYTES:
            raise ValueError(f"HTTP request body exceeds {MAX_HTTP_BODY_BYTES} bytes")
        return self.rfile.read(length)

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Cache-Control": "no-store",
            MCP_PROTOCOL_VERSION_HEADER: MCP_PROTOCOL_VERSION,
        }
        origin = self.headers.get("Origin")
        if origin and is_origin_allowed(origin, self.mcp_server.adapter.allowed_origins):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
        return headers

    def _send_json(self, status: int, payload: Mapping[str, Any], *, headers: Mapping[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        for key, value in (headers or self._base_headers()).items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int, *, headers: Mapping[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or self._base_headers()).items():
            self.send_header(key, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @staticmethod
    def _http_error(kind: str, message: str) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": None, "error": {"code": -32000, "message": message, "data": {"kind": kind}}}


def make_mcp_http_server(
    *,
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    allowed_origins: Sequence[str] | None = None,
    endpoint_path: str = MCP_ENDPOINT_PATH,
    env: Mapping[str, str] | None = None,
    quiet: bool = False,
) -> KeepaMcpHttpServer:
    adapter = StreamableHttpAdapterContract(
        allowed_origins=tuple(allowed_origins or DEFAULT_ALLOWED_ORIGINS),
        env=env if env is not None else os.environ,
    )
    return KeepaMcpHttpServer((host, port), adapter=adapter, endpoint_path=endpoint_path, quiet=quiet)


def serve_mcp_http(
    *,
    host: str = DEFAULT_HTTP_HOST,
    port: int = DEFAULT_HTTP_PORT,
    allowed_origins: Sequence[str] | None = None,
    endpoint_path: str = MCP_ENDPOINT_PATH,
    env: Mapping[str, str] | None = None,
) -> int:
    server = make_mcp_http_server(host=host, port=port, allowed_origins=allowed_origins, endpoint_path=endpoint_path, env=env)
    sys.stderr.write(f"Keepa MCP Streamable HTTP listening on http://{host}:{server.server_port}{endpoint_path}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("Keepa MCP Streamable HTTP stopped\n")
    finally:
        server.server_close()
    return 0
