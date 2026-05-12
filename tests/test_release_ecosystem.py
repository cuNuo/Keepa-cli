"""
tests/test_release_ecosystem.py
文件说明：验证 v1.5 发布生态资产。
主要职责：覆盖安装验证脚本和 companion skill 是否存在关键安全指引。
依赖边界：安装验证跳过 npm pack，避免测试内递归触发发布打包。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReleaseEcosystemTests(unittest.TestCase):
    def test_install_verify_script_checks_python_and_node_wrappers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {**os.environ, "KEEPA_CLI_CONFIG": str(Path(temp_dir) / "config.toml")}
            env.pop("KEEPA_API_KEY", None)
            result = subprocess.run(
                [sys.executable, "scripts/install_verify.py", "--skip-npm-pack"],
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(len(payload["checks"]), 1)

    def test_companion_skill_documents_safe_order(self):
        content = Path(".codex/skills/keepa-cli/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("kc --json doctor", content)
        self.assertIn("--dry-run", content)
        self.assertIn("tracking", content.lower())
        self.assertIn("Do not run raw non-GET live requests", content)

    def test_npm_scripts_route_release_gate_through_node_wrapper(self):
        package = json.loads(Path("package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        self.assertIn("node scripts/release_gate.js", scripts["test"])
        self.assertIn("node scripts/release_gate.js", scripts["release:check"])
        self.assertIn("node scripts/release_gate.js", scripts["prepack"])

    def test_release_gate_routes_mcp_checks_through_quality_gate(self):
        release_gate = Path("scripts/release_gate.py").read_text(encoding="utf-8")
        quality_gate = Path("scripts/check_mcp_quality_gate.py").read_text(encoding="utf-8")
        self.assertIn("scripts/check_mcp_quality_gate.py", release_gate)
        self.assertIn("scripts/check_agent_eval_fixtures.py", quality_gate)
        self.assertIn("scripts/check_mcp_output_schema.py", quality_gate)
        self.assertIn("scripts/check_mcp_performance_gate.py", quality_gate)
        self.assertIn("--performance-out", quality_gate)
        self.assertTrue(Path("scripts/summarize_mcp_performance_history.py").exists())
        self.assertIn("mcp_sdk_adapter_filter_parity.json", quality_gate)
        self.assertIn("scripts/export_mcp_inspector_snapshot.py", quality_gate)

    def test_ci_uploads_mcp_performance_artifact(self):
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("--performance-out artifacts/mcp-performance/", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("mcp-performance-${{ runner.os }}-py311", workflow)


if __name__ == "__main__":
    unittest.main()
