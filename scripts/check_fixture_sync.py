"""
scripts/check_fixture_sync.py
文件说明：检查 tests/fixtures 与 keepa_cli/fixtures 是否同步。
主要职责：防止测试 fixture 与 npm/Python 包内 fixture 发生漂移。
依赖边界：纯文件系统检查，不访问网络或真实 Keepa API。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from keepa_cli.fixture_sync import FixtureSyncResult, compare_fixture_dirs


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
