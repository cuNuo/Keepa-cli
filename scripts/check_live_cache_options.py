"""
scripts/check_live_cache_options.py
文件说明：审计 live CLI 命令是否显式暴露缓存控制参数。
主要职责：防止新增 live 命令遗漏 --cache-ttl / --no-cache。
依赖边界：只构建 argparse parser，不访问 Keepa API。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keepa_cli.capabilities import COMMANDS  # noqa: E402
from keepa_cli.cli import _build_parser  # noqa: E402


NON_CACHEABLE_LIVE_COMMANDS = {
    "graphs.image",
    "tracking.add",
    "tracking.remove",
    "tracking.remove-all",
    "tracking.webhook",
}


def _subparser_actions(parser: argparse.ArgumentParser) -> list[argparse._SubParsersAction[Any]]:
    return [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]


def _walk_parser(parser: argparse.ArgumentParser, parts: tuple[str, ...] = ()) -> dict[tuple[str, ...], argparse.ArgumentParser]:
    result = {parts: parser}
    for action in _subparser_actions(parser):
        for name, child in action.choices.items():
            result.update(_walk_parser(child, (*parts, name)))
    return result


def cacheable_live_cli_commands() -> list[str]:
    return sorted(
        item["name"]
        for item in COMMANDS
        if item.get("supports_live") and str(item["name"]).replace(".", " ").split()[0] not in {"graphs"}
        and item["name"] not in NON_CACHEABLE_LIVE_COMMANDS
    )


def missing_live_cache_options() -> list[str]:
    parsers = _walk_parser(_build_parser())
    missing: list[str] = []
    for command in cacheable_live_cli_commands():
        parser = parsers.get(tuple(command.split(".")))
        if parser is None:
            continue
        options = {option for action in parser._actions for option in action.option_strings}
        if "--cache-ttl" not in options or "--no-cache" not in options:
            missing.append(command)
    return missing


def main() -> int:
    missing = missing_live_cache_options()
    if missing:
        print("以下 live CLI 命令缺少 --cache-ttl / --no-cache：")
        for command in missing:
            print(f"- {command}")
        return 1
    print("live cache option 检查通过：所有 live CLI 命令均显式暴露 --cache-ttl / --no-cache。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
