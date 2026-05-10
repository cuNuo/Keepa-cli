"""
scripts/check_agent_eval_fixtures.py
文件说明：检查固定 Agent evaluation fixtures 是否仍能产出稳定 JSON。
主要职责：离线运行 tests/agent_eval_fixtures 下的评测规格，供 release gate 复用。
依赖边界：只调用本地 service 与 tests/fixtures，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from keepa_cli.agent.mcp import handle_mcp_message
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import get_tool_definition, tool_params_to_command_params, validate_tool_arguments
from keepa_cli.service import run_command


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if part == "$json":
            if not isinstance(current, str):
                raise AssertionError(f"cannot parse non-string JSON value at {path!r}")
            current = json.loads(current)
            continue
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
        if "length_min" in assertion and len(value) < assertion["length_min"]:
            raise AssertionError(f"{assertion['path']} expected length >= {assertion['length_min']!r}, got {len(value)!r}")
        if "contains_any" in assertion and not any(item in value for item in assertion["contains_any"]):
            raise AssertionError(f"{assertion['path']} expected to contain any of {assertion['contains_any']!r}")
        if "not_contains" in assertion and assertion["not_contains"] in value:
            raise AssertionError(f"{assertion['path']} expected not to contain {assertion['not_contains']!r}")
        if assertion.get("next_actions_executable"):
            _assert_next_actions_executable(value, assertion["path"])


def _assert_next_actions_executable(value: Any, path: str) -> None:
    if not isinstance(value, list):
        raise AssertionError(f"{path} expected next_actions list, got {type(value).__name__}")
    for index, action in enumerate(value):
        if not isinstance(action, dict):
            raise AssertionError(f"{path}.{index} expected action object")
        raw_tool = str(action.get("tool") or "")
        params = action.get("params") or {}
        if not isinstance(params, dict):
            raise AssertionError(f"{path}.{index}.params expected object")
        mcp_tool_name = raw_tool if raw_tool.startswith("keepa.") else f"keepa.{raw_tool.replace('.', '_').replace('-', '_')}"
        tool = get_tool_definition(mcp_tool_name)
        if tool is None:
            service_payload = run_command(raw_tool, params, env={})
            if service_payload.get("error", {}).get("kind") == "unsupported_command":
                raise AssertionError(f"{path}.{index}.tool is not executable: {raw_tool}")
            continue
        errors = validate_tool_arguments(tool, params)
        if errors:
            raise AssertionError(f"{path}.{index}.tool {raw_tool} has invalid params: {errors}")
        tool_params_to_command_params(tool, params)


def _payload_for_spec(spec: dict[str, Any], fixture_dir: Path) -> dict[str, Any]:
    kind = str(spec.get("kind") or "service")
    with tempfile.TemporaryDirectory() as temp_dir:
        prepared = _replace_tmp(copy_json(spec), Path(temp_dir))
        return _payload_for_prepared_spec(prepared, fixture_dir)


def _payload_for_prepared_spec(spec: dict[str, Any], fixture_dir: Path) -> dict[str, Any]:
    kind = str(spec.get("kind") or "service")
    if kind == "service":
        return run_command(spec["command"], spec.get("params") or {}, fixture_dir=fixture_dir, env={})
    if kind == "mcp":
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": spec.get("id") or spec.get("command") or "agent-eval",
                    "method": spec["method"],
                    "params": spec.get("params") or {},
                }
            ),
            env={},
        )
        assert response is not None
        return response
    if kind == "session":
        session = AgentSession(env={})
        payloads = []
        for step in spec.get("steps") or []:
            payloads.append(session.execute(step["command"], step.get("params") or {}, tool=step.get("tool")))
        return {"ok": True, "kind": "session", "payloads": payloads, "budget_ledger": session.ledger.to_dict()}
    raise AssertionError(f"unsupported agent eval spec kind: {kind}")


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _replace_tmp(value: Any, temp_dir: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{tmp}", str(temp_dir))
    if isinstance(value, list):
        return [_replace_tmp(item, temp_dir) for item in value]
    if isinstance(value, dict):
        return {key: _replace_tmp(item, temp_dir) for key, item in value.items()}
    return value


def check_agent_eval_fixtures(eval_dir: Path, fixture_dir: Path) -> list[str]:
    specs = sorted(eval_dir.glob("*.json"))
    if not specs:
        raise AssertionError(f"no agent eval fixture specs found in {eval_dir}")

    checked: list[str] = []
    for path in specs:
        spec = json.loads(path.read_text(encoding="utf-8"))
        payload = _payload_for_spec(spec, fixture_dir)
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
