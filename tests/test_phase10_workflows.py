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

    def test_workflow_plan_category_research_is_local_agent_graph(self):
        payload = run_command(
            "workflow.plan",
            {"name": "category-research", "term": "home kitchen", "domain": "US", "hydrate_top": 2},
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["view"], "workflow_plan")
        self.assertEqual(payload["data"]["steps"][0]["tool"], "categories.search")
        self.assertIn("search-categories", payload["data"]["steps"][1]["depends_on"])
        self.assertEqual(payload["data"]["totals"]["estimated_tokens"], 55)
        self.assertTrue(payload["data"]["totals"]["requires_confirmation"])
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


if __name__ == "__main__":
    unittest.main()
