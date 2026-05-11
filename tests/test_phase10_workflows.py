"""
tests/test_phase10_workflows.py
文件说明：验证 v1.0 本地工作流命令。
主要职责：覆盖 browse、batch、templates、reports、cache explain 与 cost audit。
依赖边界：只使用临时目录和离线 fixture，不访问真实 Keepa API。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keepa_cli.service import run_command


class Phase10WorkflowTests(unittest.TestCase):
    def test_batch_report_browse_cache_and_cost_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asin_file = root / "asins.txt"
            asin_file.write_text("B001GZ6QEC\n# comment\nB09YNQCQKR\nB001GZ6QEC\n", encoding="utf-8")
            batch_path = root / "batch.json"
            report_path = root / "report.md"
            browse_dir = root / "browse"

            batch = run_command(
                "batch.asins",
                {"asin_file": str(asin_file), "domain": "US", "dry_run": True, "out": str(batch_path)},
                env={},
            )
            self.assertTrue(batch["ok"])
            self.assertEqual(batch["data"]["task_count"], 2)
            self.assertTrue(batch_path.is_file())

            report = run_command(
                "reports.build",
                {"input": str(batch_path), "format": "markdown", "out": str(report_path), "title": "Batch Audit"},
                env={},
            )
            self.assertTrue(report["ok"])
            self.assertTrue(report_path.read_text(encoding="utf-8").startswith("# Batch Audit"))

            browse = run_command(
                "browse.snapshot",
                {"input": str(batch_path), "out_dir": str(browse_dir), "title": "Local Browse"},
                env={},
            )
            self.assertTrue(browse["ok"])
            self.assertTrue((browse_dir / "index.html").is_file())

            cache = run_command("cache.explain", {"input": str(batch_path), "command": "products.get"}, env={})
            self.assertTrue(cache["ok"])
            self.assertEqual(cache["data"]["source"], "local")

            cache_path = root / "keepa-cache.sqlite"
            stats = run_command("cache.stats", {"cache_path": str(cache_path)}, env={})
            self.assertTrue(stats["ok"])
            self.assertTrue(stats["data"]["persistent_cache_enabled"])
            self.assertEqual(stats["data"]["backend"], "sqlite")

            clear = run_command("cache.clear", {"cache_path": str(cache_path), "dry_run": True}, env={})
            self.assertTrue(clear["ok"])
            self.assertTrue(clear["data"]["dry_run"])
            self.assertEqual(clear["data"]["entries_removed"], 0)

            cost = run_command("audit.cost", {"target_command": "products.get", "params": {"asin": ["B001GZ6QEC"]}}, env={})
            self.assertTrue(cost["ok"])
            self.assertEqual(cost["data"]["totals"]["estimated_tokens"], 1)

    def test_templates_list_and_show(self):
        listed = run_command("templates.list", env={})
        self.assertTrue(listed["ok"])
        names = {item["name"] for item in listed["data"]["templates"]}
        self.assertIn("finder-basic", names)

        shown = run_command("templates.show", {"name": "tracking-add"}, env={})
        self.assertTrue(shown["ok"])
        self.assertEqual(shown["data"]["kind"], "tracking.batch")

    def test_reports_build_consumes_merged_research_graph(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            merged_path = root / "merged-graph.json"
            report_path = root / "graph-report.md"
            json_report_path = root / "graph-report.json"

            merged = run_command(
                "research_graph.merge",
                {
                    "input": [
                        "tests/fixtures/agent_eval_category_search_output.json",
                        "tests/fixtures/agent_eval_products_compare_output.json",
                        "tests/fixtures/agent_eval_seller_output.json",
                    ],
                    "root": "agent_selection_research",
                    "out": str(merged_path),
                },
                env={},
            )
            self.assertTrue(merged["ok"])
            self.assertTrue(merged_path.is_file())

            markdown = run_command(
                "reports.build",
                {"input": str(merged_path), "format": "markdown", "out": str(report_path), "title": "Graph Audit"},
                env={},
            )
            self.assertTrue(markdown["ok"])
            self.assertEqual(markdown["data"]["research_graph"]["root"], "agent_selection_research")
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("## Figures", report_text)
            self.assertNotIn("![agent-research-summary]", report_text)
            self.assertIn("![history-lines]", report_text)
            self.assertIn("## Research Graph", report_text)
            self.assertIn("### Relationships", report_text)
            figures = markdown["data"]["figures"]["figures"]
            self.assertTrue(Path(figures[0]["path"]).is_file())
            self.assertTrue(Path(figures[0]["source_data_path"]).is_file())

            json_payload = run_command(
                "reports.build",
                {"input": str(merged_path), "format": "json", "out": str(json_report_path), "title": "Graph Audit"},
                env={},
            )
            self.assertTrue(json_payload["ok"])
            report_json = json.loads(json_report_path.read_text(encoding="utf-8"))
            self.assertIn("research_graph_report", report_json)
            self.assertIn("figures", report_json)
            self.assertGreaterEqual(report_json["research_graph_report"]["node_count"], 1)

    def test_browse_snapshot_uses_research_graph_product_nodes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            merged_path = root / "merged-graph.json"
            browse_dir = root / "browse"
            merged = run_command(
                "research_graph.merge",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_output.json",
                    "root": "browse_graph_products",
                    "out": str(merged_path),
                },
                env={},
            )
            self.assertTrue(merged["ok"])

            browse = run_command("browse.snapshot", {"input": str(merged_path), "out_dir": str(browse_dir), "title": "Graph Browse"}, env={})

            self.assertTrue(browse["ok"])
            self.assertGreaterEqual(browse["data"]["row_count"], 3)
            self.assertGreaterEqual(browse["data"]["research_graph"]["node_count"], 3)
            self.assertIn("B0D8W1YVBX", (browse_dir / "index.html").read_text(encoding="utf-8"))
            data = json.loads((browse_dir / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(data["rows"][0]["source"], "research_graph")

    def test_figures_research_generates_svg_and_source_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            figures = run_command(
                "figures.research",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_output.json",
                    "out_dir": temp_dir,
                    "title": "Agent Research Figure Test",
                },
                env={},
            )

            self.assertTrue(figures["ok"])
            figure = figures["data"]["figures"][0]
            svg_path = Path(figure["path"])
            source_path = Path(figure["source_data_path"])
            self.assertTrue(svg_path.is_file())
            self.assertTrue(source_path.is_file())
            svg_text = svg_path.read_text(encoding="utf-8")
            self.assertIn("<svg", svg_text)
            self.assertIn("Times New Roman", svg_text)
            self.assertIn("SimSun", svg_text)
            self.assertIn("宋体", svg_text)
            self.assertIn("A  Product comparison", svg_text)
            self.assertIn("B  Price / rank history", svg_text)
            self.assertIn("C  Window change heatmap", svg_text)
            self.assertIn("D  Multi-ASIN small multiples", svg_text)
            self.assertGreaterEqual(len(figures["data"]["figures"]), 6)
            split_names = {item["name"] for item in figures["data"]["figures"]}
            self.assertIn("history-lines", split_names)
            self.assertIn("window-change-heatmap", split_names)
            multiples_path = Path(next(item["path"] for item in figures["data"]["figures"] if item["name"] == "small-multiples"))
            multiples_svg = multiples_path.read_text(encoding="utf-8")
            self.assertIn("multi-ASIN small multiples", multiples_svg)
            self.assertIn(">1</text>", multiples_svg)
            self.assertIn(">0</text>", multiples_svg)
            source = json.loads(source_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(source["products"]), 3)
            self.assertIn("history_series", source)
            self.assertIn("window_heatmap", source)
            self.assertGreaterEqual(len(source["small_multiples"]), 3)

    def test_figures_research_uses_bounded_history_small_multiples(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            figures = run_command(
                "figures.research",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_history_output.json",
                    "out_dir": temp_dir,
                    "title": "Agent History Figure Test 中文",
                },
                env={},
            )

            self.assertTrue(figures["ok"])
            multiples_path = Path(next(item["path"] for item in figures["data"]["figures"] if item["name"] == "small-multiples"))
            multiples_svg = multiples_path.read_text(encoding="utf-8")
            self.assertIn("Times New Roman", multiples_svg)
            self.assertIn("SimSun", multiples_svg)
            self.assertIn("宋体", multiples_svg)
            self.assertIn("Multi-ASIN history small multiples", multiples_svg)
            self.assertIn("B0D8W1YVBX", multiples_svg)
            self.assertIn("B0EVALCMP2", multiples_svg)
            self.assertIn("New price", multiples_svg)
            source = json.loads(Path(figures["data"]["figures"][0]["source_data_path"]).read_text(encoding="utf-8"))
            self.assertEqual(source["small_multiples"][0]["data_basis"], "bounded_history_points")
            self.assertEqual(len(source["small_multiples"]), 3)
            self.assertIn("normalized_points", source["small_multiples"][0]["series"][0])

    def test_figures_research_uses_sanitized_real_full_history_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            figures = run_command(
                "figures.research",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_real_full_history_output.json",
                    "out_dir": temp_dir,
                    "title": "Real Full History 对比",
                },
                env={},
            )

            self.assertTrue(figures["ok"])
            self.assertEqual(figures["data"]["schema_version"], "2026-05-11.4")
            self.assertEqual(figures["data"]["data_summary"]["small_multiple_count"], 2)
            self.assertGreaterEqual(figures["data"]["data_summary"]["history_series_count"], 8)
            multiples_path = Path(next(item["path"] for item in figures["data"]["figures"] if item["name"] == "small-multiples"))
            history_path = Path(next(item["path"] for item in figures["data"]["figures"] if item["name"] == "history-lines"))
            multiples_svg = multiples_path.read_text(encoding="utf-8")
            history_svg = history_path.read_text(encoding="utf-8")
            self.assertIn("Real Full History 对比", multiples_svg)
            self.assertIn("B0D8W1YVBX", multiples_svg)
            self.assertIn("B0F7XPYCSJ", multiples_svg)
            self.assertIn("宋体", multiples_svg)
            self.assertIn("One row per metric", history_svg)
            self.assertIn("Sales rank is inverted", history_svg)
            source = json.loads(Path(figures["data"]["figures"][0]["source_data_path"]).read_text(encoding="utf-8"))
            self.assertEqual({row["asin"] for row in source["small_multiples"]}, {"B0D8W1YVBX", "B0F7XPYCSJ"})
            self.assertEqual(source["small_multiples"][0]["data_basis"], "bounded_history_points")

    def test_figures_research_supports_agent_scoped_figure_sets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history = run_command(
                "figures.research",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_real_full_history_output.json",
                    "out_dir": str(Path(temp_dir) / "history"),
                    "title": "History Only",
                    "figure_set": "history",
                },
                env={},
            )
            compare = run_command(
                "figures.research",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_real_full_history_output.json",
                    "out_dir": str(Path(temp_dir) / "compare"),
                    "title": "Compare Only",
                    "figure_set": "compare",
                },
                env={},
            )
            audit = run_command(
                "figures.research",
                {
                    "input": "tests/fixtures/agent_eval_products_compare_real_full_history_output.json",
                    "out_dir": str(Path(temp_dir) / "audit"),
                    "title": "Audit Only",
                    "figure_set": "audit",
                },
                env={},
            )

            self.assertTrue(history["ok"])
            self.assertTrue(compare["ok"])
            self.assertTrue(audit["ok"])
            self.assertEqual(history["data"]["figure_set"], "history")
            self.assertEqual({item["name"] for item in history["data"]["figures"]}, {"history-lines", "window-change-heatmap"})
            self.assertEqual({item["name"] for item in compare["data"]["figures"]}, {"product-metric-comparison", "small-multiples"})
            self.assertEqual({item["name"] for item in audit["data"]["figures"]}, {"risk-graph-summary"})
            self.assertIn("history", history["data"]["available_figure_sets"])
            self.assertFalse((Path(temp_dir) / "history" / "agent-research-summary.svg").exists())

    def test_workflow_plan_category_research_is_local_agent_graph(self):
        payload = run_command(
            "workflow.plan",
            {"name": "category-research", "term": "home kitchen", "domain": "US", "hydrate_top": 2},
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["view"], "workflow_plan")
        self.assertEqual(payload["data"]["steps"][0]["tool"], "categories.search")
        self.assertEqual(payload["data"]["steps"][0]["mcp_tool"], "keepa.categories_search")
        self.assertEqual(payload["data"]["steps"][0]["mcp"]["profile"], "dry_run_default")
        self.assertIn("search-categories", payload["data"]["steps"][1]["depends_on"])
        self.assertEqual(payload["data"]["totals"]["estimated_tokens"], 55)
        self.assertTrue(payload["data"]["totals"]["requires_confirmation"])
        self.assertEqual(payload["data"]["workflow_policy"]["recommended_toolset"], "research")
        self.assertEqual(payload["data"]["workflow_policy"]["recommended_profile"], "dry_run_default")
        self.assertEqual(payload["data"]["workflow_policy"]["inactive_tools"][0]["tool"], "keepa.products_compare")
        self.assertEqual(payload["data"]["workflow_policy"]["confirmation_policy"]["step_ids"], ["fetch-category-products"])
        self.assertEqual(payload["data"]["workflow_policy"]["budget_ledger_seed"]["planned_estimated"], 55)
        self.assertEqual(
            payload["data"]["workflow_policy"]["tool_discovery"]["params"]["allow_tools"],
            [step["mcp"]["tool"] for step in payload["data"]["steps"]],
        )
        self.assertEqual(payload["data"]["next_actions"][0]["tool"], "categories.search")

    def test_workflow_plan_product_research_cli(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "keepa_cli",
                "--json",
                "workflow",
                "plan",
                "product-research",
                "--asin",
                "B0D8W1YVBX",
                "--domain",
                "US",
                "--goal",
                "deal",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["steps"][0]["params"]["view"], "deal")
        self.assertEqual(payload["data"]["workflow_policy"]["recommended_profile"], "live_read_allowed")
        self.assertEqual(payload["data"]["workflow_policy"]["inactive_tools"], [])
        self.assertEqual(payload["data"]["steps"][1]["execution"]["confirmation_params"], {"yes": True})

    def test_workflow_plan_report_research_is_local_reports_profile(self):
        payload = run_command(
            "workflow.plan",
            {"name": "report-research", "domain": "US", "goal": "deal"},
            env={},
        )

        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["totals"]["estimated_tokens"], 0)
        self.assertFalse(data["totals"]["requires_confirmation"])
        self.assertEqual(data["workflow_policy"]["recommended_toolset"], "reports")
        self.assertEqual(data["workflow_policy"]["recommended_profile"], "offline_fixture_only")
        self.assertEqual(data["workflow_policy"]["inactive_tools"], [])
        self.assertIn("keepa.research_graph_merge", data["workflow_policy"]["workflow_tools"])
        self.assertIn("workflow_inputs", data)
        self.assertEqual(data["workflow_inputs"]["graph_inputs"]["required"], True)
        self.assertIn("merged_graph", data["artifacts"])
        self.assertIn("markdown_report", data["artifacts"])
        self.assertIn("keepa://workflow/{encoded_params}/policy", {item["uri_template"] for item in data["resource_templates"]})
        self.assertEqual(data["steps"][0]["input_refs"][0], "workflow_inputs.graph_inputs")
        self.assertIn("artifacts.merged_graph.path", data["steps"][1]["input_refs"])
        self.assertEqual(data["steps"][0]["mcp"]["toolset"], "reports")
        self.assertEqual(data["steps"][1]["tool"], "reports.build")
        self.assertEqual(data["steps"][2]["parallel_group"], "report-outputs")
        self.assertEqual(data["next_actions"][0]["tool"], "research_graph.merge")

    def test_workflow_plan_tracking_audit_is_readonly_profile(self):
        payload = run_command(
            "workflow.plan",
            {"name": "tracking-audit", "asin": "B0D8W1YVBX", "domain": "US"},
            env={},
        )

        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["workflow_policy"]["recommended_toolset"], "tracking-readonly")
        self.assertEqual(data["workflow_policy"]["recommended_profile"], "tracking_readonly")
        self.assertEqual(data["workflow_policy"]["inactive_tools"], [])
        self.assertEqual(data["workflow_policy"]["confirmation_policy"]["step_ids"], [])
        self.assertEqual(data["workflow_inputs"]["asin"]["value"], "B0D8W1YVBX")
        self.assertIn("tracking_list", data["artifacts"])
        self.assertIn("tracking_cost_estimate", data["artifacts"])
        self.assertEqual(data["steps"][0]["artifact_refs"], ["artifacts.tracking_list"])
        self.assertIn("workflow_inputs.asin", data["steps"][2]["input_refs"])
        self.assertEqual(data["steps"][0]["tool"], "tracking.list")
        self.assertEqual(data["steps"][0]["mcp"]["toolset"], "tracking-readonly")
        self.assertEqual(data["steps"][2]["params"]["asin"], "B0D8W1YVBX")
        self.assertEqual(data["next_actions"][0]["tool"], "tracking.list")
        self.assertNotIn("tracking.add", {step["tool"] for step in data["steps"]})

    def test_workflow_plan_business_aliases_are_offline_profile(self):
        for name, mcp_tool in (
            ("velocity-research", "keepa.find_fast_movers"),
            ("inventory-audit", "keepa.inventory_audit"),
            ("market-opportunity", "keepa.market_opportunity"),
        ):
            payload = run_command("workflow.plan", {"name": name, "domain": "US"}, env={})
            self.assertTrue(payload["ok"], name)
            data = payload["data"]
            self.assertEqual(data["workflow_policy"]["recommended_toolset"], "business")
            self.assertEqual(data["workflow_policy"]["recommended_profile"], "offline_fixture_only")
            self.assertEqual(data["workflow_policy"]["inactive_tools"], [])
            self.assertEqual(data["steps"][0]["mcp_tool"], mcp_tool)
            self.assertEqual(data["steps"][0]["estimated_tokens"], 0)
            self.assertIn("business_input", data["workflow_inputs"])
            self.assertIn("business_metrics", data["artifacts"])

    def test_cli_workflow_commands_return_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asin_file = Path(temp_dir) / "asins.txt"
            asin_file.write_text("B001GZ6QEC\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "keepa_cli",
                    "--json",
                    "batch",
                    "asins",
                    str(asin_file),
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "batch.asins")

            stats_result = subprocess.run(
                [sys.executable, "-m", "keepa_cli", "--json", "cache", "stats"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=True,
            )
            stats_payload = json.loads(stats_result.stdout)
            self.assertTrue(stats_payload["ok"])
            self.assertEqual(stats_payload["command"], "cache.stats")

            figure_dir = Path(temp_dir) / "figures"
            figures_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "keepa_cli",
                    "--json",
                    "figures",
                    "research",
                    "--input",
                    "tests/fixtures/agent_eval_products_compare_real_full_history_output.json",
                    "--out-dir",
                    str(figure_dir),
                    "--figure-set",
                    "history",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=True,
            )
            figures_payload = json.loads(figures_result.stdout)
            self.assertTrue(figures_payload["ok"])
            self.assertEqual(figures_payload["data"]["figure_set"], "history")
            self.assertEqual({item["name"] for item in figures_payload["data"]["figures"]}, {"history-lines", "window-change-heatmap"})


if __name__ == "__main__":
    unittest.main()
