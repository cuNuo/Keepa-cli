"""
hooks/run_relevant_hooks.py
文件说明：项目级 Hook 转发入口。
主要职责：复用全局 run_relevant_hooks.py，提供仓库内稳定命令路径。
依赖边界：不实现 Hook 逻辑，不访问网络或真实 Keepa API。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    global_hook = Path("D:/.codex/hooks/run_relevant_hooks.py")
    if not global_hook.is_file():
        print(f"global hook runner not found: {global_hook}", file=sys.stderr)
        return 1
    sys.argv = [str(global_hook), *sys.argv[1:]]
    runpy.run_path(str(global_hook), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
