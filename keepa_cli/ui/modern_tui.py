"""
keepa_cli/ui/modern_tui.py
文件说明：提供基于 prompt_toolkit 的现代命令行交互层。
主要职责：渲染低噪声 REPL、提供 slash 命令补全，并复用 Agent-safe command service。
依赖边界：prompt_toolkit 延迟导入；缺少依赖时自动回退标准库 TUI。
"""

from __future__ import annotations

import html
import importlib.util
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from keepa_cli.capabilities import SCHEMA_VERSION
from keepa_cli.config import build_config_report
from keepa_cli.service import run_command
from keepa_cli.ui.tui import _doctor_context, _slash_to_command, _summarize_success, run_interactive_tui


TEXT: dict[str, dict[str, str]] = {
    "en": {
        "brand": "Keepa CLI",
        "ready": "Type / for commands. Ctrl-L clears the screen. Ctrl-C exits.",
        "setup_token": "Auth is missing. Use /token <64-char Keepa key> or export KEEPA_API_KEY.",
        "setup_budget": "Request budget is using the default. Use /max-tokens 250 to widen it.",
        "bye": "bye",
        "help": "Commands",
        "json": "Full JSON",
        "doctor": "Doctor",
        "capabilities": "Capabilities",
        "domains": "Domains",
        "product": "Product",
        "history": "History",
        "finder": "Finder",
        "bestsellers": "Best Sellers",
        "graph": "Graph Image",
        "tracking": "Tracking",
        "token": "Set Token",
        "budget": "Set Budget",
        "language": "Language",
        "config": "Config",
    },
    "zh": {
        "brand": "Keepa CLI",
        "ready": "输入 / 查看命令。Ctrl-L 清屏，Ctrl-C 退出。",
        "setup_token": "认证未配置。使用 /token <64字符 Keepa key> 或导出 KEEPA_API_KEY。",
        "setup_budget": "请求预算仍为默认值。使用 /max-tokens 250 调宽。",
        "bye": "再见",
        "help": "命令",
        "json": "完整 JSON",
        "doctor": "诊断",
        "capabilities": "能力",
        "domains": "域名",
        "product": "产品",
        "history": "历史",
        "finder": "筛选",
        "bestsellers": "榜单",
        "graph": "图像",
        "tracking": "跟踪",
        "token": "配置 Token",
        "budget": "配置预算",
        "language": "语言",
        "config": "配置",
    },
}


@dataclass(frozen=True)
class CommandItem:
    label: str
    group: str
    slash: str
    service_command: str
    description: str


def is_prompt_tui_available() -> bool:
    return importlib.util.find_spec("prompt_toolkit") is not None


def _language(value: str | None) -> str:
    return "zh" if str(value).lower() == "zh" else "en"


def _config_data(env: Mapping[str, str] | None) -> dict[str, Any]:
    report = build_config_report(env=env)
    config = report.get("config", {})
    return config if isinstance(config, dict) else {}


def _active_language(env: Mapping[str, str] | None) -> str:
    return _language(str(_config_data(env).get("language", "en")))


def build_command_catalog(language: str = "en") -> tuple[CommandItem, ...]:
    text = TEXT[_language(language)]
    return (
        CommandItem(text["doctor"], "Inspect", "/doctor", "doctor", "Auth, config, offline fixture status"),
        CommandItem(text["capabilities"], "Inspect", "/capabilities", "capabilities", "Agent protocol surface"),
        CommandItem(text["domains"], "Inspect", "/domains", "domains.list", "Amazon domain map"),
        CommandItem(text["config"], "Config", "/config", "config.show", "Show effective local config"),
        CommandItem(text["token"], "Config", "/token <64-char Keepa key>", "config.set-token", "Save local token"),
        CommandItem(text["budget"], "Config", "/max-tokens 250", "config.set-max-tokens", "Set request budget"),
        CommandItem(text["language"], "Config", "/language zh", "config.set-language", "Switch UI language"),
        CommandItem(
            text["product"],
            "Catalog",
            "/product B001GZ6QEC --fixture product_B001GZ6QEC.json",
            "products.get",
            "Fixture product lookup",
        ),
        CommandItem(
            text["history"],
            "Catalog",
            "/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json",
            "history.trend",
            "Price history summary",
        ),
        CommandItem(
            text["finder"],
            "Operate",
            "/finder --selection-file keepa_cli/fixtures/finder_selection.json --dry-run",
            "finder.query",
            "Finder dry-run",
        ),
        CommandItem(
            text["bestsellers"],
            "Operate",
            "/bestsellers 172282 --domain US --dry-run",
            "bestsellers.get",
            "Best sellers dry-run",
        ),
        CommandItem(
            text["graph"],
            "Operate",
            "/graph B09YNQCQKR --domain US --param amazon=1 --dry-run",
            "graphs.image",
            "Graph image spec",
        ),
        CommandItem(
            text["tracking"],
            "Operate",
            "/tracking-list --asins-only --dry-run",
            "tracking.list",
            "Tracking dry-run",
        ),
    )


def build_tui_metadata(*, selected_runtime: str | None = None) -> dict[str, Any]:
    return {
        "preferred_runtime": "prompt_toolkit",
        "fallback_runtime": "classic",
        "selected_runtime": selected_runtime or ("prompt_toolkit" if is_prompt_tui_available() else "classic"),
        "schema_version": SCHEMA_VERSION,
        "prompt_toolkit_available": is_prompt_tui_available(),
        "commands": [
            {
                "label": item.label,
                "group": item.group,
                "slash": item.slash,
                "service_command": item.service_command,
            }
            for item in build_command_catalog()
        ],
    }


def _has_configured_token(config_data: Mapping[str, Any]) -> bool:
    return str(config_data.get("api_key", "")).strip() == "[REDACTED]"


def _has_custom_budget(config_data: Mapping[str, Any]) -> bool:
    try:
        return int(config_data.get("max_tokens_per_request", 20)) != 20
    except (TypeError, ValueError):
        return False


def _iter_completion_candidates(text: str, *, language: str = "en") -> tuple[CommandItem, ...]:
    query = text.strip().lower()
    if not query:
        return build_command_catalog(language)
    if not query.startswith("/"):
        return ()
    normalized = query.lstrip("/")
    matches: list[CommandItem] = []
    for item in build_command_catalog(language):
        command_name = item.slash.split()[0].lstrip("/").lower()
        if (
            item.slash.lower().startswith(query)
            or command_name.startswith(normalized)
            or _is_subsequence(normalized, command_name)
            or item.label.lower().startswith(normalized)
        ):
            matches.append(item)
    return tuple(matches)


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    iterator = iter(haystack)
    return all(char in iterator for char in needle)


def _format_result(payload: dict[str, Any], *, language: str = "en") -> str:
    command = str(payload.get("command", "unknown"))
    if payload.get("ok"):
        if _language(language) == "zh":
            return "\n".join(_summarize_success(payload))
        return "\n".join(_summarize_success_english(payload))

    error = payload.get("error", {})
    if isinstance(error, dict):
        if _language(language) == "zh":
            return "\n".join(
                [
                    f"[{command}] ERROR",
                    f"类型    {error.get('kind', 'unknown')}",
                    f"说明    {error.get('message', '')}",
                ]
            )
        return "\n".join(
            [
                f"[{command}] ERROR",
                f"Kind    {error.get('kind', 'unknown')}",
                f"Message {error.get('message', '')}",
            ]
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _summarize_success_english(payload: dict[str, Any]) -> list[str]:
    command = str(payload.get("command", "unknown"))
    data = payload.get("data")
    lines = [f"[{command}] OK"]

    if command == "doctor" and isinstance(data, dict):
        auth = data.get("auth", {})
        offline = data.get("offline", {})
        if isinstance(auth, dict):
            lines.append(f"Auth    {auth.get('source', 'unknown')}")
        if isinstance(offline, dict):
            lines.append(f"Offline fixture={'ready' if offline.get('fixture_available') else 'missing'}")
        return lines

    if command == "capabilities" and isinstance(data, dict):
        commands = data.get("commands", [])
        command_count = len(commands) if isinstance(commands, list) else 0
        lines.append(f"Schema   {data.get('schema_version', '')}")
        lines.append(f"Commands {command_count}")
        lines.append("Modes    json / stdio / TUI")
        return lines

    if isinstance(data, dict):
        if data.get("dry_run"):
            estimate = payload.get("token_bucket", {}).get("estimated", {})
            if isinstance(estimate, dict):
                lines.append(
                    "Budget  "
                    f"estimated={estimate.get('estimated_tokens')} "
                    f"worst={estimate.get('worst_case_tokens')} "
                    f"confirm={estimate.get('requires_confirmation')}"
                )
            lines.append("Request dry-run; Keepa API was not called")
            provenance = data.get("cache_provenance")
            if isinstance(provenance, dict):
                lines.append(f"Source  {provenance.get('source')} hash={str(provenance.get('params_hash', ''))[:10]}")
            return lines
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
                            lines.append(f"History {series} points={points} latest={value}")
                return lines
        if "row_count" in data:
            lines.append(f"Export  rows={data.get('row_count')} format={data.get('format')}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"File    {output.get('path', '')}")
            return lines
        body = data.get("body")
        provenance = data.get("cache_provenance")
        if isinstance(provenance, dict):
            source = provenance.get("source", "")
            fixture = provenance.get("fixture", "")
            lines.append(f"Source  {source} {fixture}".strip())
        if isinstance(body, dict):
            products = body.get("products")
            if isinstance(products, list) and products:
                for product in products[:3]:
                    if isinstance(product, dict):
                        asin = product.get("asin", "")
                        title = product.get("title", "")
                        lines.append(f"Product {asin}  {title}".strip())
                return lines
            categories = body.get("categories")
            if isinstance(categories, dict) and categories:
                for category_id, item in list(categories.items())[:3]:
                    if isinstance(item, dict):
                        lines.append(f"Category {category_id}  {item.get('name', category_id)}")
                return lines
            sellers = body.get("sellers")
            if isinstance(sellers, dict) and sellers:
                for seller_id, item in list(sellers.items())[:3]:
                    name = item.get("sellerName", seller_id) if isinstance(item, dict) else seller_id
                    lines.append(f"Seller  {seller_id}  {name}")
                return lines
            for key, label in (("deals", "Deals"), ("topSellers", "Top sellers")):
                value = body.get(key)
                if isinstance(value, list):
                    lines.append(f"{label} count={len(value)}")
                    return lines
            bestsellers = body.get("bestSellersList")
            if isinstance(bestsellers, dict):
                asin_list = bestsellers.get("asinList")
                count = len(asin_list) if isinstance(asin_list, list) else 0
                lines.append(f"Best sellers category={bestsellers.get('categoryId', '')} count={count}")
                return lines
    lines.append("Done    Structured response received; use --json or the JSON block for the full envelope")
    return lines


def _redact_transcript_command(line: str) -> str:
    command, _params = _slash_to_command(line)
    if command == "config.set-token":
        parts = line.split(maxsplit=1)
        return parts[0] + " [REDACTED]" if parts else "[REDACTED]"
    return line


def _status_bar(env: Mapping[str, str] | None) -> str:
    context = _doctor_context(env)
    config = _config_data(env)
    default_domain = config.get("default_domain", "US")
    max_tokens = config.get("max_tokens_per_request", 20)
    language = _language(str(config.get("language", "en")))
    status = (
        f" Keepa CLI  auth:{context['auth']}  domain:{default_domain}  "
        f"max/request:{max_tokens}  lang:{language}  schema:{SCHEMA_VERSION} "
    )
    return html.escape(status)


def _startup_lines(env: Mapping[str, str] | None) -> list[str]:
    language = _active_language(env)
    text = TEXT[language]
    config = _config_data(env)
    context = _doctor_context(env)
    lines = [
        text["brand"],
        f"Auth {context['auth']} | Domain {config.get('default_domain', 'US')} | Max/request {config.get('max_tokens_per_request', 20)} | Schema {SCHEMA_VERSION}",
        text["ready"],
    ]
    if not _has_configured_token(config) and context["auth"] == "missing":
        lines.append(text["setup_token"])
    if not _has_custom_budget(config):
        lines.append(text["setup_budget"])
    return lines


def _help_lines(*, language: str = "en") -> list[str]:
    text = TEXT[_language(language)]
    lines = [text["help"]]
    for item in build_command_catalog(language):
        lines.append(f"  {item.slash:<72} {item.description}")
    lines.append("  /quit                                                                    Exit")
    return lines


def _create_completer(*, language: str = "en"):
    from prompt_toolkit.completion import Completer, Completion

    class KeepaCompleter(Completer):
        def get_completions(self, document, complete_event):
            before_cursor = document.text_before_cursor
            for item in _iter_completion_candidates(before_cursor, language=language):
                yield Completion(
                    item.slash,
                    start_position=-len(before_cursor),
                    display=item.slash,
                    display_meta=item.description,
                )

    return KeepaCompleter()


def _create_session(*, language: str = "en"):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.styles import Style

    style = Style.from_dict(
        {
            "prompt": "ansigreen bold",
            "toolbar": "reverse",
        }
    )
    return PromptSession(
        history=InMemoryHistory(),
        completer=_create_completer(language=language),
        complete_while_typing=True,
        complete_style=CompleteStyle.COLUMN,
        style=style,
    )


def _print_block(lines: list[str]) -> None:
    for line in lines:
        print(line)


def _run_prompt_loop(*, env: Mapping[str, str] | None, session: Any | None = None) -> int:
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import clear

    language = _active_language(env)
    text = TEXT[language]
    prompt_session = session or _create_session(language=language)
    _print_block(_startup_lines(env))

    while True:
        try:
            line = prompt_session.prompt(
                [("class:prompt", "kc › ")],
                bottom_toolbar=lambda: HTML(f"<style bg='ansiblack' fg='ansiwhite'>{_status_bar(env)}</style>"),
            )
        except (EOFError, KeyboardInterrupt):
            print(text["bye"])
            return 0

        value = line.strip()
        if not value:
            continue
        if value in {"/quit", "quit", "exit"}:
            print(text["bye"])
            return 0
        if value == "/clear":
            clear()
            _print_block(_startup_lines(env))
            continue
        if value == "/help":
            _print_block(_help_lines(language=language))
            continue

        command, params = _slash_to_command(value)
        payload = run_command(command, params, env=env)
        print(f"\n$ kc {_redact_transcript_command(value)}")
        print(_format_result(payload, language=language))
        print(f"{text['json']}:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        language = _active_language(env)
        text = TEXT[language]


def run_modern_tui(*, env: Mapping[str, str] | None = None) -> int:
    if not is_prompt_tui_available():
        return run_interactive_tui(env=env)
    return _run_prompt_loop(env=env)
