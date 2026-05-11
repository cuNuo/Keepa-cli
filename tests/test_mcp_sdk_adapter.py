"""
tests/test_mcp_sdk_adapter.py
文件说明：验证隔离 SDK adapter spike 不替换生产 MCP stdio 入口。
主要职责：用 Inspector 风格 fixture 对比 adapter 与当前 --mcp 输出等价性。
依赖边界：只使用本地 fixture 和 AgentSession，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from keepa_cli.agent.mcp_sdk_adapter import (
    SDK_AGENT_START_TOOLS,
    SDK_DEFAULT_PROMPT_PAGE_SIZE,
    SDK_DEFAULT_RESOURCE_PAGE_SIZE,
    SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE,
    SDK_DEFAULT_TOOL_PAGE_SIZE,
    adapter_status,
    compare_fixture_outputs,
    create_fastmcp_readonly_spike,
)


INSPECTOR_FIXTURE = Path("tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json")


class McpSdkAdapterSpikeTests(unittest.TestCase):
    def test_adapter_status_keeps_production_stdio_entrypoint(self):
        status = adapter_status()
        self.assertEqual(status["adapter"], "keepa_mcp_sdk_adapter")
        self.assertEqual(status["server_info_name"], "keepa_mcp")
        self.assertEqual(status["production_entrypoint"], "python -m keepa_cli --mcp")
        self.assertFalse(status["production_entrypoint_replaced"])
        self.assertEqual(status["business_core"], "AgentSession -> run_command")
        self.assertIn("initialize", status["supported_fixture_methods"])
        self.assertEqual(status["sdk_default_tool_page_size"], SDK_DEFAULT_TOOL_PAGE_SIZE)
        self.assertEqual(status["sdk_default_resource_page_size"], SDK_DEFAULT_RESOURCE_PAGE_SIZE)
        self.assertEqual(status["sdk_default_resource_template_page_size"], SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE)
        self.assertEqual(status["sdk_default_prompt_page_size"], SDK_DEFAULT_PROMPT_PAGE_SIZE)
        self.assertEqual(status["sdk_agent_start_tools"][0], SDK_AGENT_START_TOOLS[0])
        self.assertEqual(status["sdk_agent_start_resources"][0], "keepa://context/policy")
        self.assertEqual(status["sdk_agent_start_resource_templates"][0], "keepa://toolsets/{toolset}")
        self.assertEqual(status["sdk_agent_start_prompts"][0], "keepa.product_research")
        self.assertIn("streamable HTTP", status["streamable_http_rule"])

    def test_inspector_fixture_matches_current_mcp_output(self):
        spec = json.loads(INSPECTOR_FIXTURE.read_text(encoding="utf-8"))
        result = compare_fixture_outputs(spec, env={})
        self.assertTrue(result["ok"], result["first_difference"])
        self.assertEqual(result["fixture_id"], "mcp_inspector_protocol_fixture")
        self.assertEqual(result["step_count"], 7)
        self.assertEqual(result["response_count"], 7)

    def test_compare_script_reports_equivalence(self):
        completed = subprocess.run(
            [sys.executable, "scripts/compare_mcp_sdk_adapter_fixture.py"],
            check=True,
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
        )
        self.assertIn("mcp sdk adapter fixture equivalence ok", completed.stdout)

    @unittest.skipUnless(adapter_status()["sdk_available"], "official mcp package is optional")
    def test_official_sdk_client_smoke(self):
        completed = subprocess.run(
            [sys.executable, "scripts/smoke_mcp_sdk_adapter_client.py", "--json"],
            check=True,
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["server_info"]["name"], "keepa_mcp")
        self.assertTrue(payload["tools"]["has_context_policy"])
        self.assertGreater(payload["tools"]["page_count"], 1)
        self.assertLessEqual(len(payload["tools"]["first_page_names"]), SDK_DEFAULT_TOOL_PAGE_SIZE)
        self.assertEqual(payload["tools"]["first_page_names"][0], "keepa.context_policy")
        self.assertGreater(payload["resources"]["page_count"], 1)
        self.assertLessEqual(len(payload["resources"]["first_page_names"]), SDK_DEFAULT_RESOURCE_PAGE_SIZE)
        self.assertEqual(payload["resources"]["first_page_names"][0], "keepa://context/policy")
        self.assertTrue(payload["resources"]["context_policy_bytes"] > 100)
        self.assertGreater(payload["resource_templates"]["page_count"], 1)
        self.assertLessEqual(len(payload["resource_templates"]["first_page_names"]), SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE)
        self.assertEqual(payload["resource_templates"]["first_page_names"][0], "keepa://toolsets/{toolset}")
        self.assertGreater(payload["prompts"]["page_count"], 1)
        self.assertLessEqual(len(payload["prompts"]["first_page_names"]), SDK_DEFAULT_PROMPT_PAGE_SIZE)
        self.assertEqual(payload["prompts"]["first_page_names"][0], "keepa.product_research")
        self.assertTrue(payload["prompts"]["has_product_research"])

    @unittest.skipUnless(adapter_status()["sdk_available"], "official mcp package is optional")
    def test_official_sdk_typed_fixture_mapping(self):
        completed = subprocess.run(
            [sys.executable, "scripts/check_mcp_sdk_adapter_typed_fixture.py", "--json"],
            check=True,
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        tools = next(response for response in payload["responses"] if response["method"] == "tools/list")["result"]
        self.assertGreaterEqual(tools["total_count"], 30)
        self.assertIn("toolset", tools["unsupported_fixture_params"])
        self.assertEqual(tools["first_page_names"][0], "keepa.context_policy")
        resources = next(response for response in payload["responses"] if response["method"] == "resources/list")["result"]
        self.assertEqual(resources["first_page_names"][0], "keepa://context/policy")
        self.assertGreater(resources["page_count"], 1)
        templates = next(response for response in payload["responses"] if response["method"] == "resources/templates/list")["result"]
        self.assertEqual(templates["first_page_names"][0], "keepa://toolsets/{toolset}")
        self.assertGreater(templates["page_count"], 1)
        prompts = next(response for response in payload["responses"] if response["method"] == "prompts/list")["result"]
        self.assertEqual(prompts["first_page_names"][0], "keepa.product_research")
        self.assertGreater(prompts["page_count"], 1)

    @unittest.skipUnless(adapter_status()["sdk_available"], "official mcp package is optional")
    def test_official_sdk_inspector_snapshot(self):
        completed = subprocess.run(
            [sys.executable, "scripts/export_mcp_inspector_snapshot.py", "--check", "--json"],
            check=True,
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["server_info"]["name"], "keepa_mcp")
        self.assertEqual(payload["lists"]["resources"]["first_page_names"][0], "keepa://context/policy")
        self.assertEqual(payload["lists"]["resource_templates"]["first_page_names"][0], "keepa://toolsets/{toolset}")
        self.assertTrue(payload["tool_error_probe"]["contains_invalid_arguments"])

    @unittest.skipUnless(adapter_status()["sdk_available"], "official mcp package is optional")
    def test_mcp_quality_gate_script(self):
        completed = subprocess.run(
            [sys.executable, "scripts/check_mcp_quality_gate.py", "--require-sdk", "--json"],
            check=True,
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        labels = [step["label"] for step in payload["steps"]]
        self.assertIn("sdk inspector snapshot", labels)

    def test_fastmcp_spike_is_optional(self):
        if adapter_status()["sdk_available"]:
            self.assertIsNotNone(create_fastmcp_readonly_spike(env={}))
        else:
            with self.assertRaisesRegex(RuntimeError, "官方 Python MCP SDK 未安装"):
                create_fastmcp_readonly_spike(env={})


if __name__ == "__main__":
    unittest.main()
