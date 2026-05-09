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

    def test_stdio_reads_json_lines(self):
        result = self.run_module("--stdio", input_text='{"id":"1","method":"doctor","params":{}}\n')

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(lines[0]["event"], "started")
        self.assertEqual(lines[-1]["event"], "done")


if __name__ == "__main__":
    unittest.main()
