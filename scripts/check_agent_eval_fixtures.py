"""
scripts/check_agent_eval_fixtures.py
文件说明：检查固定 Agent evaluation fixtures 是否仍能产出稳定 JSON。
主要职责：作为 release gate 兼容入口，委托包内 agent_eval 逻辑执行离线评测。
依赖边界：只调用本地 service 与 tests/fixtures，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent_eval import check_agent_eval_fixtures


def main() -> int:
    parser = argparse.ArgumentParser(description="检查固定 Agent evaluation fixtures。")
    parser.add_argument("--eval-dir", default="tests/agent_eval_fixtures")
    parser.add_argument("--fixture-dir", default="tests/fixtures")
    args = parser.parse_args()

    checked = check_agent_eval_fixtures(Path(args.eval_dir), Path(args.fixture_dir))
    print(f"agent eval fixtures ok: {len(checked)} specs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
