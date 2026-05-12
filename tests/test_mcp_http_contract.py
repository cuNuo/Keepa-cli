"""
tests/test_mcp_http_contract.py
文件说明：验证 Streamable HTTP 前置协议合约 fixture。
主要职责：确保 Origin、MCP-Session-Id 与错误映射在 HTTP adapter 实现前已有可回归边界。
依赖边界：不启动 HTTP server，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from keepa_cli.agent.mcp_http_contract import (
    StreamableHttpAdapterContract,
    adapter_response_for_case,
    evaluate_streamable_http_contract,
    is_origin_allowed,
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

    def test_streamable_http_fixture_covers_required_boundaries(self):
        spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload = evaluate_streamable_http_contract(spec)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing_categories"], [])
        categories = {result["category"] for result in payload["results"]}
        self.assertEqual(categories, {"origin", "session", "timeout", "error_mapping"})
        statuses = {result["id"]: result["contract_status"] for result in payload["results"]}
        self.assertEqual(statuses["origin-cross-site-rejected-before-json-decode"], 403)
        self.assertEqual(statuses["session-subsequent-request-missing-id"], 400)
        self.assertEqual(statuses["session-expired-id-requires-new-initialize"], 404)
        self.assertEqual(statuses["timeout-request-header-below-minimum-rejected"], 400)
        self.assertEqual(statuses["timeout-expired-maps-to-gateway-timeout"], 504)
        self.assertEqual(statuses["error-application-jsonrpc-error-stays-json-response"], 200)
        self.assertTrue(all(result["adapter_ok"] for result in payload["results"]))
        self.assertEqual(payload["results"][10]["adapter_jsonrpc_error_code"], -32700)
        self.assertEqual(payload["results"][12]["adapter_jsonrpc_error_code"], -32602)

    def test_streamable_http_adapter_contract_reuses_raw_mcp_handler(self):
        adapter = StreamableHttpAdapterContract()
        initialize = adapter.handle(
            method="POST",
            headers={"Origin": "http://localhost:3000"},
            body={"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}},
        )
        session_id = initialize["headers"]["MCP-Session-Id"]

        response = adapter.handle(
            method="POST",
            headers={"MCP-Session-Id": session_id},
            body={"jsonrpc": "2.0", "id": "tools", "method": "tools/list", "params": {"toolset": "all", "limit": 2}},
        )

        self.assertEqual(response["http_status"], 200)
        self.assertEqual(response["body"]["result"]["tools"][0]["name"], "context_policy")
        self.assertIn(session_id, adapter.sessions)

    def test_streamable_http_fixture_cases_are_real_adapter_executable(self):
        spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
        responses = {case["id"]: adapter_response_for_case(case) for case in spec["cases"]}

        self.assertEqual(responses["origin-cross-site-rejected-before-json-decode"]["http_status"], 403)
        self.assertEqual(responses["session-subsequent-request-missing-id"]["body"]["error"]["code"], -32001)
        self.assertEqual(responses["timeout-request-header-below-minimum-rejected"]["body"]["error"]["code"], -32602)
        self.assertIsNone(responses["notification-accepted-no-body"]["body"])


if __name__ == "__main__":
    unittest.main()
