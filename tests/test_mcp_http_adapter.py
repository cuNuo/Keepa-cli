"""
tests/test_mcp_http_adapter.py
文件说明：验证真实 Streamable HTTP adapter server 可执行 MCP JSON-RPC。
主要职责：覆盖 initialize、session 复用、Origin 防护、DELETE 终止和 GET/SSE 边界。
依赖边界：仅启动本地 127.0.0.1 标准库 HTTP server，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import threading
import unittest
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from keepa_cli.agent.mcp_http import make_mcp_http_server
from keepa_cli.agent.mcp_http_contract import MCP_PROTOCOL_VERSION_HEADER, MCP_SESSION_HEADER, is_visible_ascii_session_id


class McpHttpAdapterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = make_mcp_http_server(host="127.0.0.1", port=0, env={}, quiet=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/mcp"
        self.assertEqual(self.server.adapter.env, {})

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _request(
        self,
        method: str,
        *,
        body: dict[str, Any] | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        data: bytes | None = None
        request_headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
        if body is not None:
            raw = body if isinstance(body, str) else json.dumps(body)
            data = raw.encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(self.url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read()
                status = response.status
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            payload = exc.read()
            status = exc.code
            response_headers = dict(exc.headers.items())
        if not payload:
            return status, response_headers, None
        return status, response_headers, json.loads(payload.decode("utf-8"))

    def test_post_initialize_and_tools_list_reuse_same_session(self):
        status, headers, payload = self._request(
            "POST",
            body={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
            headers={"Origin": "http://localhost:3000"},
        )
        self.assertEqual(status, 200)
        session_id = headers[MCP_SESSION_HEADER]
        self.assertTrue(is_visible_ascii_session_id(session_id))
        self.assertEqual(payload["result"]["serverInfo"]["name"], "keepa_mcp")

        status, _, payload = self._request(
            "POST",
            body={"jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {"toolset": "all", "limit": 2}},
            headers={MCP_SESSION_HEADER: session_id},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["tools"][0]["name"], "context_policy")
        self.assertEqual(payload["result"]["tools"][1]["name"], "docs_index")

    def test_origin_rejected_before_json_decode(self):
        status, _, payload = self._request(
            "POST",
            body='{"jsonrpc": "2.0", "id": 1, "method":',
            headers={"Origin": "https://evil.example"},
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], -32000)

    def test_delete_terminates_session_and_reuse_returns_expired(self):
        status, headers, _ = self._request("POST", body={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}})
        self.assertEqual(status, 200)
        session_id = headers[MCP_SESSION_HEADER]

        status, _, payload = self._request("DELETE", headers={MCP_SESSION_HEADER: session_id})
        self.assertEqual(status, 202)
        self.assertIsNone(payload)

        status, _, payload = self._request(
            "POST",
            body={"jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {}},
            headers={MCP_SESSION_HEADER: session_id},
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], -32002)

    def test_get_sse_is_explicitly_not_supported(self):
        status, _, payload = self._request("GET")

        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], -32006)

    def test_invalid_protocol_version_is_rejected_before_session(self):
        status, _, payload = self._request(
            "POST",
            body={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
            headers={MCP_PROTOCOL_VERSION_HEADER: "1900-01-01"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], -32004)

    def test_explicit_http_content_negotiation_errors_are_rejected(self):
        status, _, payload = self._request(
            "POST",
            body={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
            headers={"Accept": "application/xml"},
        )
        self.assertEqual(status, 406)
        self.assertEqual(payload["error"]["code"], -32007)

        status, _, payload = self._request(
            "POST",
            body="{\"jsonrpc\":\"2.0\",\"id\":\"init\",\"method\":\"initialize\",\"params\":{}}",
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)
        self.assertEqual(payload["error"]["code"], -32008)

    def test_options_exposes_cors_contract_for_allowed_origin(self):
        status, headers, payload = self._request("OPTIONS", headers={"Origin": "http://127.0.0.1:3000"})

        self.assertEqual(status, 204)
        self.assertIsNone(payload)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:3000")
        self.assertIn(MCP_SESSION_HEADER, headers["Access-Control-Allow-Headers"])


if __name__ == "__main__":
    unittest.main()
