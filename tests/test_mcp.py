"""
tests/test_mcp.py
文件说明：验证 Keepa MCP JSON-RPC stdio server。
主要职责：覆盖 initialize、tools/list、tools/call、错误与确认策略。
依赖边界：全部使用 fixture/dry-run，不访问真实 Keepa API。
"""

import json
import tempfile
import unittest
import base64
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
        self.assertIn("prompts", response["result"]["capabilities"])
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
        self.assertIn("keepa.research_brief_export", names)
        self.assertIn("keepa.docs_index", names)
        self.assertIn("keepa.docs_read", names)
        self.assertIn("keepa.context_policy", names)
        self.assertIn("keepa.resolve_research_target", names)
        self.assertIn("keepa.query_research_context", names)
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
        self.assertIn("keepa.cassettes_promote_and_verify", audit_names)
        self.assertNotIn("keepa.products_get", audit_names)

        reports = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "reports", "method": "tools/list", "params": {"toolset": "reports"}}),
            env={},
        )
        report_names = {item["name"] for item in reports["result"]["tools"]}
        self.assertEqual({"keepa.research_graph_merge", "keepa.reports_build", "keepa.browse_snapshot", "keepa.research_brief_export"}, report_names)

        docs = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "docs", "method": "tools/list", "params": {"toolset": "docs"}}),
            env={},
        )
        docs_names = {item["name"] for item in docs["result"]["tools"]}
        self.assertEqual({"keepa.docs_index", "keepa.docs_read", "keepa.context_policy", "keepa.query_research_context"}, docs_names)

        tracking = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tracking", "method": "tools/list", "params": {"toolset": "tracking-readonly"}}),
            env={},
        )
        tracking_names = {item["name"] for item in tracking["result"]["tools"]}
        self.assertIn("keepa.tracking_list", tracking_names)
        self.assertIn("keepa.tracking_get", tracking_names)
        self.assertIn("keepa.audit_cost", tracking_names)
        self.assertNotIn("tracking.add", tracking_names)

        all_tools = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "all", "method": "tools/list", "params": {"toolset": "all"}}),
            env={},
        )
        self.assertEqual(set(tool_names()), {item["name"] for item in all_tools["result"]["tools"]})

    def test_tools_list_supports_allow_and_exclude_filters(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "filtered",
                    "method": "tools/list",
                    "params": {
                        "allow_tools": ["keepa.context_policy", "keepa.resolve_research_target"],
                        "exclude_tools": ["keepa.context_policy"],
                    },
                }
            ),
            env={},
        )

        self.assertEqual(["keepa.resolve_research_target"], [item["name"] for item in response["result"]["tools"]])
        self.assertEqual(response["result"]["filters"]["allow_tools"], ["keepa.context_policy", "keepa.resolve_research_target"])
        self.assertEqual(response["result"]["filters"]["exclude_tools"], ["keepa.context_policy"])

    def test_tools_list_marks_inactive_tools_for_profile(self):
        response = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "profile", "method": "tools/list", "params": {"toolset": "all", "profile": "offline_fixture_only"}}),
            env={},
        )
        tools = {item["name"]: item for item in response["result"]["tools"]}

        self.assertEqual(response["result"]["profile"], "offline_fixture_only")
        self.assertIn("offline_fixture_only", response["result"]["available_profiles"])
        self.assertTrue(tools["keepa.context_policy"]["x-keepa"]["active"])
        self.assertFalse(tools["keepa.products_get"]["x-keepa"]["active"])
        self.assertIn("inactive_tool", tools["keepa.products_get"]["x-keepa"]["inactive_reason"])

    def test_tools_list_rejects_unknown_profile(self):
        response = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "bad-profile", "method": "tools/list", "params": {"profile": "unknown"}}),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["message"], "Invalid profile")
        self.assertIn("offline_fixture_only", response["error"]["data"]["available_profiles"])

    def test_tools_call_inactive_profile_returns_structured_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "inactive",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.products_get",
                        "arguments": {"asin": "B0D8W1YVBX", "domain": "US", "fixture": "product_B0D8W1YVBX_agent_eval.json", "profile": "offline_fixture_only"},
                    },
                }
            ),
            env={},
        )

        result = response["result"]
        structured = result["structuredContent"]
        self.assertTrue(result["isError"])
        self.assertFalse(structured["ok"])
        self.assertEqual(structured["error"]["kind"], "inactive_tool")
        self.assertEqual(structured["error"]["details"]["profile"], "offline_fixture_only")

    def test_prompts_list_and_get_return_agent_playbooks(self):
        listed = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "prompts", "method": "prompts/list", "params": {}}), env={})
        names = {item["name"] for item in listed["result"]["prompts"]}

        self.assertIn("keepa.product_research", names)
        self.assertIn("keepa.project_onboarding", names)
        self.assertIn("keepa.research_agent_start", names)

        prompt = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "prompt",
                    "method": "prompts/get",
                    "params": {"name": "keepa.product_research", "arguments": {"asin": "B0D8W1YVBX", "domain": "US", "goal": "deal"}},
                }
            ),
            env={},
        )
        message = prompt["result"]["messages"][0]
        self.assertEqual(message["role"], "user")
        self.assertIn("B0D8W1YVBX", message["content"]["text"])
        self.assertIn("keepa.workflow_plan", message["content"]["text"])

        research_start = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "research-start",
                    "method": "prompts/get",
                    "params": {"name": "keepa.research_agent_start", "arguments": {"query": "B001GZ6QEC", "domain": "US", "goal": "deal"}},
                }
            ),
            env={},
        )
        start_text = research_start["result"]["messages"][0]["content"]["text"]
        self.assertIn("keepa://context/policy", start_text)
        self.assertIn("keepa.resolve_research_target", start_text)

    def test_docs_tools_read_zread_resources_for_resource_limited_clients(self):
        index = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "docs-index", "method": "tools/call", "params": {"name": "keepa.docs_index", "arguments": {}}}),
            env={},
        )
        structured = index["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["command"], "docs.index")
        self.assertEqual(structured["data"]["stable_entrypoints"]["zread_current"], "keepa://zread/wiki/current")

        page = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "docs-read",
                    "method": "tools/call",
                    "params": {"name": "keepa.docs_read", "arguments": {"page": "1-gai-lan.md"}},
                }
            ),
            env={},
        )
        page_payload = page["result"]["structuredContent"]
        self.assertTrue(page_payload["ok"])
        self.assertEqual(page_payload["data"]["mime_type"], "text/markdown")
        self.assertIn("Keepa CLI", page_payload["data"]["text"])

    def test_context_policy_and_target_tools_are_local_mcp_tools(self):
        policy = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "policy", "method": "tools/call", "params": {"name": "keepa.context_policy", "arguments": {}}}),
            env={},
        )
        policy_payload = policy["result"]["structuredContent"]
        self.assertTrue(policy_payload["ok"])
        self.assertEqual(policy_payload["data"]["view"], "context_policy")
        self.assertFalse(policy_payload["data"]["live_keepa"]["allowed_by_default"])

        resolved = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "resolve",
                    "method": "tools/call",
                    "params": {"name": "keepa.resolve_research_target", "arguments": {"query": "B001GZ6QEC", "domain": "US"}},
                }
            ),
            env={},
        )
        resolved_payload = resolved["result"]["structuredContent"]
        self.assertEqual(resolved_payload["data"]["primary"]["type"], "asin")
        self.assertEqual(resolved_payload["data"]["next_actions"][0]["tool"], "keepa.products_get")

        context = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "context",
                    "method": "tools/call",
                    "params": {"name": "keepa.query_research_context", "arguments": {"target_type": "asin", "target_id": "B001GZ6QEC"}},
                }
            ),
            env={},
        )
        context_payload = context["result"]["structuredContent"]
        self.assertIn("keepa://asin/B001GZ6QEC/fixture", context_payload["data"]["recommended_read_order"])

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

    def test_tools_call_workflow_plan_returns_profile_policy(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "workflow-policy",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.workflow_plan",
                        "arguments": {
                            "name": "category-research",
                            "term": "home kitchen",
                            "domain": "US",
                            "hydrate_top": 2,
                            "profile": "offline_fixture_only",
                        },
                    },
                }
            ),
            env={},
        )

        structured = response["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["command"], "workflow.plan")
        self.assertEqual(structured["data"]["workflow_policy"]["planning_profile"], "offline_fixture_only")
        self.assertEqual(structured["data"]["workflow_policy"]["recommended_profile"], "dry_run_default")
        self.assertEqual(structured["data"]["workflow_policy"]["confirmation_policy"]["step_ids"], ["fetch-category-products"])
        self.assertEqual(structured["data"]["steps"][2]["mcp"]["tool"], "keepa.categories_products")
        self.assertFalse(structured["data"]["steps"][3]["mcp"]["active_in_recommended_profile"])

    def test_tools_call_report_and_tracking_workflow_profiles(self):
        report = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "report-workflow",
                    "method": "tools/call",
                    "params": {"name": "keepa.workflow_plan", "arguments": {"name": "report-research", "domain": "US", "goal": "deal"}},
                }
            ),
            env={},
        )
        report_data = report["result"]["structuredContent"]["data"]
        self.assertEqual(report_data["workflow_policy"]["recommended_toolset"], "reports")
        self.assertEqual(report_data["workflow_policy"]["recommended_profile"], "offline_fixture_only")
        self.assertEqual(report_data["workflow_inputs"]["graph_inputs"]["source"], "paths or resource_templates.research_graph")
        self.assertIn("merged_graph", report_data["artifacts"])
        self.assertIn("resource_templates", report_data["workflow_policy"])
        self.assertEqual(report_data["steps"][0]["mcp"]["toolset"], "reports")
        self.assertIn("workflow_inputs.graph_inputs", report_data["steps"][0]["input_refs"])
        self.assertEqual(report_data["totals"]["estimated_tokens"], 0)

        tracking = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "tracking-workflow",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.workflow_plan",
                        "arguments": {"name": "tracking-audit", "domain": "US", "asin": "B0D8W1YVBX"},
                    },
                }
            ),
            env={},
        )
        tracking_data = tracking["result"]["structuredContent"]["data"]
        self.assertEqual(tracking_data["workflow_policy"]["recommended_toolset"], "tracking-readonly")
        self.assertEqual(tracking_data["workflow_policy"]["recommended_profile"], "tracking_readonly")
        self.assertEqual(tracking_data["workflow_inputs"]["asin"]["value"], "B0D8W1YVBX")
        self.assertIn("tracking_detail", tracking_data["artifacts"])
        self.assertEqual(tracking_data["steps"][0]["mcp"]["toolset"], "tracking-readonly")
        self.assertIn("artifacts.tracking_list", tracking_data["steps"][2]["input_refs"])
        self.assertNotIn("tracking.add", {step["tool"] for step in tracking_data["steps"]})

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
        self.assertIn("keepa://tools/index", uris)
        self.assertIn("keepa://prompts/index", uris)
        self.assertIn("keepa://zread/wiki/current", uris)
        self.assertIn("keepa://zread/wiki/toc", uris)
        self.assertIn("keepa://zread/wiki/pages", uris)

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

    def test_zread_resources_read_current_toc_pages_and_page(self):
        current = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "zread-current", "method": "resources/read", "params": {"uri": "keepa://zread/wiki/current"}}),
            env={},
        )
        current_payload = json.loads(current["result"]["contents"][0]["text"])
        self.assertEqual(current_payload["version"], "2026-05-10-215740")
        self.assertEqual(current_payload["toc_resource"], "keepa://zread/wiki/toc")

        pages = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "zread-pages", "method": "resources/read", "params": {"uri": "keepa://zread/wiki/pages"}}),
            env={},
        )
        pages_payload = json.loads(pages["result"]["contents"][0]["text"])
        self.assertGreaterEqual(pages_payload["page_count"], 30)
        self.assertTrue(any(item["resource_uri"] == "keepa://zread/wiki/page/1-gai-lan" for item in pages_payload["pages"]))

        page = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "zread-page", "method": "resources/read", "params": {"uri": "keepa://zread/wiki/page/1-gai-lan"}}),
            env={},
        )
        content = page["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "text/markdown")
        self.assertIn("Keepa CLI", content["text"])

    def test_resources_templates_list_and_fixture_template_read(self):
        listed = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "templates", "method": "resources/templates/list", "params": {}}),
            env={},
        )
        templates = listed["result"]["resourceTemplates"]
        uri_templates = {item["uriTemplate"] for item in templates}

        self.assertIn("keepa://schema/{name}", uri_templates)
        self.assertIn("keepa://fixtures/{name}", uri_templates)
        self.assertIn("keepa://cache-key/{command}/{encoded_params}", uri_templates)
        self.assertIn("keepa://workflow/{encoded_params}/policy", uri_templates)
        self.assertIn("keepa://research/{cache_key}/brief", uri_templates)
        self.assertIn("keepa://research/{cache_key}/graph", uri_templates)
        self.assertIn("keepa://toolsets/{toolset}", uri_templates)
        self.assertIn("keepa://tools/{name}", uri_templates)
        self.assertIn("keepa://prompts/{name}", uri_templates)
        self.assertIn("keepa://asin/{asin}/fixture", uri_templates)
        self.assertIn("keepa://evidence/{encoded_logical_path}", uri_templates)
        self.assertIn("keepa://zread/wiki/page/{slug_or_file}", uri_templates)
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

    def test_workflow_policy_resource_reads_encoded_plan_params(self):
        params_token = base64.urlsafe_b64encode(
            json.dumps(
                {"name": "category-research", "term": "home kitchen", "domain": "US", "hydrate_top": 1},
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii").rstrip("=")

        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "workflow-policy-resource",
                    "method": "resources/read",
                    "params": {"uri": f"keepa://workflow/{params_token}/policy"},
                }
            ),
            env={},
        )

        content = response["result"]["contents"][0]
        payload = json.loads(content["text"])
        self.assertEqual(content["mimeType"], "application/json")
        self.assertEqual(payload["view"], "workflow_policy_resource")
        self.assertEqual(payload["workflow_inputs"]["term"]["value"], "home kitchen")
        self.assertIn("category_products", payload["artifacts"])
        self.assertEqual(payload["resource_templates"][0]["uri_template"], "keepa://workflow/{encoded_params}/policy")
        self.assertEqual(payload["workflow_policy"]["recommended_profile"], "dry_run_default")
        self.assertEqual(payload["workflow_policy"]["confirmation_policy"]["step_ids"], ["fetch-category-products"])
        self.assertEqual(payload["step_summary"][0]["mcp_tool"], "keepa.categories_search")
        self.assertIn("workflow_inputs.term", payload["step_summary"][0]["input_refs"])
        self.assertIn("artifacts.category_candidates", payload["step_summary"][0]["artifact_refs"])

        tracking_token = base64.urlsafe_b64encode(
            json.dumps(
                {"name": "tracking-audit", "domain": "US", "asin": "B0D8W1YVBX"},
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii").rstrip("=")
        tracking = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "workflow-policy-resource-tracking",
                    "method": "resources/read",
                    "params": {"uri": f"keepa://workflow/{tracking_token}/policy"},
                }
            ),
            env={},
        )
        tracking_payload = json.loads(tracking["result"]["contents"][0]["text"])
        self.assertEqual(tracking_payload["workflow_policy"]["recommended_toolset"], "tracking-readonly")
        self.assertEqual(tracking_payload["workflow_inputs"]["asin"]["value"], "B0D8W1YVBX")
        self.assertIn("tracking_detail", tracking_payload["artifacts"])
        self.assertEqual(tracking_payload["step_summary"][0]["mcp_tool"], "keepa.tracking_list")

    def test_tool_and_prompt_resources_support_schema_first_agent_discovery(self):
        toolset = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "toolset", "method": "resources/read", "params": {"uri": "keepa://toolsets/research"}}),
            env={},
        )
        toolset_payload = json.loads(toolset["result"]["contents"][0]["text"])
        self.assertEqual(toolset_payload["toolset"], "research")
        self.assertTrue(any(item["resource_uri"] == "keepa://tools/keepa.products_get" for item in toolset_payload["tools"]))

        tool = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tool", "method": "resources/read", "params": {"uri": "keepa://tools/keepa.products_get"}}),
            env={},
        )
        tool_payload = json.loads(tool["result"]["contents"][0]["text"])
        self.assertEqual(tool_payload["tool"]["name"], "keepa.products_get")
        self.assertEqual(tool_payload["execution"]["service_command"], "products.get")
        self.assertIn("inputSchema", tool_payload["tool"])

        prompts = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "prompts-index", "method": "resources/read", "params": {"uri": "keepa://prompts/index"}}),
            env={},
        )
        prompts_payload = json.loads(prompts["result"]["contents"][0]["text"])
        self.assertGreaterEqual(prompts_payload["prompt_count"], 4)
        self.assertTrue(any(item["resource_uri"] == "keepa://prompts/keepa.project_onboarding" for item in prompts_payload["prompts"]))

        prompt = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "prompt-resource", "method": "resources/read", "params": {"uri": "keepa://prompts/keepa.project_onboarding"}}),
            env={},
        )
        prompt_payload = json.loads(prompt["result"]["contents"][0]["text"])
        self.assertEqual(prompt_payload["name"], "keepa.project_onboarding")
        self.assertIn("keepa://zread/wiki/current", prompt_payload["rendered_prompt"]["messages"][0]["content"]["text"])

    def test_resource_templates_read_cache_key_asin_and_evidence(self):
        params_token = base64.urlsafe_b64encode(b'{"asin":"B0D8W1YVBX","domain":"US"}').decode("ascii").rstrip("=")
        cache_key = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "cache-key",
                    "method": "resources/read",
                    "params": {"uri": f"keepa://cache-key/products.get/{params_token}"},
                }
            ),
            env={},
        )
        cache_payload = json.loads(cache_key["result"]["contents"][0]["text"])
        self.assertEqual(cache_payload["command"], "products.get")
        self.assertTrue(cache_payload["cache_key"].startswith("products.get:"))

        asin_resource = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "asin-fixtures",
                    "method": "resources/read",
                    "params": {"uri": "keepa://asin/B0D8W1YVBX/fixture"},
                }
            ),
            env={},
        )
        asin_payload = json.loads(asin_resource["result"]["contents"][0]["text"])
        self.assertGreaterEqual(asin_payload["match_count"], 1)
        self.assertTrue(any(item["uri"].startswith("keepa://fixtures/") for item in asin_payload["fixtures"]))

        logical_path = "evidence/tasks/20260510-zread-review-mcp-resource-templates-graph-diagnostics.md"
        evidence_token = base64.urlsafe_b64encode(logical_path.encode("utf-8")).decode("ascii").rstrip("=")
        evidence = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "evidence",
                    "method": "resources/read",
                    "params": {"uri": f"keepa://evidence/{evidence_token}"},
                }
            ),
            env={},
        )
        evidence_content = evidence["result"]["contents"][0]
        self.assertEqual(evidence_content["mimeType"], "text/markdown")
        self.assertIn("GitHub CI", evidence_content["text"])

    def test_resource_templates_read_research_cache_and_graph_root(self):
        session = AgentSession(env={})
        product = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "product",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.products_get",
                        "arguments": {
                            "asin": "B0D8W1YVBX",
                            "domain": "US",
                            "fixture": "product_B0D8W1YVBX_agent_eval.json",
                            "agent_view": True,
                            "view": "summary",
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]
        cache_key = product["cache_key"]

        research_resource = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "research", "method": "resources/read", "params": {"uri": f"keepa://research/{cache_key}"}}),
            env={},
            session=session,
        )
        research_payload = json.loads(research_resource["result"]["contents"][0]["text"])
        self.assertTrue(research_payload["found"])
        self.assertEqual(research_payload["cache_key"], cache_key)
        self.assertGreaterEqual(research_payload["research_graph_count"], 1)
        self.assertIn("evidence_index", research_payload)

        root = product["data"]["products"][0]["research_graph"]["root"]
        graph_resource = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "graph-root", "method": "resources/read", "params": {"uri": f"keepa://graphs/{root}"}}),
            env={},
            session=session,
        )
        graph_payload = json.loads(graph_resource["result"]["contents"][0]["text"])
        self.assertEqual(graph_payload["root"], root)
        self.assertGreaterEqual(graph_payload["match_count"], 1)
        self.assertTrue(any(item["source"] == "session_cache" for item in graph_payload["matches"]))

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

    def test_research_brief_export_tool_and_resources_use_session_cache(self):
        session = AgentSession(env={})
        category = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "brief-cat",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.categories_search",
                        "arguments": {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]
        seller = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "brief-seller",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.sellers_get",
                        "arguments": {"seller": "A2L77EE7U53NWQ", "domain": "US", "storefront": True, "fixture": "seller_A2L77EE7U53NWQ.json"},
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]
        exported = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "brief",
                    "method": "tools/call",
                    "params": {
                        "name": "keepa.research_brief_export",
                        "arguments": {"payload": [category, seller], "title": "agent selection brief"},
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]

        self.assertTrue(exported["ok"])
        self.assertEqual(exported["command"], "research_brief.export")
        cache_key = exported["cache_key"]
        self.assertEqual(exported["data"]["brief"]["view"], "research_brief_export")
        self.assertGreaterEqual(exported["data"]["brief"]["input_summary"]["research_graph_count"], 2)

        brief_resource = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "brief-resource", "method": "resources/read", "params": {"uri": f"keepa://research/{cache_key}/brief"}}),
            env={},
            session=session,
        )
        brief_payload = json.loads(brief_resource["result"]["contents"][0]["text"])
        self.assertTrue(brief_payload["found"])
        self.assertEqual(brief_payload["brief"]["id"], exported["data"]["brief"]["id"])

        graph_resource = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "brief-graph", "method": "resources/read", "params": {"uri": f"keepa://research/{cache_key}/graph"}}),
            env={},
            session=session,
        )
        graph_payload = json.loads(graph_resource["result"]["contents"][0]["text"])
        self.assertTrue(graph_payload["found"])
        self.assertGreaterEqual(graph_payload["input_summary"]["research_graph_count"], 2)

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
                        "arguments": {"graph": [graph_a, graph_b], "root": "agent_research", "prefer_source": "1"},
                    },
                }
            ),
            env={},
        )

        diagnostics = merged["result"]["structuredContent"]["data"]["diagnostics"]
        self.assertEqual(diagnostics["duplicate_node_count"], 1)
        self.assertEqual(diagnostics["conflict_count"], 1)
        self.assertEqual(diagnostics["conflicts"][0]["id"], "product:B0TEST")
        diff = merged["result"]["structuredContent"]["data"]["diff"]
        self.assertEqual(diff["changed_node_count"], 1)
        self.assertEqual(diff["preferred_source"]["index"], 1)
        self.assertEqual(diff["resolutions"][0]["selected_label"], "New title")


if __name__ == "__main__":
    unittest.main()
