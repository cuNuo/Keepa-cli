"""
scripts/release_gate.py
文件说明：本地发布前质量门禁。
主要职责：串联编译、单元测试、fixture 同步、入口 smoke 与 npm 打包 dry-run。
依赖边界：默认不安装依赖、不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True, env=env)


def _tool(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise FileNotFoundError(f"required tool not found on PATH: {name}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Keepa CLI 发布前门禁。")
    parser.add_argument("--skip-npm-install", action="store_true", help="兼容入口；当前项目无 npm 依赖安装步骤。")
    parser.add_argument("--skip-npm-pack", action="store_true", help="跳过 npm pack；用于 npm prepack 避免递归。")
    args = parser.parse_args()
    _ = args.skip_npm_install

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    node = _tool("node")
    npm = _tool("npm")
    with tempfile.TemporaryDirectory() as temp_dir:
        smoke_env = {**os.environ, "KEEPA_CLI_CONFIG": str(Path(temp_dir) / "config.toml")}
        smoke_env.pop("KEEPA_API_KEY", None)
        node_env = {**smoke_env, "KEEPA_CLI_PYTHON": python}
        _run([python, "-m", "compileall", "-q", "keepa_cli", "scripts"], root)
        _run([python, "-m", "unittest", "discover", "-s", "tests", "-v"], root)
        _run([python, "scripts/check_fixture_sync.py"], root)
        install_verify = [python, "scripts/install_verify.py"]
        if args.skip_npm_pack:
            install_verify.append("--skip-npm-pack")
        _run(install_verify, root, smoke_env)
        _run([python, "-m", "keepa_cli", "--json", "doctor"], root, env=smoke_env)
        _run([node, "bin/keepa-cli.js", "--json", "doctor"], root, env=node_env)
        _run([node, "bin/kc.js", "--json", "doctor"], root, env=node_env)
        if not args.skip_npm_pack:
            _run([npm, "pack", "--dry-run", "--json", "--ignore-scripts"], root, env=smoke_env)
    print("release gate ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
