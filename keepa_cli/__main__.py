"""
keepa_cli/__main__.py
文件说明：支持 python -m keepa_cli 的模块入口。
主要职责：转发到 keepa_cli.cli.main，便于未安装 console script 时验证。
依赖边界：不包含业务逻辑，只负责入口转发。
"""

from __future__ import annotations

from keepa_cli.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
