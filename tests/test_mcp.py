"""
tests/test_mcp.py
文件说明：验证 Keepa MCP JSON-RPC stdio server。
主要职责：覆盖 initialize、tools/list、tools/call、错误与确认策略。
依赖边界：全部使用 fixture/dry-run，不访问真实 Keepa API。
"""

import json
import tempfile
import unittest
from pathlib import Path

from keepa_cli.agent.mcp import handle_mcp_message, iter_mcp_output
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import tool_names


class McpProtocolTests(unittest.TestCase):
    def test_initialize_returns_server_info(self):
        response = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), env={})

        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "keepa")
        self.assertIn("tools", response["result"]["capabilities"])
        self.assertIn("resources", response["result"]["capabilities"])
        self.assertTrue(response["result"]["capabilities"]["resources"]["templatesChanged"] is False)

    def test_tools_list_contains_initial_keepa_tools(self):
        response = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}), env={})
        names = {item["name"] for item in response["result"]["tools"]}

        self.assertEqual(response["result"]["toolset"], "research")
        self.assertIn("keepa.products_get", names)
        self.assertIn("keepa.products_compare", names)
        self.assertIn("keepa.categories_search", names)
        self.assertIn("keepa.deals_query", names)
        self.assertIn("keepa.research_graph_merge", names)
        self.assertNotIn("keepa.audit_cost", names)
        products = next(item for item in response["result"]["tools"] if item["name"] == "keepa.products_get")
        self.assertIn("inputSchema", products)
        self.assertIn("outputSchema", products)
        self.assertEqual(products["x-keepa"]["service_command"], "products.get")
        compare = next(item for item in response["result"]["tools"] if item["name"] == "keepa.products_compare")
        self.assertEqual(compare["x-keepa"]["service_command"], "products.compare")
        self.assertIn("risk", compare["description"])

    def test_tools_list_supports_named_toolsets(self):
        audit = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "audit", "method": "tools/list", "params": {"toolset": "audit"}}),
            env={},
        )
        audit_names = {item["name"] for item in audit["result"]["tools"]}
        self.assertIn("keepa.audit_cost", audit_names)
        self.assertIn("keepa.cassettes_promote", audit_names)
        self.assertNotIn("keepa.products_get", audit_names)

        reports = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "reports", "method": "tools/list", "params": {"toolset": "reports"}}),
            env={},
        )
        report_names = {item["name"] for item in reports["result"]["tools"]}
        self.assertEqual({"keepa.reports_build", "keepa.browse_snapshot"}, report_names)

        tracking = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tracking", "method": "tools/list", "params": {"toolset": "tracking-readonly"}}),
            env={},
        )
        tracking_names = {item["name"] for item in tracking["result"]["tools"]}
        self.assertIn("keepa.tracking_list", tracking_names)
        self.assertIn("keepa.tracking_get", tracking_names)
        self.assertNotIn("tracking.add", tracking_names)

        all_tools = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "all", "method": "tools/list", "params": {"toolset": "all"}}),
            env={},
        )
        self.assertEqual(set(tool_names()), {item["name"] for item in all_tools["result"]["tools"]})

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
        self.assertGreaterEqual(structured["data"]["research_graph"]["entity_counts"]["category"], 1)
        text_payload = json.loads(result["content"][0]["text"])
        self.assertEqual(text_payload["command"], "categories.search")

    def test_tools_call_categories_finder_selection_is_local_scaffold(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "finder-selection",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.categories_finder_selection",
                        "arguments": {
                            "category": "1055398",
                            "domain": "US",
                            "sales_rank_max": 15000,
                            "min_reviews": 100,
                        },
                    },
                }
            ),
            env={},
        )

        structured = response["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["command"], "categories.finder-selection")
        self.assertEqual(structured["data"]["view"], "finder_selection_scaffold")
        self.assertEqual(structured["data"]["selection"]["categories_include"], [1055398])
        self.assertEqual(structured["budget_ledger"]["session_consumed"], 0)

    def test_tools_call_deals_query_returns_deal_research_graph(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "deals",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.deals_query",
                        "arguments": {
                            "selection_file": "tests/fixtures/deals_selection.json",
                            "domain": "US",
                            "fixture": "deals_home.json",
                        },
                    },
                }
            ),
            env={},
        )

        structured = response["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["command"], "deals.query")
        self.assertEqual(structured["data"]["research_graph"]["entity_counts"]["deal"], 1)
        self.assertEqual(structured["data"]["research_graph"]["entity_counts"]["product"], 1)

    def test_tools_call_products_compare_returns_semantic_agent_quality(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "compare",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.products_compare",
                        "arguments": {
                            "asin": ["B0D8W1YVBX", "B0EVALCMP1", "B0EVALCMP2"],
                            "domain": "US",
                            "fixture": "products_compare_agent_eval.json",
                            "full": True,
                            "view": "deal",
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
        self.assertEqual(structured["command"], "products.compare")
        self.assertEqual(structured["data"]["product_count"], 3)
        self.assertIn("data_missing", structured["data"]["risk_summary"]["by_code"])
        self.assertGreaterEqual(structured["data"]["research_graph"]["entity_counts"]["product"], 3)

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

    def test_tools_list_rejects_unknown_toolset(self):
        response = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "bad-toolset", "method": "tools/list", "params": {"toolset": "writes"}}),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["message"], "Invalid toolset")
        self.assertIn("research", response["error"]["data"]["available_toolsets"])

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

    def test_resources_list_and_read_expose_agent_contract_assets(self):
        listed = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "resources", "method": "resources/list", "params": {}}), env={})
        resources = listed["result"]["resources"]
        uris = {item["uri"] for item in resources}

        self.assertIn("keepa://schema/products-agent-view", uris)
        self.assertIn("keepa://fixtures/manifest", uris)
        self.assertIn("keepa://guides/cassette-promotion", uris)
        self.assertIn("keepa://evidence/recent", uris)

        guide = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "guide",
                    "method": "resources/read",
                    "params": {"uri": "keepa://guides/cassette-promotion"},
                }
            ),
            env={},
        )

        content = guide["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "text/markdown")
        self.assertIn("cassettes promote", content["text"])

    def test_resources_templates_list_and_fixture_template_read(self):
        listed = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "templates", "method": "resources/templates/list", "params": {}}),
            env={},
        )
        templates = listed["result"]["resourceTemplates"]
        uri_templates = {item["uriTemplate"] for item in templates}

        self.assertIn("keepa://schema/{name}", uri_templates)
        self.assertIn("keepa://fixtures/{name}", uri_templates)
        fixture = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "fixture",
                    "method": "resources/read",
                    "params": {"uri": "keepa://fixtures/agent_eval_category_search_output.json"},
                }
            ),
            env={},
        )

        content = fixture["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "application/json")
        self.assertIn('"research_graph"', content["text"])

    def test_tools_call_with_chunks_returns_compact_text_resource_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            chunks_dir = Path(temp_dir) / "chunks"
            response = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "chunks",
                        "method": "tools/call",
                        "params": {
                            "name": "keepa.products_get",
                            "arguments": {
                                "asin": "B0D8W1YVBX",
                                "domain": "US",
                                "fixture": "product_B0D8W1YVBX_agent_eval.json",
                                "agent_view": True,
                                "view": "summary",
                                "fields": "agent_brief,identity,pricing,data_quality,next_actions,selection_signals,research_graph,evidence_index",
                                "chunks_dir": str(chunks_dir),
                            },
                        },
                    }
                ),
                env={},
            )

            result = response["result"]
            structured = result["structuredContent"]
            text_payload = json.loads(result["content"][0]["text"])

            self.assertTrue(structured["ok"])
            self.assertIn("products", structured["data"])
            self.assertIn("mcp_resource_manifest", text_payload)
            self.assertGreaterEqual(text_payload["mcp_resource_manifest"]["resource_count"], 3)
            self.assertNotIn("temporal_features", json.dumps(text_payload.get("data", {})))
            uri = text_payload["mcp_resource_manifest"]["resources"][0]["uri"]
            chunk = handle_mcp_message(
                json.dumps({"jsonrpc": "2.0", "id": "chunk", "method": "resources/read", "params": {"uri": uri}}),
                env={},
            )
            self.assertIn("contents", chunk["result"])

    def test_research_graph_merge_tool_merges_inline_graphs(self):
        category = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "cat",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.categories_search",
                        "arguments": {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
                    },
                }
            ),
            env={},
        )["result"]["structuredContent"]
        seller = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "seller",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.sellers_get",
                        "arguments": {"seller": "A2L77EE7U53NWQ", "domain": "US", "storefront": True, "fixture": "seller_A2L77EE7U53NWQ.json"},
                    },
                }
            ),
            env={},
        )["result"]["structuredContent"]
        merged = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "merge",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.research_graph_merge",
                        "arguments": {"graph": [category, seller], "root": "agent_research"},
                    },
                }
            ),
            env={},
        )

        structured = merged["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["data"]["view"], "research_graph_merge")
        self.assertEqual(structured["data"]["input_graph_count"], 2)
        self.assertGreaterEqual(structured["data"]["summary"]["entity_counts"]["category"], 1)
        self.assertGreaterEqual(structured["data"]["summary"]["entity_counts"]["seller"], 1)
        self.assertIn("diagnostics", structured["data"])
        self.assertIn("diagnostics", structured["data"]["summary"])
        self.assertGreaterEqual(structured["data"]["diagnostics"]["highest_source_weight"], 1)
        self.assertGreaterEqual(structured["data"]["graph"]["sources"][0]["source_weight"], 1)

    def test_research_graph_merge_reports_duplicate_label_conflicts(self):
        graph_a = {
            "root": "product:B0TEST",
            "entity_counts": {"product": 1},
            "nodes": [{"id": "product:B0TEST", "type": "product", "label": "Old title"}],
            "edges": [],
        }
        graph_b = {
            "root": "product:B0TEST",
            "entity_counts": {"product": 1},
            "nodes": [{"id": "product:B0TEST", "type": "product", "label": "New title"}],
            "edges": [],
        }
        merged = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "merge-conflict",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.research_graph_merge",
                        "arguments": {"graph": [graph_a, graph_b], "root": "agent_research"},
                    },
                }
            ),
            env={},
        )

        diagnostics = merged["result"]["structuredContent"]["data"]["diagnostics"]
        self.assertEqual(diagnostics["duplicate_node_count"], 1)
        self.assertEqual(diagnostics["conflict_count"], 1)
        self.assertEqual(diagnostics["conflicts"][0]["id"], "product:B0TEST")


if __name__ == "__main__":
    unittest.main()
