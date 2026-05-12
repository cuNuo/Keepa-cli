"""
tests/test_mcp_http_contract.py
文件说明：验证 Streamable HTTP 前置协议合约 fixture。
主要职责：确保 Origin、MCP-Session-Id 与错误映射在 HTTP adapter 实现前已有可回归边界。
依赖边界：不启动 HTTP server，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from keepa_cli.agent.mcp_http_contract import (
    HTTP_ACCEPT_HEADER,
    HTTP_CONTENT_TYPE_HEADER,
    MCP_REQUEST_TIMEOUT_HEADER,
    MCP_SESSION_HEADER,
    StreamableHttpAdapterContract,
    adapter_response_for_case,
    evaluate_streamable_http_contract,
    is_origin_allowed,
    is_accept_compatible,
    is_json_content_type,
    is_visible_ascii_session_id,
    normalize_request_timeout_ms,
)


FIXTURE = Path("tests/agent_eval_fixtures/mcp_streamable_http_boundary_fixture.json")


class McpHttpContractTests(unittest.TestCase):
    def test_origin_policy_is_allowlist_based(self):
        allowed = ["http://127.0.0.1:3000", "http://localhost:3000"]
        self.assertTrue(is_origin_allowed(None, allowed))
        self.assertTrue(is_origin_allowed("http://localhost:3000", allowed))
        self.assertFalse(is_origin_allowed("https://evil.example", allowed))

    def test_session_id_visible_ascii_contract(self):
        self.assertTrue(is_visible_ascii_session_id("7b3c4d5e6f7a8b9c-safe-session"))
        self.assertFalse(is_visible_ascii_session_id("包含中文的-session"))
        self.assertFalse(is_visible_ascii_session_id("short"))

    def test_request_timeout_contract_is_bounded(self):
        self.assertEqual(normalize_request_timeout_ms(None), 30_000)
        self.assertEqual(normalize_request_timeout_ms("45000"), 45_000)
        with self.assertRaises(ValueError):
            normalize_request_timeout_ms(10)
        with self.assertRaises(ValueError):
            normalize_request_timeout_ms(True)

    def test_http_content_negotiation_is_strict_when_explicit(self):
        self.assertTrue(is_accept_compatible(None))
        self.assertTrue(is_accept_compatible("application/json, text/event-stream"))
        self.assertTrue(is_accept_compatible("*/*"))
        self.assertFalse(is_accept_compatible("application/xml"))
        self.assertFalse(is_accept_compatible("application/xml, application/json;q=0"))
        self.assertTrue(is_json_content_type(None))
        self.assertTrue(is_json_content_type("application/json; charset=utf-8"))
        self.assertFalse(is_json_content_type("text/plain"))

    def test_request_timeout_uses_real_adapter_wait_boundary(self):
        adapter = StreamableHttpAdapterContract()
        adapter.register_session("active-visible-ascii-session")

        def slow_handler(*args, **kwargs):
            time.sleep(2)
            return {"jsonrpc": "2.0", "id": "slow", "result": {}}

        with patch("keepa_cli.agent.mcp_http_contract.handle_mcp_message", side_effect=slow_handler):
            response = adapter.handle(
                method="POST",
                headers={MCP_SESSION_HEADER: "active-visible-ascii-session", MCP_REQUEST_TIMEOUT_HEADER: "1000"},
                body={"jsonrpc": "2.0", "id": "slow", "method": "tools/list", "params": {}},
            )

        self.assertEqual(response["http_status"], 504)
        self.assertEqual(response["body"]["error"]["code"], -32003)

    def test_idle_sessions_are_pruned_before_reuse(self):
        adapter = StreamableHttpAdapterContract(session_idle_ttl_seconds=1)
        adapter.register_session("idle-visible-ascii-session")
        adapter.session_last_seen["idle-visible-ascii-session"] = time.monotonic() - 2

        response = adapter.handle(
            method="POST",
            headers={MCP_SESSION_HEADER: "idle-visible-ascii-session"},
            body={"jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {}},
        )

        self.assertEqual(response["http_status"], 404)
        self.assertEqual(response["body"]["error"]["code"], -32002)
        self.assertNotIn("idle-visible-ascii-session", adapter.sessions)

    def test_session_capacity_is_bounded(self):
        adapter = StreamableHttpAdapterContract(max_sessions=1)
        first = adapter.handle(
            method="POST",
            body={"jsonrpc": "2.0", "id": "init-1", "method": "initialize", "params": {}},
        )
        self.assertEqual(first["http_status"], 200)

        second = adapter.handle(
            method="POST",
            body={"jsonrpc": "2.0", "id": "init-2", "method": "initialize", "params": {}},
        )

        self.assertEqual(second["http_status"], 503)
        self.assertEqual(second["body"]["error"]["code"], -32009)

    def test_streamable_http_fixture_covers_required_boundaries(self):
        spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload = evaluate_streamable_http_contract(spec)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing_categories"], [])
        categories = {result["category"] for result in payload["results"]}
        self.assertEqual(categories, {"origin", "session", "timeout", "headers", "error_mapping"})
        statuses = {result["id"]: result["contract_status"] for result in payload["results"]}
        self.assertEqual(statuses["origin-cross-site-rejected-before-json-decode"], 403)
        self.assertEqual(statuses["session-subsequent-request-missing-id"], 400)
        self.assertEqual(statuses["session-expired-id-requires-new-initialize"], 404)
        self.assertEqual(statuses["session-delete-terminates-active-session"], 202)
        self.assertEqual(statuses["timeout-request-header-below-minimum-rejected"], 400)
        self.assertEqual(statuses["timeout-expired-maps-to-gateway-timeout"], 504)
        self.assertEqual(statuses["headers-accept-unsupported-rejected"], 406)
        self.assertEqual(statuses["headers-content-type-unsupported-rejected"], 415)
        self.assertEqual(statuses["error-application-jsonrpc-error-stays-json-response"], 200)
        self.assertTrue(all(result["adapter_ok"] for result in payload["results"]))
        self.assertEqual(payload["results"][12]["adapter_jsonrpc_error_code"], -32700)
        self.assertEqual(payload["results"][14]["adapter_jsonrpc_error_code"], -32602)

    def test_streamable_http_adapter_contract_reuses_protocol_core_handler(self):
        adapter = StreamableHttpAdapterContract()
        initialize = adapter.handle(
            method="POST",
            headers={"Origin": "http://localhost:3000", HTTP_ACCEPT_HEADER: "application/json", HTTP_CONTENT_TYPE_HEADER: "application/json"},
            body={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
        )
        session_id = initialize["headers"]["MCP-Session-Id"]

        response = adapter.handle(
            method="POST",
            headers={"MCP-Session-Id": session_id, HTTP_ACCEPT_HEADER: "application/json", HTTP_CONTENT_TYPE_HEADER: "application/json"},
            body={"jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {"toolset": "all", "limit": 2}},
        )

        self.assertEqual(response["http_status"], 200)
        self.assertEqual(response["body"]["result"]["tools"][0]["name"], "context_policy")
        self.assertIn(session_id, adapter.sessions)

    def test_streamable_http_fixture_cases_are_real_adapter_executable(self):
        spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
        responses = {case["id"]: adapter_response_for_case(case) for case in spec["cases"]}

        self.assertEqual(responses["origin-cross-site-rejected-before-json-decode"]["http_status"], 403)
        self.assertEqual(responses["session-delete-terminates-active-session"]["http_status"], 202)
        self.assertEqual(responses["session-subsequent-request-missing-id"]["body"]["error"]["code"], -32001)
        self.assertEqual(responses["timeout-request-header-below-minimum-rejected"]["body"]["error"]["code"], -32602)
        self.assertEqual(responses["headers-accept-unsupported-rejected"]["body"]["error"]["code"], -32007)
        self.assertEqual(responses["headers-content-type-unsupported-rejected"]["body"]["error"]["code"], -32008)
        self.assertIsNone(responses["notification-accepted-no-body"]["body"])


if __name__ == "__main__":
    unittest.main()
