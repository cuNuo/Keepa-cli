"""
tests/test_capabilities.py
文件说明：验证 Agent 能力发现协议。
主要职责：确保 CLI、service 与 stdio 都能暴露稳定 capabilities。
依赖边界：不访问真实 Keepa API。
"""

import json
import subprocess
import sys
import unittest

from keepa_cli.agent.stdio import handle_stdio_message
from keepa_cli.service import run_command


class CapabilitiesTests(unittest.TestCase):
    def test_service_capabilities_include_schema_version_and_graphimage(self):
        payload = run_command("capabilities", env={})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "capabilities")
        self.assertEqual(payload["data"]["schema_version"], "2026-05-11.7")
        self.assertIn("tui", payload["data"]["protocols"])
        self.assertIn("mcp", payload["data"]["protocols"])
        self.assertEqual(payload["data"]["mcp"]["server_name"], "keepa")
        self.assertEqual(payload["data"]["mcp"]["default_toolset"], "research")
        self.assertIn("docs", payload["data"]["mcp"]["toolsets"])
        self.assertIn("tracking-readonly", payload["data"]["mcp"]["toolsets"])
        self.assertIn("offline_fixture_only", payload["data"]["mcp"]["profiles"])
        self.assertGreaterEqual(len(payload["data"]["mcp"]["resource_templates"]), 4)
        self.assertGreaterEqual(len(payload["data"]["mcp"]["prompts"]), 4)
        resource_uris = {item["uri"] for item in payload["data"]["mcp"]["resources"]}
        self.assertIn("keepa://tools/index", resource_uris)
        self.assertIn("keepa://prompts/index", resource_uris)
        self.assertIn("keepa://context/policy", resource_uris)
        resource_templates = {item["uriTemplate"] for item in payload["data"]["mcp"]["resource_templates"]}
        self.assertIn("keepa://research/{cache_key}", resource_templates)
        self.assertIn("keepa://research/{cache_key}/brief", resource_templates)
        self.assertIn("keepa://research/{cache_key}/graph", resource_templates)
        self.assertIn("keepa://graphs/{root}", resource_templates)
        self.assertIn("keepa://toolsets/{toolset}", resource_templates)
        self.assertIn("keepa://tools/{name}", resource_templates)
        self.assertIn("keepa://prompts/{name}", resource_templates)
        mcp_tool_names = {item["name"] for item in payload["data"]["mcp"]["tools"]}
        self.assertIn("keepa.products_get", mcp_tool_names)
        self.assertIn("keepa.products_compare", mcp_tool_names)
        self.assertIn("keepa.categories_finder_selection", mcp_tool_names)
        self.assertIn("keepa.research_graph_merge", mcp_tool_names)
        self.assertIn("keepa.research_brief_export", mcp_tool_names)
        self.assertIn("keepa.docs_index", mcp_tool_names)
        self.assertIn("keepa.docs_read", mcp_tool_names)
        self.assertIn("keepa.context_policy", mcp_tool_names)
        self.assertIn("keepa.resolve_research_target", mcp_tool_names)
        self.assertIn("keepa.query_research_context", mcp_tool_names)
        self.assertIn("keepa.audit_cost", mcp_tool_names)
        self.assertIn("keepa.cassettes_promote", mcp_tool_names)
        self.assertIn("keepa.cassettes_promote_and_verify", mcp_tool_names)
        self.assertIn("keepa.reports_build", mcp_tool_names)
        self.assertIn("keepa.tracking_list", mcp_tool_names)
        command_names = {item["name"] for item in payload["data"]["commands"]}
        self.assertIn("products.compare", command_names)
        self.assertIn("docs.index", command_names)
        self.assertIn("docs.read", command_names)
        self.assertIn("context.policy", command_names)
        self.assertIn("research.target.resolve", command_names)
        self.assertIn("research.context.query", command_names)
        self.assertIn("categories.products", command_names)
        self.assertIn("categories.finder-selection", command_names)
        self.assertIn("workflow.plan", command_names)
        self.assertIn("research_graph.merge", command_names)
        self.assertIn("research_brief.export", command_names)
        self.assertIn("graphs.image", command_names)
        self.assertIn("schema.generate", command_names)
        self.assertIn("cassettes.sanitize", command_names)
        self.assertIn("cassettes.promote", command_names)
        self.assertIn("cassettes.promote_and_verify", command_names)
        self.assertIn("browse.snapshot", command_names)
        self.assertIn("reports.build", command_names)
        self.assertIn("cache.explain", command_names)
        self.assertIn("cache.stats", command_names)
        self.assertIn("cache.inspect", command_names)
        self.assertIn("cache.prune-expired", command_names)
        self.assertIn("cache.clear", command_names)
        self.assertIn("audit.cost", command_names)
        graph = next(item for item in payload["data"]["commands"] if item["name"] == "graphs.image")
        self.assertTrue(graph["supports_fixture"])
        self.assertTrue(graph["supports_live"])
        self.assertEqual(graph["output"], "binary-file")

    def test_cli_capabilities_returns_json_envelope(self):
        result = subprocess.run(
            [sys.executable, "-m", "keepa_cli", "--json", "capabilities"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["schema_version"], "2026-05-11.7")

    def test_stdio_capabilities_returns_response_event(self):
        raw = json.dumps({"id": "caps", "method": "capabilities", "params": {}})
        events = handle_stdio_message(raw, env={})

        response = next(event for event in events if event["event"] == "response")
        self.assertTrue(response["payload"]["ok"])
        self.assertEqual(response["payload"]["data"]["schema_version"], "2026-05-11.7")


if __name__ == "__main__":
    unittest.main()
