"""
keepa_cli/ui/tui.py
文件说明：提供标准库实现的人类可用 TUI 工作台。
主要职责：解析 slash 命令、调用 command service，并渲染简洁的人类摘要。
依赖边界：不直接构造 Keepa API 请求，不访问网络，业务能力全部委托 service。
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping
from typing import Any

from keepa_cli.service import run_command


def _parse_options(tokens: list[str]) -> tuple[list[str], dict[str, Any]]:
    positional: list[str] = []
    options: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            positional.append(token)
            index += 1
            continue
        name = token[2:]
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
            options[name] = tokens[index + 1]
            index += 2
        else:
            options[name] = True
            index += 1
    return positional, options


def _slash_to_command(line: str) -> tuple[str, dict[str, Any]]:
    tokens = shlex.split(line)
    if not tokens:
        return "help", {}
    slash_command = tokens[0].lstrip("/").lower()
    positional, options = _parse_options(tokens[1:])

    if slash_command == "doctor":
        return "doctor", {}
    if slash_command == "domains":
        return "domains.list", {}
    if slash_command == "product":
        return "products.get", {"asin": positional, **options}
    if slash_command == "category":
        return "categories.get", {"category": positional, **options}
    if slash_command == "category-search":
        return "categories.search", {"term": " ".join(positional), **options}
    return slash_command, options


def _summarize_payload(payload: dict[str, Any]) -> str:
    command = str(payload.get("command", "unknown"))
    if not payload.get("ok"):
        error = payload.get("error", {})
        return f"{command}: error {error.get('kind', 'unknown')}: {error.get('message', '')}"

    summary = f"{command}: ok"
    data = payload.get("data")
    if isinstance(data, dict):
        body = data.get("body")
        if isinstance(body, dict):
            products = body.get("products")
            if isinstance(products, list) and products:
                asin = products[0].get("asin", "")
                title = products[0].get("title", "")
                return f"{summary} product={asin} {title}".strip()
            categories = body.get("categories")
            if isinstance(categories, dict) and categories:
                names = [str(item.get("name", category_id)) for category_id, item in categories.items()]
                return f"{summary} categories={', '.join(names[:3])}"
    return summary


def run_tui_session(input_lines: Iterable[str], *, env: Mapping[str, str] | None = None) -> list[str]:
    output = [
        "Keepa CLI 工作台",
        "输入 /doctor、/product <ASIN>、/category <ID>、/category-search <term> 或 /quit。",
    ]
    for raw_line in input_lines:
        line = raw_line.strip()
        if not line:
            continue
        if line in {"/quit", "quit", "exit"}:
            output.append("再见")
            break
        command, params = _slash_to_command(line)
        payload = run_command(command, params, env=env)
        output.append(_summarize_payload(payload))
    return output


def run_interactive_tui(*, env: Mapping[str, str] | None = None) -> int:
    print("Keepa CLI 工作台")
    print("输入 /doctor、/product <ASIN>、/category <ID>、/category-search <term> 或 /quit。")
    while True:
        try:
            line = input("kc> ").strip()
        except EOFError:
            print("再见")
            return 0
        if line in {"/quit", "quit", "exit"}:
            print("再见")
            return 0
        if not line:
            continue
        command, params = _slash_to_command(line)
        payload = run_command(command, params, env=env)
        print(_summarize_payload(payload))
