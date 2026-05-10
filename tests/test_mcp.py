"""
tests/test_mcp.py
文件说明：验证 Keepa MCP JSON-RPC stdio server。
主要职责：覆盖 initialize、tools/list、tools/call、错误与确认策略。
依赖边界：全部使用 fixture/dry-run，不访问真实 Keepa API。
"""

import json
import unittest

from keepa_cli.agent.mcp import handle_mcp_message, iter_mcp_output
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import tool_names


class McpProtocolTests(unittest.TestCase):
    def test_initialize_returns_server_info(self):
        response = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), env={})

        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "keepa")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_tools_list_contains_initial_keepa_tools(self):
        response = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}), env={})
        names = {item["name"] for item in response["result"]["tools"]}

        self.assertEqual(set(tool_names()), names)
        self.assertIn("keepa.products_get", names)
        self.assertIn("keepa.categories_search", names)
        products = next(item for item in response["result"]["tools"] if item["name"] == "keepa.products_get")
        self.assertIn("inputSchema", products)
        self.assertIn("outputSchema", products)
        self.assertEqual(products["x-keepa"]["service_command"], "products.get")

    def test_tools_call_categories_search_uses_fixture(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.categories_search",
                        "arguments": {
                            "term": "home kitchen",
                            "domain": "US",
                            "fixture": "category_search_home.json",
                        },
                    },
                }
            ),
            env={},
        )

        result = response["result"]
        structured = result["structuredContent"]
        self.assertFalse(result["isError"])
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["command"], "categories.search")
        self.assertIn("cache_key", structured)
        self.assertEqual(structured["data"]["view"], "category_search")
        self.assertTrue(structured["data"]["category_candidates"])
        text_payload = json.loads(result["content"][0]["text"])
        self.assertEqual(text_payload["command"], "categories.search")

    def test_unknown_tool_returns_json_rpc_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "bad",
                    "method": "tools/call",
                    "params": {"name": "keepa.unknown", "arguments": {}},
                }
            ),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["data"]["tool"], "keepa.unknown")

    def test_invalid_tool_arguments_return_json_rpc_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "invalid",
                    "method": "tools/call",
                    "params": {"name": "keepa.categories_search", "arguments": {"domain": "US", "extra": True}},
                }
            ),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("missing required argument: term", response["error"]["data"]["errors"])
        self.assertIn("unsupported argument: extra", response["error"]["data"]["errors"])

    def test_high_cost_tool_without_confirmation_returns_structured_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.categories_products",
                        "arguments": {"category": "172282", "domain": "US"},
                    },
                }
            ),
            env={},
        )

        result = response["result"]
        structured = result["structuredContent"]
        self.assertTrue(result["isError"])
        self.assertFalse(structured["ok"])
        self.assertEqual(structured["error"]["kind"], "confirmation_required")
        self.assertEqual(structured["budget_ledger"]["blocked_actions"][0]["tool"], "keepa.categories_products")

    def test_iter_mcp_output_keeps_session_cache_across_lines(self):
        first = {
            "jsonrpc": "2.0",
            "id": "a",
            "method": "tools/call",
            "params": {
                "name": "keepa.categories_search",
                "arguments": {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
            },
        }
        second = {
            "jsonrpc": "2.0",
            "id": "b",
            "method": "tools/call",
            "params": {
                "name": "keepa.categories_search",
                "arguments": {"domain": "US", "fixture": "category_search_home.json", "term": "home kitchen"},
            },
        }
        lines = iter_mcp_output(json.dumps(first) + "\n" + json.dumps(second), env={})
        responses = [json.loads(line) for line in lines]
        first_payload = responses[0]["result"]["structuredContent"]
        second_payload = responses[1]["result"]["structuredContent"]

        self.assertFalse(first_payload["cache_hit"])
        self.assertTrue(second_payload["cache_hit"])
        self.assertEqual(first_payload["cache_key"], second_payload["cache_key"])
        self.assertEqual(second_payload["budget_ledger"]["cache_hits"], 1)
        self.assertTrue(second_payload["data"]["provenance"]["mcp"]["cache_hit"])

    def test_tools_call_can_use_injected_session(self):
        calls = []

        def runner(command, params):
            calls.append(command)
            return {"ok": True, "command": command, "request": {}, "token_bucket": {}, "data": {"ok": "fake"}}

        session = AgentSession(env={}, runner=runner)
        raw = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "fake",
                "method": "tools/call",
                "params": {"name": "keepa.audit_cost", "arguments": {"target_command": "products.get"}},
            }
        )
        response = handle_mcp_message(raw, env={}, session=session)

        self.assertEqual(calls, ["audit.cost"])
        self.assertTrue(response["result"]["structuredContent"]["ok"])


if __name__ == "__main__":
    unittest.main()
