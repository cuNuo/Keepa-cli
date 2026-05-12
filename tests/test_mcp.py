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
from keepa_cli.agent.mcp_core import DEFAULT_MCP_PROTOCOL_CORE, MCPProtocolCore
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import tool_names


class McpProtocolTests(unittest.TestCase):
    def test_stdio_wrapper_delegates_to_protocol_core(self):
        raw = json.dumps({"jsonrpc": "2.0", "id": "core", "method": "tools/list", "params": {"toolset": "all", "limit": 2}})

        self.assertEqual(handle_mcp_message(raw, env={}), DEFAULT_MCP_PROTOCOL_CORE.handle_message(raw, env={}))

    def test_protocol_core_keeps_session_cache_across_calls(self):
        core = MCPProtocolCore()
        session = AgentSession(env={})

        first = core.handle_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "product",
                    "method": "tools/call",
                    "params": {"name": "products_get", "arguments": {"asin": "B0TEST", "fixture": "product_agent_view_B0TEST.json"}},
                }
            ),
            env={},
            session=session,
        )
        cache_key = first["result"]["structuredContent"]["cache_key"]
        second = core.handle_message(
            json.dumps({"jsonrpc": "2.0", "id": "resource", "method": "resources/read", "params": {"uri": f"keepa://research/{cache_key}"}}),
            env={},
            session=session,
        )

        self.assertEqual(second["result"]["contents"][0]["uri"], f"keepa://research/{cache_key}")

    def test_initialize_returns_server_info(self):
        response = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), env={})

        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(response["result"]["serverInfo"]["name"], "keepa_mcp")
        self.assertEqual(response["result"]["serverInfo"]["title"], "Keepa CLI MCP")
        self.assertIn("tools", response["result"]["capabilities"])
        self.assertIn("resources", response["result"]["capabilities"])
        self.assertIn("prompts", response["result"]["capabilities"])
        self.assertTrue(response["result"]["capabilities"]["resources"]["templatesChanged"] is False)

    def test_tools_list_contains_initial_keepa_tools(self):
        response = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}), env={})
        names = {item["name"] for item in response["result"]["tools"]}

        self.assertEqual(response["result"]["toolset"], "research")
        self.assertIn("products_get", names)
        self.assertIn("products_compare", names)
        self.assertIn("categories_search", names)
        self.assertIn("deals_query", names)
        self.assertIn("research_graph_merge", names)
        self.assertIn("research_brief_export", names)
        self.assertIn("docs_index", names)
        self.assertIn("docs_read", names)
        self.assertIn("context_policy", names)
        self.assertIn("resolve_research_target", names)
        self.assertIn("query_research_context", names)
        self.assertNotIn("audit_cost", names)
        products = next(item for item in response["result"]["tools"] if item["name"] == "products_get")
        self.assertIn("inputSchema", products)
        self.assertIn("outputSchema", products)
        self.assertEqual(products["title"], "Keepa Products Get")
        self.assertEqual(products["execution"]["taskSupport"], "forbidden")
        self.assertTrue(products["annotations"]["openWorldHint"])
        self.assertTrue(products["annotations"]["readOnlyHint"])
        self.assertEqual(products["x-keepa"]["service_command"], "products.get")
        compare = next(item for item in response["result"]["tools"] if item["name"] == "products_compare")
        self.assertEqual(compare["x-keepa"]["service_command"], "products.compare")
        self.assertIn("risk", compare["description"])

    def test_tools_list_supports_named_toolsets(self):
        audit = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "audit", "method": "tools/list", "params": {"toolset": "audit"}}),
            env={},
        )
        audit_names = {item["name"] for item in audit["result"]["tools"]}
        self.assertIn("audit_cost", audit_names)
        self.assertIn("cassettes_promote", audit_names)
        self.assertIn("cassettes_promote_and_verify", audit_names)
        self.assertNotIn("products_get", audit_names)
        promote = next(item for item in audit["result"]["tools"] if item["name"] == "cassettes_promote")
        self.assertFalse(promote["annotations"]["readOnlyHint"])
        self.assertTrue(promote["annotations"]["destructiveHint"])

        reports = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "reports", "method": "tools/list", "params": {"toolset": "reports"}}),
            env={},
        )
        report_names = {item["name"] for item in reports["result"]["tools"]}
        self.assertEqual(
            {
                "research_graph_merge",
                "reports_build",
                "browse_snapshot",
                "research_brief_export",
                "figures_research",
            },
            report_names,
        )

        docs = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "docs", "method": "tools/list", "params": {"toolset": "docs"}}),
            env={},
        )
        docs_names = {item["name"] for item in docs["result"]["tools"]}
        self.assertEqual(
            {"docs_index", "docs_read", "context_policy", "query_research_context", "agent_profile_generate"},
            docs_names,
        )

        business = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "business", "method": "tools/list", "params": {"toolset": "business"}}),
            env={},
        )
        business_names = {item["name"] for item in business["result"]["tools"]}
        self.assertEqual({"find_fast_movers", "inventory_audit", "market_opportunity", "agent_profile_generate"}, business_names)

        tracking = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tracking", "method": "tools/list", "params": {"toolset": "tracking-readonly"}}),
            env={},
        )
        tracking_names = {item["name"] for item in tracking["result"]["tools"]}
        self.assertIn("tracking_list", tracking_names)
        self.assertIn("tracking_get", tracking_names)
        self.assertIn("audit_cost", tracking_names)
        self.assertNotIn("tracking.add", tracking_names)

        all_default = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "all-default", "method": "tools/list", "params": {"toolset": "all"}}),
            env={},
        )
        self.assertLessEqual(len(all_default["result"]["tools"]), 8)
        self.assertEqual(
            ["context_policy", "docs_index", "workflow_plan", "agent_profile_generate"],
            [item["name"] for item in all_default["result"]["tools"][:4]],
        )
        self.assertIn("nextCursor", all_default["result"])
        self.assertTrue(all_default["result"]["_meta"]["has_more"])

        all_tools = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "all", "method": "tools/list", "params": {"toolset": "all", "limit": 100}}),
            env={},
        )
        self.assertEqual(set(tool_names()), {item["name"] for item in all_tools["result"]["tools"]})

    def test_list_methods_support_mcp_cursor_pagination(self):
        first_tools = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tools-page-1", "method": "tools/list", "params": {"toolset": "all", "limit": 3}}),
            env={},
        )
        self.assertEqual(len(first_tools["result"]["tools"]), 3)
        self.assertIn("nextCursor", first_tools["result"])
        self.assertEqual(first_tools["result"]["_meta"]["total_count"], len(tool_names()))
        self.assertEqual(first_tools["result"]["_meta"]["cursor_schema_version"], "2026-05-12.1")
        self.assertEqual(first_tools["result"]["_meta"]["cursor_collection"], "tools")

        second_tools = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "tools-page-2",
                    "method": "tools/list",
                    "params": {"toolset": "all", "limit": 3, "cursor": first_tools["result"]["nextCursor"]},
                }
            ),
            env={},
        )
        first_names = {item["name"] for item in first_tools["result"]["tools"]}
        second_names = {item["name"] for item in second_tools["result"]["tools"]}
        self.assertFalse(first_names.intersection(second_names))
        self.assertEqual(second_tools["result"]["_meta"]["offset"], 3)

        wrong_filter = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "tools-page-wrong-filter",
                    "method": "tools/list",
                    "params": {"toolset": "research", "limit": 3, "cursor": first_tools["result"]["nextCursor"]},
                }
            ),
            env={},
        )
        self.assertEqual(wrong_filter["error"]["code"], -32602)
        self.assertEqual(wrong_filter["error"]["message"], "Invalid pagination params")
        self.assertIn("cursor filters do not match", wrong_filter["error"]["data"]["message"])

        resources = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "resources-page", "method": "resources/list", "params": {"limit": 2}}),
            env={},
        )
        self.assertEqual(len(resources["result"]["resources"]), 2)
        self.assertIn("nextCursor", resources["result"])
        self.assertIn("title", resources["result"]["resources"][0])
        self.assertEqual(resources["result"]["_meta"]["cursor_collection"], "resources")

        wrong_collection = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "resources-page-wrong-cursor",
                    "method": "resources/list",
                    "params": {"limit": 2, "cursor": first_tools["result"]["nextCursor"]},
                }
            ),
            env={},
        )
        self.assertEqual(wrong_collection["error"]["code"], -32602)
        self.assertIn("cursor collection does not match resources", wrong_collection["error"]["data"]["message"])

        prompts = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "prompts-page", "method": "prompts/list", "params": {"limit": 2}}),
            env={},
        )
        self.assertEqual(len(prompts["result"]["prompts"]), 2)
        self.assertIn("nextCursor", prompts["result"])
        self.assertIn("title", prompts["result"]["prompts"][0])
        self.assertEqual(prompts["result"]["_meta"]["cursor_collection"], "prompts")

        templates = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "templates-page", "method": "resources/templates/list", "params": {"limit": 1}}),
            env={},
        )
        self.assertEqual(len(templates["result"]["resourceTemplates"]), 1)
        self.assertIn("nextCursor", templates["result"])
        self.assertEqual(templates["result"]["_meta"]["cursor_collection"], "resourceTemplates")

    def test_list_methods_have_stable_first_page_order(self):
        tools = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tools-order", "method": "tools/list", "params": {"toolset": "all", "limit": 8}}),
            env={},
        )
        self.assertEqual(
            [
                "context_policy",
                "docs_index",
                "workflow_plan",
                "agent_profile_generate",
                "products_get",
                "products_compare",
                "categories_search",
                "finder_query",
            ],
            [item["name"] for item in tools["result"]["tools"]],
        )

        resources = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "resources-order", "method": "resources/list", "params": {"limit": 4}}),
            env={},
        )
        self.assertEqual(
            [
                "keepa://schema/products-agent-view",
                "keepa://schema/workflow-runtime-contract",
                "keepa://schema/risk-taxonomy",
                "keepa://fixtures/manifest",
            ],
            [item["uri"] for item in resources["result"]["resources"]],
        )

        prompts = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "prompts-order", "method": "prompts/list", "params": {"limit": 4}}),
            env={},
        )
        self.assertEqual(
            ["product_research", "category_research", "deal_compare", "project_onboarding"],
            [item["name"] for item in prompts["result"]["prompts"]],
        )

    def test_tools_list_supports_allow_and_exclude_filters(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "filtered",
                    "method": "tools/list",
                    "params": {
                        "allow_tools": ["context_policy", "resolve_research_target"],
                        "exclude_tools": ["context_policy"],
                    },
                }
            ),
            env={},
        )

        self.assertEqual(["resolve_research_target"], [item["name"] for item in response["result"]["tools"]])
        self.assertEqual(response["result"]["filters"]["allow_tools"], ["context_policy", "resolve_research_target"])
        self.assertEqual(response["result"]["filters"]["exclude_tools"], ["context_policy"])

    def test_workflow_runtime_args_only_exposed_on_resolver_tools(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "runtime-schema",
                    "method": "tools/list",
                    "params": {"toolset": "all", "allow_tools": ["products_compare", "context_policy"]},
                }
            ),
            env={},
        )
        tools = {item["name"]: item for item in response["result"]["tools"]}

        compare_props = tools["products_compare"]["inputSchema"]["properties"]
        policy_props = tools["context_policy"]["inputSchema"]["properties"]
        self.assertIn("resource_uri", compare_props)
        self.assertNotIn("resource_uri", policy_props)

        invalid = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "runtime-unsupported",
                    "method": "tools/call",
                    "params": {"name": "context_policy", "arguments": {"resource_uri": "keepa://research/example"}},
                }
            ),
            env={},
        )
        self.assertTrue(invalid["result"]["isError"])
        self.assertEqual(invalid["result"]["structuredContent"]["error"]["kind"], "invalid_arguments")
        self.assertIn("unsupported argument: resource_uri", invalid["result"]["structuredContent"]["error"]["details"]["errors"])

    def test_tools_list_marks_inactive_tools_for_profile(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "profile",
                    "method": "tools/list",
                    "params": {"toolset": "all", "profile": "offline_fixture_only", "limit": 100},
                }
            ),
            env={},
        )
        tools = {item["name"]: item for item in response["result"]["tools"]}

        self.assertEqual(response["result"]["profile"], "offline_fixture_only")
        self.assertIn("offline_fixture_only", response["result"]["available_profiles"])
        self.assertTrue(tools["context_policy"]["x-keepa"]["active"])
        self.assertTrue(tools["find_fast_movers"]["x-keepa"]["active"])
        self.assertTrue(tools["products_get"]["x-keepa"]["active"])
        self.assertTrue(tools["products_compare"]["x-keepa"]["active"])
        self.assertTrue(tools["categories_products"]["x-keepa"]["active"])

    def test_tools_list_rejects_unknown_profile(self):
        response = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "bad-profile", "method": "tools/list", "params": {"profile": "unknown"}}),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["message"], "Invalid profile")
        self.assertIn("offline_fixture_only", response["error"]["data"]["available_profiles"])

    def test_tools_call_offline_profile_allows_fixture_product_research(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "inactive",
                    "method": "tools/call",
                    "params": {
                        "name": "products_get",
                        "arguments": {"asin": "B0D8W1YVBX", "domain": "US", "fixture": "product_B0D8W1YVBX_agent_eval.json", "profile": "offline_fixture_only"},
                    },
                }
            ),
            env={},
        )

        result = response["result"]
        structured = result["structuredContent"]
        self.assertFalse(result["isError"])
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["command"], "products.get")

    def test_tools_call_offline_profile_requires_fixture_or_dry_run(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "profile-guard",
                    "method": "tools/call",
                    "params": {
                        "name": "products_get",
                        "arguments": {"asin": "B0D8W1YVBX", "domain": "US", "profile": "offline_fixture_only"},
                    },
                }
            ),
            env={},
        )

        result = response["result"]
        structured = result["structuredContent"]
        self.assertTrue(result["isError"])
        self.assertFalse(structured["ok"])
        self.assertEqual(structured["error"]["kind"], "profile_requires_fixture_or_dry_run")
        self.assertEqual(structured["error"]["details"]["live_profile"], "live_read_allowed")

    def test_safe_profiles_keep_live_research_tools_discoverable_but_guard_calls(self):
        live_research_tools = {
            "products_get": {"asin": "B0D8W1YVBX", "domain": "US"},
            "products_compare": {"asin": ["B0D8W1YVBX", "B0EVALCMP1"], "domain": "US"},
            "categories_products": {"category": "172282", "domain": "US"},
            "finder_query": {"selection": {}, "domain": "US"},
            "deals_query": {"selection": {}, "domain": "US"},
            "bestsellers_get": {"category": "172282", "domain": "US"},
            "topsellers_list": {"domain": "US"},
        }
        for profile in ("offline_fixture_only", "dry_run_default"):
            with self.subTest(profile=profile, phase="list"):
                response = handle_mcp_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": f"list-{profile}",
                            "method": "tools/list",
                            "params": {"toolset": "all", "profile": profile, "limit": 100},
                        }
                    ),
                    env={},
                )
                tools = {item["name"]: item for item in response["result"]["tools"]}
                for tool_name in live_research_tools:
                    self.assertTrue(tools[tool_name]["x-keepa"]["active"], tool_name)

            for tool_name, arguments in live_research_tools.items():
                with self.subTest(profile=profile, tool=tool_name, phase="call"):
                    response = handle_mcp_message(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": f"guard-{profile}-{tool_name}",
                                "method": "tools/call",
                                "params": {"name": tool_name, "arguments": {**arguments, "profile": profile}},
                            }
                        ),
                        env={},
                    )
                    structured = response["result"]["structuredContent"]
                    self.assertTrue(response["result"]["isError"])
                    self.assertEqual(structured["error"]["kind"], "profile_requires_fixture_or_dry_run")
                    self.assertEqual(structured["error"]["details"]["live_profile"], "live_read_allowed")

    def test_prompts_list_and_get_return_agent_playbooks(self):
        listed = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "prompts", "method": "prompts/list", "params": {}}), env={})
        names = {item["name"] for item in listed["result"]["prompts"]}

        self.assertIn("product_research", names)
        self.assertIn("project_onboarding", names)
        self.assertIn("research_agent_start", names)
        self.assertIn("inventory_audit", names)
        self.assertIn("velocity_research", names)
        self.assertIn("market_opportunity", names)

        prompt = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "prompt",
                    "method": "prompts/get",
                    "params": {"name": "product_research", "arguments": {"asin": "B0D8W1YVBX", "domain": "US", "goal": "deal"}},
                }
            ),
            env={},
        )
        message = prompt["result"]["messages"][0]
        self.assertEqual(message["role"], "user")
        self.assertIn("B0D8W1YVBX", message["content"]["text"])
        self.assertIn("workflow_plan", message["content"]["text"])

        research_start = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "research-start",
                    "method": "prompts/get",
                    "params": {"name": "research_agent_start", "arguments": {"query": "B001GZ6QEC", "domain": "US", "goal": "deal"}},
                }
            ),
            env={},
        )
        start_text = research_start["result"]["messages"][0]["content"]["text"]
        self.assertIn("keepa://context/policy", start_text)
        self.assertIn("resolve_research_target", start_text)

    def test_docs_tools_read_zread_resources_for_resource_limited_clients(self):
        index = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "docs-index", "method": "tools/call", "params": {"name": "docs_index", "arguments": {}}}),
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
                    "params": {"name": "docs_read", "arguments": {"page": "1-gai-lan.md"}},
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
            json.dumps({"jsonrpc": "2.0", "id": "policy", "method": "tools/call", "params": {"name": "context_policy", "arguments": {}}}),
            env={},
        )
        policy_payload = policy["result"]["structuredContent"]
        self.assertTrue(policy_payload["ok"])
        self.assertEqual(policy_payload["data"]["view"], "context_policy")
        self.assertTrue(policy_payload["data"]["live_keepa"]["allowed_by_default"])
        self.assertEqual(policy_payload["data"]["mode"], "live_read_allowed_for_real_research")

        resolved = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "resolve",
                    "method": "tools/call",
                    "params": {"name": "resolve_research_target", "arguments": {"query": "B001GZ6QEC", "domain": "US"}},
                }
            ),
            env={},
        )
        resolved_payload = resolved["result"]["structuredContent"]
        self.assertEqual(resolved_payload["data"]["primary"]["type"], "asin")
        self.assertEqual(resolved_payload["data"]["next_actions"][0]["tool"], "products_get")

        context = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "context",
                    "method": "tools/call",
                    "params": {"name": "query_research_context", "arguments": {"target_type": "asin", "target_id": "B001GZ6QEC"}},
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
                        "name": "categories_search",
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
                        "name": "categories_finder_selection",
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

    def test_tools_call_business_alias_returns_formula_metadata(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "business-alias",
                    "method": "tools/call",
                    "params": {
                        "name": "find_fast_movers",
                        "arguments": {"fixture": "product_agent_view_B0TEST.json", "profile": "offline_fixture_only"},
                    },
                }
            ),
            env={},
        )

        structured = response["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["data"]["view"], "business_metrics")
        metric = structured["data"]["products"][0]["metrics"]["velocity"]
        self.assertEqual(metric["method"], "monthly_sold_direct_v1")
        self.assertIn("confidence", metric)
        self.assertIn("evidence_path", metric)

    def test_tools_call_workflow_plan_returns_profile_policy(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "workflow-policy",
                    "method": "tools/call",
                    "params": {
                        "name": "workflow_plan",
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
        self.assertEqual(structured["data"]["steps"][2]["mcp"]["tool"], "categories_products")
        self.assertTrue(structured["data"]["steps"][3]["mcp"]["active_in_recommended_profile"])

    def test_tools_call_report_and_tracking_workflow_profiles(self):
        report = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "report-workflow",
                    "method": "tools/call",
                    "params": {"name": "workflow_plan", "arguments": {"name": "report-research", "domain": "US", "goal": "deal"}},
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
                        "name": "workflow_plan",
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
                        "name": "deals_query",
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
                        "name": "products_compare",
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
        self.assertIn("research_graph_summary", structured["data"])
        self.assertIn("mcp_resource_manifest", structured)
        self.assertEqual(structured["data"]["rows"][0]["total_offer_count"], 5)
        self.assertEqual(structured["data"]["rows"][0]["offer_count"], 5)
        self.assertIn("content_quality", structured["data"]["rows"][0]["selection_signals"])
        self.assertIn("content_quality", structured["data"]["rows"][0])
        self.assertIn("risk_summary", structured["data"]["rows"][0])
        self.assertIn("next_actions", structured["data"]["rows"][0])
        self.assertTrue(any(item.get("type") == "session_cache" for item in structured["mcp_resource_manifest"]["resources"]))

    def test_unknown_tool_returns_json_rpc_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "bad",
                    "method": "tools/call",
                    "params": {"name": "unknown", "arguments": {}},
                }
            ),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["data"]["tool"], "unknown")

    def test_tools_list_rejects_unknown_toolset(self):
        response = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "bad-toolset", "method": "tools/list", "params": {"toolset": "writes"}}),
            env={},
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(response["error"]["message"], "Invalid toolset")
        self.assertIn("research", response["error"]["data"]["available_toolsets"])

    def test_invalid_tool_arguments_return_structured_tool_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "invalid",
                    "method": "tools/call",
                    "params": {"name": "categories_search", "arguments": {"domain": "US", "extra": True}},
                }
            ),
            env={},
        )

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["kind"], "invalid_arguments")
        self.assertIn("missing required argument: term", result["structuredContent"]["error"]["details"]["errors"])
        self.assertIn("unsupported argument: extra", result["structuredContent"]["error"]["details"]["errors"])
        self.assertIn("Call tools/list", result["structuredContent"]["error"]["details"]["next_action"])

    def test_tools_list_input_schemas_are_registration_compatible(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "schema-compat",
                    "method": "tools/list",
                    "params": {"toolset": "all", "limit": 100},
                }
            ),
            env={},
        )
        forbidden = {"oneOf", "anyOf", "allOf", "enum", "not"}

        for tool in response["result"]["tools"]:
            with self.subTest(tool=tool["name"]):
                schema = tool["inputSchema"]
                self.assertEqual(schema.get("type"), "object")
                self.assertFalse(forbidden.intersection(schema), schema)

    def test_json_schema_tool_arguments_return_structured_errors(self):
        cases = [
            ("categories_search", {"domain": "US", "term": 123}, "term: expected string"),
            ("products_get", {"asin": "B001GZ6QEC", "view": "bad", "dry_run": True}, "view: value 'bad' is not one of"),
            ("products_get", {"asin": "B001GZ6QEC", "history_limit": -1, "dry_run": True}, "history_limit: value -1 is less than minimum 0"),
            ("products_compare", {"asin": ["B001GZ6QEC", 123], "dry_run": True}, "asin[1]: expected string"),
        ]

        for name, arguments, expected_error in cases:
            with self.subTest(name=name, expected_error=expected_error):
                response = handle_mcp_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": expected_error,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": arguments},
                        }
                    ),
                    env={},
                )

                result = response["result"]
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["error"]["kind"], "invalid_arguments")
                self.assertTrue(
                    any(expected_error in error for error in result["structuredContent"]["error"]["details"]["errors"]),
                    result["structuredContent"]["error"]["details"]["errors"],
                )

    def test_tools_call_missing_workflow_input_returns_structured_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "missing-workflow-input",
                    "method": "tools/call",
                    "params": {"name": "research_graph_merge", "arguments": {}},
                }
            ),
            env={},
        )

        result = response["result"]
        structured = result["structuredContent"]
        self.assertTrue(result["isError"])
        self.assertFalse(structured["ok"])
        self.assertEqual(structured["error"]["kind"], "missing_inputs")
        self.assertEqual(structured["error"]["details"]["missing_inputs"][0]["field"], "graph")

    def test_high_cost_tool_without_confirmation_returns_structured_error(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "categories_products",
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
        details = structured["error"]["details"]
        self.assertEqual(details["token_refill_guidance"]["status_command"], "tokens.status")
        self.assertEqual(details["token_refill_guidance"]["wait_strategy"], "check_tokens_status")
        self.assertIn("set_hydrate_top_zero", details["token_refill_guidance"]["hints"])
        self.assertEqual(structured["budget_ledger"]["blocked_actions"][0]["tool"], "categories_products")

    def test_iter_mcp_output_keeps_session_cache_across_lines(self):
        first = {
            "jsonrpc": "2.0",
            "id": "a",
            "method": "tools/call",
            "params": {
                "name": "categories_search",
                "arguments": {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
            },
        }
        second = {
            "jsonrpc": "2.0",
            "id": "b",
            "method": "tools/call",
            "params": {
                "name": "categories_search",
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
                "params": {"name": "audit_cost", "arguments": {"target_command": "products.get"}},
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
        self.assertIn("keepa://schema/risk-taxonomy", uris)
        self.assertIn("keepa://schema/workflow-runtime-contract", uris)
        self.assertIn("keepa://fixtures/manifest", uris)
        self.assertIn("keepa://guides/cassette-promotion", uris)
        self.assertIn("keepa://guides/categories", uris)
        self.assertIn("keepa://guides/marketplaces", uris)
        self.assertIn("keepa://guides/agent-profile", uris)
        self.assertIn("keepa://evidence/recent", uris)
        self.assertIn("keepa://tools/index", uris)
        self.assertIn("keepa://workflow/runtime-contract", uris)
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

        runtime = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "runtime-contract",
                    "method": "resources/read",
                    "params": {"uri": "keepa://workflow/runtime-contract"},
                }
            ),
            env={},
        )
        runtime_payload = json.loads(runtime["result"]["contents"][0]["text"])
        self.assertEqual(runtime_payload["schema_resource_uri"], "keepa://schema/workflow-runtime-contract")
        self.assertIn("resource_uri", runtime_payload["argument_names"])
        self.assertEqual(runtime_payload["failure_kind"], "missing_inputs")
        self.assertTrue(any(item["name"] == "products_compare" for item in runtime_payload["tools"]))
        report_tool = next(item for item in runtime_payload["tools"] if item["name"] == "reports_build")
        self.assertEqual(report_tool["future_task_support"]["cancel"]["method"], "tasks/cancel")
        self.assertEqual(report_tool["future_task_support"]["progress"]["notification"], "notifications/progress")
        self.assertEqual(report_tool["future_task_support"]["result"]["method"], "tasks/result")

        runtime_schema = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "runtime-contract-schema",
                    "method": "resources/read",
                    "params": {"uri": runtime_payload["schema_resource_uri"]},
                }
            ),
            env={},
        )
        schema_payload = json.loads(runtime_schema["result"]["contents"][0]["text"])
        self.assertEqual(schema_payload["$id"], "keepa://schema/workflow-runtime-contract")
        self.assertIn("accepted_sources", schema_payload["required"])

        risk_schema = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "risk-taxonomy-schema",
                    "method": "resources/read",
                    "params": {"uri": "keepa://schema/risk-taxonomy"},
                }
            ),
            env={},
        )
        risk_payload = json.loads(risk_schema["result"]["contents"][0]["text"])
        self.assertEqual(risk_payload["$id"], "keepa://schema/risk-taxonomy")
        self.assertIn("category_mismatch", risk_payload["$defs"]["risk_code"]["enum"])

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
        self.assertIn("keepa://research/{cache_key}/figures", uri_templates)
        self.assertIn("keepa://research/{cache_key}/figures/{figure_set}", uri_templates)
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
        self.assertEqual(payload["step_summary"][0]["mcp_tool"], "categories_search")
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
        self.assertEqual(tracking_payload["step_summary"][0]["mcp_tool"], "tracking_list")

    def test_tool_and_prompt_resources_support_schema_first_agent_discovery(self):
        toolset = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "toolset", "method": "resources/read", "params": {"uri": "keepa://toolsets/research"}}),
            env={},
        )
        toolset_payload = json.loads(toolset["result"]["contents"][0]["text"])
        self.assertEqual(toolset_payload["toolset"], "research")
        self.assertEqual(toolset_payload["workflow_runtime_contract_uri"], "keepa://workflow/runtime-contract")
        self.assertTrue(any(item["resource_uri"] == "keepa://tools/products_get" for item in toolset_payload["tools"]))

        tool = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "tool", "method": "resources/read", "params": {"uri": "keepa://tools/products_get"}}),
            env={},
        )
        tool_payload = json.loads(tool["result"]["contents"][0]["text"])
        self.assertEqual(tool_payload["tool"]["name"], "products_get")
        self.assertEqual(tool_payload["execution"]["service_command"], "products.get")
        self.assertTrue(tool_payload["execution"]["workflow_runtime"])
        self.assertEqual(tool_payload["execution"]["workflow_runtime_contract_uri"], "keepa://workflow/runtime-contract")
        self.assertIn("inputSchema", tool_payload["tool"])

        long_tool = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "long-tool", "method": "resources/read", "params": {"uri": "keepa://tools/figures_research"}}),
            env={},
        )
        long_payload = json.loads(long_tool["result"]["contents"][0]["text"])
        future = long_payload["execution"]["future_task_support"]
        self.assertEqual(future["cancel"]["method"], "tasks/cancel")
        self.assertEqual(future["progress"]["notification"], "notifications/progress")
        self.assertEqual(future["result"]["resource_uri_template"], "keepa://tasks/{task_id}/result")

        prompts = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "prompts-index", "method": "resources/read", "params": {"uri": "keepa://prompts/index"}}),
            env={},
        )
        prompts_payload = json.loads(prompts["result"]["contents"][0]["text"])
        self.assertGreaterEqual(prompts_payload["prompt_count"], 4)
        self.assertTrue(any(item["resource_uri"] == "keepa://prompts/project_onboarding" for item in prompts_payload["prompts"]))

        prompt = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "prompt-resource", "method": "resources/read", "params": {"uri": "keepa://prompts/project_onboarding"}}),
            env={},
        )
        prompt_payload = json.loads(prompt["result"]["contents"][0]["text"])
        self.assertEqual(prompt_payload["name"], "project_onboarding")
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
                        "name": "products_get",
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
                            "name": "products_get",
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
            self.assertEqual(result["content"][1]["type"], "resource_link")
            self.assertEqual(result["content"][1]["uri"], uri)
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
                        "name": "categories_search",
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
                        "name": "sellers_get",
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
                        "name": "research_graph_merge",
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

    def test_workflow_resource_uri_resolves_category_products_to_compare(self):
        session = AgentSession(env={})
        category_products = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "category-products",
                    "method": "tools/call",
                    "params": {
                        "name": "categories_products",
                        "arguments": {
                            "category": "1055398",
                            "domain": "US",
                            "fixture": "bestsellers_home.json",
                            "limit": 5,
                            "yes": True,
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]

        compared = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "compare-from-resource",
                    "method": "tools/call",
                    "params": {
                        "name": "products_compare",
                        "arguments": {
                            "resource_uri": f"keepa://research/{category_products['cache_key']}",
                            "domain": "US",
                            "fixture": "products_compare_agent_eval.json",
                            "full": True,
                            "view": "deal",
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]

        self.assertTrue(compared["ok"])
        self.assertEqual(compared["command"], "products.compare")
        self.assertEqual(compared["data"]["product_count"], 3)
        self.assertEqual(compared["data"]["workflow_resolution"]["derived_values"]["asins"][:2], ["B001GZ6QEC", "B000TEST001"])
        self.assertEqual(compared["data"]["workflow_resolution"]["resolved"][0]["cache_key"], category_products["cache_key"])

    def test_workflow_resource_uri_resolves_graph_for_report_tools(self):
        session = AgentSession(env={})
        product = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "product-for-report",
                    "method": "tools/call",
                    "params": {
                        "name": "products_get",
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

        merged = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "merge-resource",
                    "method": "tools/call",
                    "params": {
                        "name": "research_graph_merge",
                        "arguments": {
                            "resource_uri": f"keepa://research/{product['cache_key']}/graph",
                            "root": "agent-report",
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]
        self.assertTrue(merged["ok"])
        self.assertEqual(merged["data"]["input_graph_count"], 1)
        self.assertEqual(merged["data"]["workflow_resolution"]["graph_count"], 1)

        report = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "report-from-resource",
                    "method": "tools/call",
                    "params": {
                        "name": "reports_build",
                        "arguments": {
                            "resource_uri": f"keepa://research/{merged['cache_key']}",
                            "format": "json",
                            "title": "Agent Report",
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]

        self.assertTrue(report["ok"])
        self.assertEqual(report["command"], "reports.build")
        self.assertEqual(report["data"]["research_graph"]["entity_counts"]["research_graph"], 1)
        self.assertGreaterEqual(len(report["data"]["workflow_resolution"]["temp_paths"]), 1)

    def test_workflow_artifact_output_path_resolves_local_report_chain(self):
        session = AgentSession(env={})
        with tempfile.TemporaryDirectory() as temp_dir:
            graph_path = str(Path(temp_dir) / "merged-graph.json")
            brief_path = str(Path(temp_dir) / "brief.json")
            product = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "artifact-product",
                        "method": "tools/call",
                        "params": {
                            "name": "products_get",
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

            merged = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "artifact-merge",
                        "method": "tools/call",
                        "params": {
                            "name": "research_graph_merge",
                            "arguments": {
                                "resource_uri": f"keepa://research/{product['cache_key']}/graph",
                                "root": "artifact-report-chain",
                                "out": graph_path,
                            },
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]

            brief = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "artifact-brief",
                        "method": "tools/call",
                        "params": {
                            "name": "research_brief_export",
                            "arguments": {"artifact": merged, "title": "Artifact Brief", "out": brief_path},
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]

            report = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "artifact-report",
                        "method": "tools/call",
                        "params": {
                            "name": "reports_build",
                            "arguments": {"artifact": {"output": {"path": graph_path}}, "format": "json", "title": "Artifact Report"},
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]

        self.assertTrue(merged["ok"])
        self.assertTrue(brief["ok"])
        self.assertTrue(report["ok"])
        self.assertEqual(brief["data"]["workflow_resolution"]["resolved"][0]["kind"], "path")
        self.assertEqual(brief["data"]["workflow_resolution"]["resolved"][0]["path"], graph_path)
        self.assertEqual(report["data"]["workflow_resolution"]["resolved"][0]["kind"], "path")
        self.assertEqual(report["data"]["workflow_resolution"]["resolved"][0]["path"], graph_path)
        self.assertEqual(report["data"]["research_graph"]["entity_counts"]["research_graph"], 1)

    def test_workflow_context_nested_outputs_resolve_report_chain(self):
        session = AgentSession(env={})
        with tempfile.TemporaryDirectory() as temp_dir:
            graph_path = str(Path(temp_dir) / "nested-graph.json")
            product = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "nested-context-product",
                        "method": "tools/call",
                        "params": {
                            "name": "products_get",
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

            merged = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "nested-context-merge",
                        "method": "tools/call",
                        "params": {
                            "name": "research_graph_merge",
                            "arguments": {
                                "resource_uri": f"keepa://research/{product['cache_key']}/graph",
                                "root": "nested-context-chain",
                                "out": graph_path,
                            },
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]

            report = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "nested-context-report",
                        "method": "tools/call",
                        "params": {
                            "name": "reports_build",
                            "arguments": {
                                "workflow_context": {
                                    "steps": {"merge": {"artifact": merged}},
                                    "results": [{"artifact": {"data": {"output": {"path": graph_path}}}}],
                                },
                                "format": "json",
                                "title": "Nested Context Report",
                            },
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]

        self.assertTrue(report["ok"])
        self.assertEqual(report["data"]["workflow_resolution"]["resolved"][0]["kind"], "path")
        self.assertEqual(report["data"]["workflow_resolution"]["resolved"][0]["path"], graph_path)
        self.assertEqual(report["data"]["research_graph"]["entity_counts"]["research_graph"], 1)

    def test_graph_root_resource_is_audit_only_for_workflow_resolution(self):
        session = AgentSession(env={})
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "graph-root-audit-only",
                    "method": "tools/call",
                    "params": {
                        "name": "research_graph_merge",
                        "arguments": {"resource_uri": "keepa://graphs/product_compare_agent_eval", "root": "audit-only"},
                    },
                }
            ),
            env={},
            session=session,
        )

        structured = response["result"]["structuredContent"]
        self.assertFalse(structured["ok"])
        self.assertEqual(structured["error"]["kind"], "missing_inputs")
        resolution = structured["error"]["details"]["workflow_resolution"]
        self.assertEqual(resolution["resolved"][0]["kind"], "graph_audit_resource")
        self.assertEqual(resolution["missing_inputs"][0]["field"], "graph")

    def test_research_brief_export_tool_and_resources_use_session_cache(self):
        session = AgentSession(env={})
        category = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "brief-cat",
                    "method": "tools/call",
                    "params": {
                        "name": "categories_search",
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
                        "name": "sellers_get",
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
                        "name": "research_brief_export",
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

    def test_figures_research_tool_returns_svg_output_resource(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            response = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "figures",
                        "method": "tools/call",
                        "params": {
                            "name": "figures_research",
                            "arguments": {
                                "input": "tests/fixtures/agent_eval_products_compare_output.json",
                                "out_dir": temp_dir,
                                "title": "MCP SVG Figure Test",
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
            self.assertEqual(structured["command"], "figures.research")
            self.assertEqual(structured["data"]["format"], "svg")
            resources = text_payload["mcp_resource_manifest"]["resources"]
            svg_resource = next(item for item in resources if item["mimeType"] == "image/svg+xml")
            svg = handle_mcp_message(
                json.dumps({"jsonrpc": "2.0", "id": "figure-resource", "method": "resources/read", "params": {"uri": svg_resource["uri"]}}),
                env={},
            )
            content = svg["result"]["contents"][0]
            self.assertEqual(content["mimeType"], "image/svg+xml")
            self.assertIn("<svg", content["text"])

    def test_research_cache_figures_resource_generates_svg_manifest(self):
        session = AgentSession(env={})
        compared = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "compare",
                    "method": "tools/call",
                    "params": {
                        "name": "products_compare",
                        "arguments": {
                            "asin": ["B0D8W1YVBX", "B0F7XPYCSJ"],
                            "domain": "US",
                            "fixture": "products_multi_asin_full_history_sanitized.json",
                            "view": "deal",
                            "full": True,
                            "history_limit": 80,
                            "keep_history_points": True,
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]
        cache_key = compared["cache_key"]

        figures = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "research-figures",
                    "method": "resources/read",
                    "params": {"uri": f"keepa://research/{cache_key}/figures"},
                }
            ),
            env={},
            session=session,
        )
        payload = json.loads(figures["result"]["contents"][0]["text"])
        self.assertTrue(payload["found"])
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["figure_result"]["data_summary"]["small_multiple_count"], 2)
        self.assertGreaterEqual(payload["figure_result"]["data_summary"]["history_series_count"], 8)
        figure_names = {item["name"] for item in payload["figure_result"]["figures"]}
        self.assertIn("history-lines", figure_names)
        self.assertIn("window-change-heatmap", figure_names)
        svg_resource = next(item for item in payload["svg_resources"] if item.get("name") == "small-multiples")
        svg = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "research-svg", "method": "resources/read", "params": {"uri": svg_resource["uri"]}}),
            env={},
            session=session,
        )
        content = svg["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "image/svg+xml")
        self.assertIn("Multi-ASIN history small multiples", content["text"])
        self.assertIn("B0F7XPYCSJ", content["text"])
        self.assertIn("宋体", content["text"])

    def test_research_cache_figures_resource_supports_scoped_sets(self):
        session = AgentSession(env={})
        compared = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "compare",
                    "method": "tools/call",
                    "params": {
                        "name": "products_compare",
                        "arguments": {
                            "asin": ["B0D8W1YVBX", "B0F7XPYCSJ"],
                            "domain": "US",
                            "fixture": "products_multi_asin_full_history_sanitized.json",
                            "view": "deal",
                            "full": True,
                            "history_limit": 80,
                            "keep_history_points": True,
                        },
                    },
                }
            ),
            env={},
            session=session,
        )["result"]["structuredContent"]
        cache_key = compared["cache_key"]

        figures = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "research-figures-history",
                    "method": "resources/read",
                    "params": {"uri": f"keepa://research/{cache_key}/figures/history"},
                }
            ),
            env={},
            session=session,
        )

        payload = json.loads(figures["result"]["contents"][0]["text"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["figure_result"]["figure_set"], "history")
        self.assertEqual({item["name"] for item in payload["figure_result"]["figures"]}, {"history-lines", "window-change-heatmap"})
        self.assertEqual({item["name"] for item in payload["svg_resources"]}, {"history-lines", "window-change-heatmap"})

    def test_figures_research_tool_schema_exposes_figure_set(self):
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "tools",
                    "method": "tools/list",
                    "params": {"toolset": "reports", "allow_tools": ["figures_research", "reports_build"]},
                }
            ),
            env={},
        )

        tools = {item["name"]: item for item in response["result"]["tools"]}
        figures_schema = tools["figures_research"]["inputSchema"]["properties"]["figure_set"]
        reports_schema = tools["reports_build"]["inputSchema"]["properties"]["figure_set"]
        self.assertEqual(figures_schema["enum"], ["all", "history", "compare", "audit"])
        self.assertEqual(reports_schema["default"], "all")
        for name in ("figures_research", "reports_build"):
            meta = tools[name]["x-keepa"]
            self.assertTrue(meta["long_running_candidate"])
            self.assertEqual(meta["normal_tools_call_policy"], "fixture_or_small_output_only")
            self.assertEqual(meta["future_task_support"]["target"], "required")
            self.assertEqual(meta["future_task_support"]["cancel"]["method"], "tasks/cancel")
            self.assertEqual(meta["future_task_support"]["progress"]["notification"], "notifications/progress")
            self.assertEqual(meta["future_task_support"]["result"]["resource_uri_template"], "keepa://tasks/{task_id}/result")
            self.assertEqual(tools[name]["execution"]["taskSupport"], "forbidden")

    def test_report_markdown_svg_resource_links_are_readable(self):
        session = AgentSession(env={})
        with tempfile.TemporaryDirectory() as temp_dir:
            graph_path = str(Path(temp_dir) / "merged-graph.json")
            report_path = str(Path(temp_dir) / "report.md")
            merged = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "report-svg-merge",
                        "method": "tools/call",
                        "params": {
                            "name": "research_graph_merge",
                            "arguments": {
                                "input": "tests/fixtures/agent_eval_products_compare_output.json",
                                "root": "report-svg-links",
                                "out": graph_path,
                            },
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]
            self.assertTrue(merged["ok"])
            report = handle_mcp_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "report-svg-build",
                        "method": "tools/call",
                        "params": {
                            "name": "reports_build",
                            "arguments": {"input": graph_path, "format": "markdown", "out": report_path, "title": "SVG Report"},
                        },
                    }
                ),
                env={},
                session=session,
            )["result"]["structuredContent"]

            self.assertTrue(report["ok"])
            markdown = Path(report_path).read_text(encoding="utf-8")
            resource_uri = next(line.split("`")[1] for line in markdown.splitlines() if line.startswith("- MCP resource: `"))
            svg = handle_mcp_message(
                json.dumps({"jsonrpc": "2.0", "id": "report-svg-read", "method": "resources/read", "params": {"uri": resource_uri}}),
                env={},
                session=session,
            )
            content = svg["result"]["contents"][0]
            self.assertEqual(content["mimeType"], "image/svg+xml")
            self.assertIn("<svg", content["text"])

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
                        "name": "research_graph_merge",
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
