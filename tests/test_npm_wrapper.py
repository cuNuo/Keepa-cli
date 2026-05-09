"""
tests/test_npm_wrapper.py
文件说明：验证 npm bin wrapper 能转发到 Python CLI。
主要职责：确保未来 npm 全局安装后 keepa-cli 与 kc 入口仍保持 Agent 契约。
依赖边界：仅调用本仓库 Node wrapper，不安装 npm 依赖，不访问真实 Keepa API。
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


class NpmWrapperTests(unittest.TestCase):
    def test_node_wrapper_runs_json_doctor(self):
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        env = dict(os.environ)
        env["KEEPA_CLI_PYTHON"] = sys.executable

        with TemporaryDirectory() as temp_dir:
            env.pop("KEEPA_API_KEY", None)
            env["KEEPA_CLI_CONFIG"] = str(Path(temp_dir) / "config.toml")

            for wrapper in ("keepa-cli.js", "kc.js"):
                with self.subTest(wrapper=wrapper):
                    result = subprocess.run(
                        ["node", str(ROOT / "bin" / wrapper), "--json", "doctor"],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        check=False,
                        env=env,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertTrue(payload["ok"])
                    self.assertEqual(payload["command"], "doctor")


if __name__ == "__main__":
    unittest.main()
