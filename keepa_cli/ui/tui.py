"""
keepa_cli/ui/tui.py
文件说明：提供标准库实现的人类可用 TUI 工作台。
主要职责：解析 slash 命令、调用 command service，并渲染简洁的人类摘要。
依赖边界：不直接构造 Keepa API 请求，不访问网络，业务能力全部委托 service。
"""

from __future__ import annotations

import shlex
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from keepa_cli.service import run_command


PANEL_WIDTH = 78


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _fit(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    output = ""
    used = 0
    for char in text:
        char_width = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
        if used + char_width > width - 1:
            break
        output += char
        used += char_width
    return output + "…"


def _pad(text: str, width: int) -> str:
    fitted = _fit(text, width)
    return fitted + " " * max(width - _display_width(fitted), 0)


def _panel(title: str, lines: Iterable[str], *, width: int = PANEL_WIDTH) -> list[str]:
    inner_width = width - 4
    output = [
        "╭" + "─" * (width - 2) + "╮",
        "│ " + _pad(title, inner_width) + " │",
        "├" + "─" * (width - 2) + "┤",
    ]
    for line in lines:
        output.append("│ " + _pad(line, inner_width) + " │")
    output.append("╰" + "─" * (width - 2) + "╯")
    return output


def _doctor_context(env: Mapping[str, str] | None) -> dict[str, Any]:
    payload = run_command("doctor", env=env)
    if not payload.get("ok"):
        return {"auth": "unknown", "fixture": "unknown", "version": "unknown"}

    data = payload.get("data", {})
    auth = data.get("auth", {}) if isinstance(data, dict) else {}
    offline = data.get("offline", {}) if isinstance(data, dict) else {}
    return {
        "auth": str(auth.get("source", "missing")),
        "fixture": "ready" if offline.get("fixture_available") else "missing",
        "version": str(data.get("version", "unknown")),
    }


def _welcome(env: Mapping[str, str] | None) -> list[str]:
    context = _doctor_context(env)
    return [
        *_panel(
            "Keepa CLI 工作台",
            [
                "Agent-first Keepa API workspace",
                f"上下文  auth={context['auth']}  fixture={context['fixture']}  version={context['version']}",
                "模式    默认离线优先；live 请求必须显式配置 KEEPA_API_KEY",
                "入口    keepa-cli 与 kc 完全等价；Agent 使用 --json / --stdio",
            ],
        ),
        "",
        *_panel(
            "常用命令",
            [
                "/doctor",
                "/domains",
                "/product B001GZ6QEC --domain US --fixture product_B001GZ6QEC.json",
                "/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json",
                "/category 0 --domain US --parents --fixture category_roots_US.json",
                "/category-search home kitchen --domain US --fixture category_search_home.json",
                "/quit",
            ],
        ),
    ]


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
    if slash_command == "product-search":
        return "products.search", {"term": " ".join(positional), **options}
    if slash_command == "history":
        return "history.trend", {"asin": positional[:1], **options}
    if slash_command == "history-export":
        return "history.export", {"asin": positional[:1], **options}
    if slash_command == "category":
        return "categories.get", {"category": positional, **options}
    if slash_command == "category-search":
        return "categories.search", {"term": " ".join(positional), **options}
    return slash_command, options


def _summarize_success(payload: dict[str, Any]) -> list[str]:
    command = str(payload.get("command", "unknown"))
    data = payload.get("data")
    lines = [f"[{command}] OK"]

    if command == "doctor" and isinstance(data, dict):
        auth = data.get("auth", {})
        offline = data.get("offline", {})
        if isinstance(auth, dict):
            lines.append(f"认证    {auth.get('source', 'unknown')}")
        if isinstance(offline, dict):
            lines.append(f"离线    fixture={'ready' if offline.get('fixture_available') else 'missing'}")
        return lines

    if isinstance(data, dict):
        analysis = data.get("analysis")
        if isinstance(analysis, dict):
            series_map = analysis.get("series", {})
            if isinstance(series_map, dict):
                for series, series_data in list(series_map.items())[:3]:
                    if isinstance(series_data, dict):
                        all_time = series_data.get("all_time", {})
                        if isinstance(all_time, dict):
                            latest = all_time.get("latest", {})
                            points = all_time.get("points", 0)
                            value = latest.get("value") if isinstance(latest, dict) else ""
                            lines.append(f"历史    {series} points={points} latest={value}")
                return lines
        if "row_count" in data:
            lines.append(f"导出    rows={data.get('row_count')} format={data.get('format')}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"文件    {output.get('path', '')}")
            return lines
        body = data.get("body")
        if isinstance(body, dict):
            products = body.get("products")
            if isinstance(products, list) and products:
                for product in products[:3]:
                    if isinstance(product, dict):
                        asin = product.get("asin", "")
                        title = product.get("title", "")
                        lines.append(f"产品    {asin}  {title}".strip())
                return lines
            categories = body.get("categories")
            if isinstance(categories, dict) and categories:
                for category_id, item in list(categories.items())[:3]:
                    if isinstance(item, dict):
                        lines.append(f"分类    {category_id}  {item.get('name', category_id)}")
                return lines
    lines.append("完成    已收到结构化响应；Agent 可使用 --json 查看完整 envelope")
    return lines


def _summarize_payload(payload: dict[str, Any]) -> list[str]:
    command = str(payload.get("command", "unknown"))
    if payload.get("ok"):
        return _panel(f"结果 [{command}] OK", _summarize_success(payload))

    error = payload.get("error", {})
    kind = error.get("kind", "unknown") if isinstance(error, dict) else "unknown"
    message = error.get("message", "") if isinstance(error, dict) else ""
    return _panel(
        f"结果 [{command}] ERROR",
        [
            f"[{command}] ERROR",
            f"类型    {kind}",
            f"说明    {message}",
        ],
    )


def run_tui_session(input_lines: Iterable[str], *, env: Mapping[str, str] | None = None) -> list[str]:
    output = _welcome(env)
    for raw_line in input_lines:
        line = raw_line.strip()
        if not line:
            continue
        output.append("")
        output.append(f"kc> {line}")
        if line in {"/quit", "quit", "exit"}:
            output.extend(_panel("会话", ["再见"]))
            break
        if line == "/help":
            output.extend(_welcome(env))
            continue
        command, params = _slash_to_command(line)
        payload = run_command(command, params, env=env)
        output.extend(_summarize_payload(payload))
    return output


def run_interactive_tui(*, env: Mapping[str, str] | None = None) -> int:
    if not sys.stdin.isatty():
        for line in run_tui_session(sys.stdin, env=env):
            print(line)
        return 0

    for line in _welcome(env):
        print(line)
    while True:
        try:
            line = input("kc> ").strip()
        except EOFError:
            for output_line in _panel("会话", ["再见"]):
                print(output_line)
            return 0
        if line in {"/quit", "quit", "exit"}:
            for output_line in _panel("会话", ["再见"]):
                print(output_line)
            return 0
        if not line:
            continue
        if line == "/help":
            for output_line in _welcome(env):
                print(output_line)
            continue
        command, params = _slash_to_command(line)
        payload = run_command(command, params, env=env)
        for output_line in _summarize_payload(payload):
            print(output_line)
