"""
scripts/check_fixture_sync.py
文件说明：检查 tests/fixtures 与 keepa_cli/fixtures 是否同步。
主要职责：防止测试 fixture 与 npm/Python 包内 fixture 发生漂移。
依赖边界：纯文件系统检查，不访问网络或真实 Keepa API。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FixtureSyncResult:
    ok: bool
    missing_in_package: list[str]
    missing_in_tests: list[str]
    mismatched: list[str]


def _json_files(path: Path) -> dict[str, Path]:
    return {item.name: item for item in sorted(path.glob("*.json"))}


def compare_fixture_dirs(tests_dir: Path, package_dir: Path) -> FixtureSyncResult:
    tests = _json_files(tests_dir)
    package = _json_files(package_dir)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="检查测试 fixture 与包内 fixture 是否同步。")
    parser.add_argument("--tests-dir", default="tests/fixtures")
    parser.add_argument("--package-dir", default="keepa_cli/fixtures")
    args = parser.parse_args()

    result = compare_fixture_dirs(Path(args.tests_dir), Path(args.package_dir))
    if result.ok:
        print("fixture sync ok")
        return 0
    if result.missing_in_package:
        print("missing in package:", ", ".join(result.missing_in_package))
    if result.missing_in_tests:
        print("missing in tests:", ", ".join(result.missing_in_tests))
    if result.mismatched:
        print("mismatched:", ", ".join(result.mismatched))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
