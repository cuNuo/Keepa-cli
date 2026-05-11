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

from keepa_cli.agent.mcp_http_contract import evaluate_streamable_http_contract, is_origin_allowed, is_visible_ascii_session_id


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

    def test_streamable_http_fixture_covers_required_boundaries(self):
        spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload = evaluate_streamable_http_contract(spec)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing_categories"], [])
        categories = {result["category"] for result in payload["results"]}
        self.assertEqual(categories, {"origin", "session", "error_mapping"})
        statuses = {result["id"]: result["contract_status"] for result in payload["results"]}
        self.assertEqual(statuses["origin-cross-site-rejected-before-json-decode"], 403)
        self.assertEqual(statuses["session-subsequent-request-missing-id"], 400)
        self.assertEqual(statuses["session-expired-id-requires-new-initialize"], 404)
        self.assertEqual(statuses["error-application-jsonrpc-error-stays-json-response"], 200)


if __name__ == "__main__":
    unittest.main()
