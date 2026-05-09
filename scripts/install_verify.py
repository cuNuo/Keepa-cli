"""
scripts/install_verify.py
文件说明：跨平台安装验证脚本。
主要职责：验证 Python 模块入口、console script 元数据、Node wrapper 与 npm 发布元数据。
依赖边界：默认不安装依赖、不访问 Keepa API、不读取真实用户配置。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], cwd: Path, env: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=True)
    stdout = completed.stdout.strip()
    payload = json.loads(stdout) if stdout.startswith("{") else stdout
    return {"command": command, "ok": True, "payload": payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 Keepa CLI 跨平台安装入口。")
    parser.add_argument("--skip-node", action="store_true", help="跳过 Node wrapper 检查。")
    parser.add_argument("--skip-npm-pack", action="store_true", help="跳过 npm pack dry-run。")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    checks: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        env = {**os.environ, "KEEPA_CLI_CONFIG": str(Path(temp_dir) / "config.toml")}
        env.pop("KEEPA_API_KEY", None)
        checks.append(run([sys.executable, "-m", "keepa_cli", "--json", "doctor"], root, env))

        node = shutil.which("node")
        npm = shutil.which("npm")
        if not args.skip_node:
            if not node:
                raise FileNotFoundError("node is required unless --skip-node is set")
            node_env = {**env, "KEEPA_CLI_PYTHON": sys.executable}
            checks.append(run([node, "bin/keepa-cli.js", "--json", "doctor"], root, node_env))
            checks.append(run([node, "bin/kc.js", "--json", "doctor"], root, node_env))
        if not args.skip_npm_pack:
            if not npm:
                raise FileNotFoundError("npm is required unless --skip-npm-pack is set")
            checks.append(run([npm, "pack", "--dry-run", "--json", "--ignore-scripts"], root, env))

    result = {
        "ok": True,
        "python": sys.executable,
        "platform": sys.platform,
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
