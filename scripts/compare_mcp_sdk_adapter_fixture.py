"""
scripts/compare_mcp_sdk_adapter_fixture.py
文件说明：对比隔离 SDK adapter spike 与当前 --mcp 协议输出。
主要职责：用 MCP Inspector 风格 fixture 校验 adapter 边界等价，避免后续 SDK/HTTP spike 复制业务逻辑。
依赖边界：只执行本地 MCP session fixture，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent.mcp_sdk_adapter import compare_fixture_outputs  # noqa: E402


DEFAULT_FIXTURE = REPO_ROOT / "tests" / "agent_eval_fixtures" / "mcp_inspector_protocol_fixture.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare current MCP stdio output with the isolated SDK adapter spike.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="mcp_session fixture path.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args(argv)

    fixture_path = args.fixture if args.fixture.is_absolute() else REPO_ROOT / args.fixture
    spec = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = compare_fixture_outputs(spec, env={})
    result["fixture"] = str(fixture_path.relative_to(REPO_ROOT))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"mcp sdk adapter fixture equivalence ok: {result['fixture']} ({result['step_count']} steps)")
    else:
        print(f"mcp sdk adapter fixture equivalence failed: {result['first_difference']}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
