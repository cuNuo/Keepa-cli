"""
tests/test_mcp_client_example.py
文件说明：验证可复制 MCP client 示例能完整跑通离线 Agent 工作流。
主要职责：覆盖 workflow.plan、resource_uri 解析、风险 schema 校验、图谱、brief 与 report。
依赖边界：通过本地 fixture 子进程执行示例，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class McpClientExampleTests(unittest.TestCase):
    def run_example(self, script: str) -> dict:
        return self.run_example_with_args(script, [])

    def run_example_with_args(self, script: str, extra_args: list[str]) -> dict:
        result = subprocess.run(
            [sys.executable, script, "--json", *extra_args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        return payload

    def test_mcp_agent_workflow_example_runs_full_offline_chain(self) -> None:
        payload = self.run_example("scripts/mcp_agent_workflow_example.py")

        tools = set(payload["mcp"]["tools"])
        self.assertIn("workflow_plan", tools)
        self.assertIn("reports_build", tools)
        self.assertEqual(payload["risk_schema"]["uri"], "keepa://schema/risk-taxonomy")
        self.assertIn("data_missing", payload["risk_schema"]["known_codes"])

        steps = payload["steps"]
        self.assertEqual(steps["workflow_plan"]["recommended_profile"], "dry_run_default")
        self.assertGreaterEqual(steps["workflow_plan"]["estimated_tokens"], 50)
        self.assertTrue(steps["category_products"]["resource_uri"].startswith("keepa://research/categories.products:"))
        self.assertTrue(steps["products_compare"]["graph_resource_uri"].endswith("/graph"))
        self.assertGreaterEqual(steps["products_compare"]["product_count"], 3)
        self.assertIn("B001GZ6QEC", steps["products_compare"]["resolved_asins"])

        self.assertTrue(payload["risk_validation"]["ok"])
        self.assertGreaterEqual(payload["risk_validation"]["checked_objects"], 1)
        self.assertIn("data_missing", payload["risk_validation"]["present_codes"])

        entity_counts = steps["graph_merge"]["entity_counts"]
        self.assertGreaterEqual(entity_counts["product"], 3)
        self.assertGreaterEqual(entity_counts["category"], 1)
        self.assertTrue(steps["brief"]["resource_uri"].endswith("/brief"))
        self.assertIn("research graphs", steps["brief"]["one_line"])
        self.assertEqual(steps["report"]["format"], "json")
        self.assertGreaterEqual(steps["report"]["research_graph_counts"]["product"], 3)

        ledger = payload["budget_ledger"]
        self.assertGreaterEqual(ledger["session_estimated"], 50)
        self.assertGreaterEqual(ledger["session_consumed"], 50)

    def test_tracking_audit_example_keeps_mcp_read_only(self) -> None:
        payload = self.run_example("scripts/mcp_tracking_audit_example.py")

        self.assertEqual(payload["mcp"]["toolset"], "tracking-readonly")
        self.assertEqual(payload["mcp"]["profile"], "tracking_readonly")
        self.assertEqual(payload["mcp"]["write_tools_exposed"], [])
        self.assertIn("tracking_list", payload["mcp"]["tools"])
        self.assertIn("audit_cost", payload["mcp"]["tools"])

        plan = payload["workflow_plan"]
        self.assertEqual(plan["recommended_toolset"], "tracking-readonly")
        self.assertEqual(plan["recommended_profile"], "tracking_readonly")
        self.assertEqual(plan["confirmation_steps"], [])

        steps = payload["steps"]
        self.assertIn("B09YNQCQKR", steps["tracking_list"]["asins"])
        self.assertEqual(steps["tracking_get"]["derived_asin"], "B09YNQCQKR")
        self.assertTrue(steps["tracking_get"]["dry_run"])
        self.assertTrue(steps["notifications"]["dry_run"])
        self.assertEqual(steps["cost"]["target_command"], "tracking.get")
        self.assertEqual(steps["cost"]["derived_asin"], "B09YNQCQKR")
        self.assertTrue(steps["write_boundary"]["blocked"])
        self.assertIn("Unknown tool", steps["write_boundary"]["error"])

    def test_report_research_example_builds_local_graph_brief_browse_report(self) -> None:
        payload = self.run_example("scripts/mcp_report_research_example.py")

        self.assertEqual(payload["mcp"]["toolset"], "reports")
        self.assertEqual(payload["mcp"]["profile"], "offline_fixture_only")
        self.assertIn("reports_build", payload["mcp"]["tools"])
        self.assertIn("browse_snapshot", payload["mcp"]["tools"])

        plan = payload["workflow_plan"]
        self.assertEqual(plan["recommended_toolset"], "reports")
        self.assertEqual(plan["recommended_profile"], "offline_fixture_only")
        self.assertEqual(plan["estimated_tokens"], 0)

        steps = payload["steps"]
        self.assertTrue(steps["graph_merge"]["resource_uri"].startswith("keepa://research/research_graph.merge:"))
        self.assertGreaterEqual(steps["graph_merge"]["entity_counts"]["product"], 3)
        self.assertTrue(steps["graph_merge"]["output_exists_during_run"])
        self.assertIn("research graphs", steps["brief"]["one_line"])
        self.assertTrue(steps["browse"]["index_exists_during_run"])
        self.assertGreaterEqual(steps["browse"]["row_count"], 3)
        self.assertEqual(steps["figures"]["svg_mime_type"], "image/svg+xml")
        self.assertGreaterEqual(steps["figures"]["data_summary"]["product_count"], 3)
        self.assertEqual(steps["report"]["format"], "json")
        self.assertGreaterEqual(steps["report"]["research_graph_counts"]["product"], 3)
        self.assertEqual(payload["budget_ledger"]["session_estimated"], 0)

    def test_examples_can_save_summary_to_controlled_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "mcp-summary.json"
            payload = self.run_example_with_args("scripts/mcp_report_research_example.py", ["--save-summary", str(summary_path)])

            self.assertTrue(summary_path.is_file())
            saved = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["ok"], True)
            self.assertEqual(saved["steps"]["report"]["format"], payload["steps"]["report"]["format"])

    def test_real_stdio_finder_query_schema_is_registration_compatible(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "keepa_cli", "--mcp"],
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        def request(method: str, params: dict) -> dict:
            assert process.stdin is not None
            assert process.stdout is not None
            request.next_id += 1
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request.next_id, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            raw = process.stdout.readline()
            if not raw:
                self.fail(process.stderr.read() if process.stderr else "MCP subprocess closed before response")
            response = json.loads(raw)
            self.assertNotIn("error", response)
            return response["result"]

        request.next_id = 0

        try:
            tools = request("tools/list", {"toolset": "all", "limit": 100})["tools"]
            finder = next(tool for tool in tools if tool["name"] == "finder_query")
            schema = finder["inputSchema"]
            forbidden_root_keywords = {"oneOf", "anyOf", "allOf", "enum", "not"}
            self.assertEqual(schema.get("type"), "object")
            self.assertFalse(forbidden_root_keywords.intersection(schema), schema)

            result = request(
                "tools/call",
                {
                    "name": "finder_query",
                    "arguments": {
                        "selection_file": "keepa_cli/fixtures/finder_selection.json",
                        "domain": "US",
                        "dry_run": True,
                    },
                },
            )
            self.assertFalse(result["isError"])
            self.assertTrue(result["structuredContent"]["ok"])
        finally:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
