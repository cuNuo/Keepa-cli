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
        self.assertEqual(payload["data"]["schema_version"], "2026-05-09.1")
        command_names = {item["name"] for item in payload["data"]["commands"]}
        self.assertIn("graphs.image", command_names)
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
        self.assertEqual(payload["data"]["schema_version"], "2026-05-09.1")

    def test_stdio_capabilities_returns_response_event(self):
        raw = json.dumps({"id": "caps", "method": "capabilities", "params": {}})
        events = handle_stdio_message(raw, env={})

        response = next(event for event in events if event["event"] == "response")
        self.assertTrue(response["payload"]["ok"])
        self.assertEqual(response["payload"]["data"]["schema_version"], "2026-05-09.1")


if __name__ == "__main__":
    unittest.main()
