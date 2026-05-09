"""
keepa_cli/doctor.py
文件说明：生成 CLI 本地健康检查报告。
主要职责：检查版本、认证来源、fixture/offline 状态与双入口约束。
依赖边界：只报告认证来源，不返回或持久化明文凭据。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from keepa_cli import __version__


PACKAGE_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def find_auth_source(env: Mapping[str, str] | None = None) -> dict[str, object]:
    env = os.environ if env is None else env
    if env.get("KEEPA_API_KEY"):
        return {"available": True, "source": "env"}
    return {"available": False, "source": "missing"}


def build_doctor_report(
    *,
    env: Mapping[str, str] | None = None,
    fixture_available: bool | None = None,
) -> dict[str, object]:
    if fixture_available is None:
        fixture_available = PACKAGE_FIXTURE_DIR.exists() or Path("tests/fixtures").exists()

    return {
        "version": __version__,
        "auth": find_auth_source(env),
        "offline": {
            "fixture_available": bool(fixture_available),
            "auth_required": False,
        },
        "commands": {
            "primary": "keepa-cli",
            "alias": "kc",
            "parity_required": True,
        },
    }
