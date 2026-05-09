"""
tests/test_cli.py
文件说明：验证模块入口的核心 CLI 行为。
主要职责：覆盖 --json doctor、domains、config 与 --stdio 的命令级输出。
依赖边界：通过子进程调用当前虚拟环境 Python，不访问真实 Keepa API。
"""

import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def run_module(self, *args, input_text=None):
        return subprocess.run(
            [sys.executable, "-m", "keepa_cli", *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_json_doctor_returns_machine_readable_output(self):
        result = self.run_module("--json", "doctor")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "doctor")

    def test_domains_list_returns_domain_data(self):
        result = self.run_module("--json", "domains", "list")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(any(item["code"] == "US" for item in payload["data"]["domains"]))

    def test_config_show_returns_default_config(self):
        result = self.run_module("--json", "config", "show")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "config.show")
        self.assertEqual(payload["data"]["config"]["default_domain"], "US")

    def test_products_get_fixture_returns_product_data(self):
        result = self.run_module(
            "--json",
            "products",
            "get",
            "B001GZ6QEC",
            "--domain",
            "US",
            "--history",
            "0",
            "--fixture",
            "product_B001GZ6QEC.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "products.get")
        self.assertEqual(payload["request"]["endpoint"], "/product")
        self.assertEqual(payload["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")

    def test_categories_search_fixture_returns_category_data(self):
        result = self.run_module(
            "--json",
            "categories",
            "search",
            "home kitchen",
            "--domain",
            "US",
            "--fixture",
            "category_search_home.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["params_redacted"]["type"], "category")
        self.assertIn("1055398", payload["data"]["body"]["categories"])

    def test_history_export_fixture_returns_rows(self):
        result = self.run_module(
            "--json",
            "history",
            "export",
            "B001GZ6QEC",
            "--domain",
            "US",
            "--series",
            "amazon,new",
            "--format",
            "json",
            "--fixture",
            "product_history_B001GZ6QEC.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "history.export")
        self.assertEqual(payload["data"]["row_count"], 6)
        self.assertEqual(payload["data"]["rows"][0]["series"], "amazon")

    def test_history_trend_fixture_returns_analysis(self):
        result = self.run_module(
            "--json",
            "history",
            "trend",
            "B001GZ6QEC",
            "--domain",
            "US",
            "--series",
            "amazon",
            "--window-days",
            "30",
            "--fixture",
            "product_history_B001GZ6QEC.json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["analysis"]["series"]["amazon"]["all_time"]["points"], 3)

    def test_stdio_reads_json_lines(self):
        result = self.run_module("--stdio", input_text='{"id":"1","method":"doctor","params":{}}\n')

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(lines[0]["event"], "started")
        self.assertEqual(lines[-1]["event"], "done")


if __name__ == "__main__":
    unittest.main()
