"""
scripts/check_mcp_quality_gate.py
文件说明：MCP 协议质量门禁聚合入口。
主要职责：串联生产/SDK adapter fixture 等价、Agent fixture、SDK typed smoke、typed Inspector 映射和快照校验。
依赖边界：默认只跑离线检查；`--require-sdk` 用于 CI 中强制确认已安装官方 MCP SDK extra。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent.mcp_sdk_adapter import adapter_status


class QualityGateStepError(RuntimeError):
    def __init__(self, label: str, result: dict[str, Any]) -> None:
        super().__init__(f"MCP quality gate step failed: {label}")
        self.result = result


def _tail(text: str, *, lines: int = 8) -> str:
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _run_step(label: str, command: list[str], *, json_mode: bool) -> dict[str, Any]:
    if not json_mode:
        print("+ " + " ".join(command))
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    result = {
        "label": label,
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }
    if completed.returncode != 0:
        if completed.stdout and not json_mode:
            print(completed.stdout, end="")
        if completed.stderr and not json_mode:
            print(completed.stderr, end="", file=sys.stderr)
        raise QualityGateStepError(label, result)
    if completed.stdout and not json_mode:
        print(_tail(completed.stdout, lines=3))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 Keepa MCP 协议质量门禁。")
    parser.add_argument("--json", action="store_true", help="输出 JSON 汇总。")
    parser.add_argument("--skip-if-missing", action="store_true", help="缺少可选 mcp 包时跳过 SDK typed 检查。")
    parser.add_argument("--require-sdk", action="store_true", help="要求官方 mcp 包已安装；CI 的 mcp-sdk-adapter job 应使用。")
    args = parser.parse_args(argv)

    status = adapter_status()
    if args.require_sdk and not status["sdk_available"]:
        print("official mcp package is required but not installed", file=sys.stderr)
        return 1

    python = sys.executable
    skip_flag = ["--skip-if-missing"] if args.skip_if_missing and not args.require_sdk else []
    steps = [
        ("agent eval fixtures", [python, "scripts/check_agent_eval_fixtures.py"]),
        ("output schema", [python, "scripts/check_mcp_output_schema.py", "--json"]),
        ("performance gate", [python, "scripts/check_mcp_performance_gate.py", "--json"]),
        ("adapter fixture equivalence", [python, "scripts/compare_mcp_sdk_adapter_fixture.py"]),
        (
            "adapter filter parity",
            [
                python,
                "scripts/compare_mcp_sdk_adapter_fixture.py",
                "--fixture",
                "tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json",
            ],
        ),
        ("sdk typed smoke", [python, "scripts/smoke_mcp_sdk_adapter_client.py", "--json", *skip_flag]),
        ("sdk typed inspector fixture", [python, "scripts/check_mcp_sdk_adapter_typed_fixture.py", "--json", *skip_flag]),
        ("sdk inspector snapshot", [python, "scripts/export_mcp_inspector_snapshot.py", "--check", "--json", *skip_flag]),
    ]

    results: list[dict[str, Any]] = []
    try:
        for label, command in steps:
            results.append(_run_step(label, command, json_mode=args.json))
    except QualityGateStepError as exc:
        payload = {"ok": False, "adapter_status": status, "steps": [*results, exc.result], "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    payload = {"ok": True, "adapter_status": status, "steps": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("mcp quality gate ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
