"""
keepa_cli/fixture_sync.py
文件说明：检查测试 fixture 与包内 fixture 是否同步。
主要职责：为 CLI、MCP 和 release 脚本提供可复用的 fixture parity 检查。
依赖边界：纯文件系统检查，不访问网络或真实 Keepa API。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FixtureSyncResult:
    ok: bool
    missing_in_package: list[str]
    missing_in_tests: list[str]
    mismatched: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "missing_in_package": list(self.missing_in_package),
            "missing_in_tests": list(self.missing_in_tests),
            "mismatched": list(self.mismatched),
        }


def _json_files(path: Path) -> dict[str, Path]:
    return {item.name: item for item in sorted(path.glob("*.json"))}


def compare_fixture_dirs(tests_dir: Path | str, package_dir: Path | str) -> FixtureSyncResult:
    tests_path = Path(tests_dir)
    package_path = Path(package_dir)
    tests = _json_files(tests_path)
    package = _json_files(package_path)
    missing_in_package = sorted(set(tests) - set(package))
    missing_in_tests = sorted(set(package) - set(tests))
    mismatched = sorted(
        name for name in set(tests) & set(package) if tests[name].read_bytes() != package[name].read_bytes()
    )
    return FixtureSyncResult(
        ok=not missing_in_package and not missing_in_tests and not mismatched,
        missing_in_package=missing_in_package,
        missing_in_tests=missing_in_tests,
        mismatched=mismatched,
    )
