"""
scripts/check_agent_eval_fixtures.py
文件说明：检查固定 Agent evaluation fixtures 是否仍能产出稳定 JSON。
主要职责：离线运行 tests/agent_eval_fixtures 下的评测规格，供 release gate 复用。
依赖边界：只调用本地 service 与 tests/fixtures，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from keepa_cli.service import run_command


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise AssertionError(f"cannot resolve {path!r}; stopped at {part!r}")
    return current


def _assert_spec(payload: dict[str, Any], spec: dict[str, Any]) -> None:
    for assertion in spec["assertions"]:
        value = _resolve_path(payload, assertion["path"])
        if "equals" in assertion and value != assertion["equals"]:
            raise AssertionError(f"{assertion['path']} expected {assertion['equals']!r}, got {value!r}")
        if "min" in assertion and value < assertion["min"]:
            raise AssertionError(f"{assertion['path']} expected >= {assertion['min']!r}, got {value!r}")
        if "contains" in assertion and assertion["contains"] not in value:
            raise AssertionError(f"{assertion['path']} expected to contain {assertion['contains']!r}")
        if "length" in assertion and len(value) != assertion["length"]:
            raise AssertionError(f"{assertion['path']} expected length {assertion['length']!r}, got {len(value)!r}")


def check_agent_eval_fixtures(eval_dir: Path, fixture_dir: Path) -> list[str]:
    specs = sorted(eval_dir.glob("*.json"))
    if not specs:
        raise AssertionError(f"no agent eval fixture specs found in {eval_dir}")

    checked: list[str] = []
    for path in specs:
        spec = json.loads(path.read_text(encoding="utf-8"))
        payload = run_command(spec["command"], spec.get("params") or {}, fixture_dir=fixture_dir, env={})
        _assert_spec(payload, spec)
        checked.append(path.name)
    return checked


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
