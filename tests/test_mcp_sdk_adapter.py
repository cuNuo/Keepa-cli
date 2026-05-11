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

from keepa_cli.agent.mcp_sdk_adapter import adapter_status, compare_fixture_outputs, create_fastmcp_readonly_spike


INSPECTOR_FIXTURE = Path("tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json")


class McpSdkAdapterSpikeTests(unittest.TestCase):
    def test_adapter_status_keeps_production_stdio_entrypoint(self):
        status = adapter_status()
        self.assertEqual(status["adapter"], "keepa_mcp_sdk_spike")
        self.assertEqual(status["server_info_name"], "keepa_mcp")
        self.assertEqual(status["production_entrypoint"], "python -m keepa_cli --mcp")
        self.assertFalse(status["production_entrypoint_replaced"])
        self.assertEqual(status["business_core"], "AgentSession -> run_command")
        self.assertIn("initialize", status["supported_fixture_methods"])
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

    def test_fastmcp_spike_is_optional(self):
        if adapter_status()["sdk_available"]:
            self.assertIsNotNone(create_fastmcp_readonly_spike(env={}))
        else:
            with self.assertRaisesRegex(RuntimeError, "官方 Python MCP SDK 未安装"):
                create_fastmcp_readonly_spike(env={})


if __name__ == "__main__":
    unittest.main()
