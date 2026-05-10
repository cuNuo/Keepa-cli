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
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from keepa_cli.capabilities import SCHEMA_VERSION
from keepa_cli.config import build_config_report
from keepa_cli.service import run_command
from keepa_cli.ui.tui import _doctor_context, _slash_to_command, _summarize_success, run_interactive_tui


ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN = "\033[36m"


TEXT: dict[str, dict[str, str]] = {
    "en": {
        "brand": "Keepa CLI",
        "ready": "Type / for commands. Ctrl-L clears.",
        "setup_token": "No token. Run /login <64-char Keepa key> or export KEEPA_API_KEY.",
        "setup_budget": "Default request cap is 20 tokens. Raise it with /max-tokens 250.",
        "bye": "bye",
        "help": "Commands",
        "json": "Full JSON",
        "no_json": "No command response yet.",
        "last_json": "Last JSON",
        "doctor": "Doctor",
        "capabilities": "Capabilities",
        "domains": "Domains",
        "browse": "Browse",
        "batch": "Batch",
        "templates": "Templates",
        "report": "Report",
        "cache": "Cache",
        "cost": "Cost",
        "product": "Product",
        "history": "History",
        "finder": "Finder",
        "bestsellers": "Best Sellers",
        "graph": "Graph Image",
        "tracking": "Tracking",
        "login": "Login",
        "token": "Set Token",
        "budget": "Set Budget",
        "language": "Language",
        "config": "Config",
    },
    "zh": {
        "brand": "Keepa CLI",
        "ready": "输入 / 查看命令。Ctrl-L 清屏。",
        "setup_token": "未配置 token。运行 /login <64字符 Keepa key> 或导出 KEEPA_API_KEY。",
        "setup_budget": "默认单次请求上限为 20 tokens，可用 /max-tokens 250 调宽。",
        "bye": "再见",
        "help": "命令",
        "json": "完整 JSON",
        "no_json": "还没有可查看的命令响应。",
        "last_json": "上一条 JSON",
        "doctor": "诊断",
        "capabilities": "能力",
        "domains": "域名",
        "browse": "浏览",
        "batch": "批处理",
        "templates": "模板",
        "report": "报告",
        "cache": "缓存",
        "cost": "成本",
        "product": "产品",
        "history": "历史",
        "finder": "筛选",
        "bestsellers": "榜单",
        "graph": "图像",
        "tracking": "跟踪",
        "login": "登录",
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
    insert: str | None = None

    @property
    def command_name(self) -> str:
        return self.slash.split()[0]

    @property
    def completion_text(self) -> str:
        if self.insert is not None:
            return self.insert
        return self.command_name if " " not in self.slash else f"{self.command_name} "


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
        CommandItem(text["login"], "Config", "/login <64-char Keepa key>", "config.set-token", "Save local token"),
        CommandItem(text["token"], "Config", "/token <64-char Keepa key>", "config.set-token", "Save local token"),
        CommandItem(text["budget"], "Config", "/max-tokens 250", "config.set-max-tokens", "Set request budget"),
        CommandItem(text["language"], "Config", "/language zh", "config.set-language", "Switch UI language"),
        CommandItem(
            text["browse"],
            "Local",
            "/browse --input batch.json --out-dir keepa-browse",
            "browse.snapshot",
            "Build local HTML browse view",
        ),
        CommandItem(
            text["batch"],
            "Local",
            "/batch asins.txt --domain US --dry-run --out batch.json",
            "batch.asins",
            "Plan ASIN batch queries",
        ),
        CommandItem(text["templates"], "Local", "/templates", "templates.list", "List workflow templates"),
        CommandItem(
            text["report"],
            "Local",
            "/report --input batch.json --format markdown --out report.md",
            "reports.build",
            "Build local report",
        ),
        CommandItem(
            text["cache"],
            "Local",
            "/cache --input response.json --command products.get",
            "cache.explain",
            "Explain cache provenance",
        ),
        CommandItem(text["cost"], "Local", "/cost products.get", "audit.cost", "Estimate token cost"),
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
        command_name = item.command_name.lstrip("/").lower()
        if (
            item.slash.lower().startswith(query)
            or command_name.startswith(normalized)
            or _is_subsequence(normalized, command_name)
            or item.label.lower().startswith(normalized)
            or item.service_command.lower().startswith(normalized)
        ):
            matches.append(item)
    return tuple(matches)


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    iterator = iter(haystack)
    return all(char in iterator for char in needle)


def _ansi(style: str, value: str) -> str:
    return f"{style}{value}{ANSI_RESET}"


def _colorize_summary(summary: str) -> str:
    lines: list[str] = []
    for line in summary.splitlines():
        if "ERROR" in line:
            lines.append(_ansi(ANSI_RED, line))
        elif re.match(r"^\[[^\]]+\] OK$", line):
            lines.append(_ansi(ANSI_GREEN, line))
        elif line.startswith(("Budget", "预算", "Token", "Tokens", "Confirm", "确认", "No token", "未配置")):
            lines.append(_ansi(ANSI_YELLOW, line))
        else:
            lines.append(line)
    return "\n".join(lines)


def _colorize_startup(lines: list[str]) -> list[str]:
    colored: list[str] = []
    for index, line in enumerate(lines):
        if index == 0:
            colored.append(_ansi(ANSI_CYAN, line))
        elif "No token" in line or "未配置 token" in line or "Default request cap" in line or "默认单次请求上限" in line:
            colored.append(_ansi(ANSI_YELLOW, line))
        else:
            colored.append(_ansi(ANSI_DIM, line))
    return colored


def _colorize_transcript(line: str) -> str:
    return f"{ANSI_DIM}$ {ANSI_RESET}{ANSI_CYAN}kc{ANSI_RESET} {line}"


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
        if command == "browse.snapshot":
            lines.append(f"Browse  rows={data.get('row_count', 0)} dir={data.get('out_dir', '')}")
            lines.append(f"Open    {data.get('index', '')}")
            return lines
        if command == "batch.asins":
            lines.append(f"Batch   tasks={data.get('task_count', 0)} tokens={data.get('estimated_tokens', 0)}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"File    {output.get('path', '')}")
            return lines
        if command == "templates.list":
            templates = data.get("templates", [])
            count = len(templates) if isinstance(templates, list) else 0
            names = ", ".join(str(item.get("name", "")) for item in templates[:4] if isinstance(item, dict))
            lines.append(f"Templates count={count}")
            if names:
                lines.append(f"Names   {names}")
            return lines
        if command == "templates.show":
            lines.append(f"Template {data.get('name', '')} kind={data.get('kind', '')}")
            return lines
        if command == "reports.build":
            lines.append(f"Report  rows={data.get('row_count', 0)} format={data.get('format', '')}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"File    {output.get('path', '')}")
            return lines
        if command == "cache.explain":
            lines.append(f"Cache   source={data.get('source', 'unknown')} hit={data.get('cache_hit', False)}")
            lines.append(f"Tokens  saved={data.get('estimated_tokens_saved', 0)} live={data.get('estimated_tokens_if_live', 0)}")
            return lines
        if command == "audit.cost":
            totals = data.get("totals", {})
            if isinstance(totals, dict):
                lines.append(
                    f"Cost    estimated={totals.get('estimated_tokens', 0)} worst={totals.get('worst_case_tokens', 0)}"
                )
            lines.append(f"Confirm {data.get('requires_confirmation', False)}")
            return lines
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
    lines.append("Done    Structured response received")
    return lines


def _redact_transcript_command(line: str) -> str:
    first_token = line.strip().split(maxsplit=1)[0].lower() if line.strip() else ""
    if first_token in {"/token", "/login"}:
        parts = line.split(maxsplit=1)
        return parts[0] + " [REDACTED]" if parts else "[REDACTED]"
    return line


def _status_bar(env: Mapping[str, str] | None) -> str:
    context = _doctor_context(env)
    config = _config_data(env)
    default_domain = config.get("default_domain", "US")
    max_tokens = config.get("max_tokens_per_request", 20)
    language = _language(str(config.get("language", "en")))
    auth = html.escape(str(context["auth"]))
    if context["auth"] == "missing":
        auth_fragment = f"<style fg='ansiyellow'>auth:{auth}</style>"
    else:
        auth_fragment = f"<style fg='ansigreen'>auth:{auth}</style>"
    content = (
        f"{auth_fragment}"
        f"  <style fg='ansibrightblack'>{html.escape(str(default_domain))}</style>"
        f"  <style fg='ansibrightblack'>max:{html.escape(str(max_tokens))}</style>"
        f"  <style fg='ansibrightblack'>{html.escape(language)}</style>"
        "  <style fg='ansibrightblack'>/help /json /quit</style>"
    )
    return f"<style bg='#111315'> {content} </style>"


def _json_hint(text: Mapping[str, str]) -> str:
    return _ansi(ANSI_DIM, f"json: /json")


def _startup_lines(env: Mapping[str, str] | None) -> list[str]:
    language = _active_language(env)
    text = TEXT[language]
    config = _config_data(env)
    context = _doctor_context(env)
    lines = [f"{text['brand']}  auth:{context['auth']}  schema:{SCHEMA_VERSION}", text["ready"]]
    if not _has_configured_token(config) and context["auth"] == "missing":
        lines.append(text["setup_token"])
    if not _has_custom_budget(config):
        lines.append(text["setup_budget"])
    return lines


def _help_lines(*, language: str = "en") -> list[str]:
    text = TEXT[_language(language)]
    lines = [text["help"]]
    current_group = ""
    for item in build_command_catalog(language):
        if item.group != current_group:
            current_group = item.group
            lines.append(f"{current_group}:")
        lines.append(f"  {item.slash:<52} {item.description}")
    lines.append("Session:")
    lines.append("  /json                                                Show last full JSON response")
    lines.append("  /clear                                               Clear screen")
    lines.append("  /quit                                                Exit")
    return lines


def _create_completer(*, language: str = "en"):
    from prompt_toolkit.completion import Completer, Completion

    class KeepaCompleter(Completer):
        def get_completions(self, document, complete_event):
            before_cursor = document.text_before_cursor
            for item in _iter_completion_candidates(before_cursor, language=language):
                yield Completion(
                    item.completion_text,
                    start_position=-len(before_cursor),
                    display=[
                        ("class:completion.command", f"{item.command_name:<18}"),
                        ("class:completion.label", item.label),
                    ],
                    display_meta=[("class:completion.meta", f"{item.group} · {item.description}")],
                )

    return KeepaCompleter()


def _create_session(*, language: str = "en"):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.styles import Style

    style = Style.from_dict(
        {
            "prompt": "ansicyan bold",
            "bottom-toolbar": "bg:#111315 #7f858d",
            "completion-menu.completion": "bg:#202124 #d0d0d0",
            "completion-menu.completion.current": "bg:#2d333b #ffffff",
            "completion-menu.meta.completion": "bg:#202124 #8a8f98",
            "completion-menu.meta.completion.current": "bg:#2d333b #c0c6d0",
            "completion.command": "ansicyan",
            "completion.label": "#d0d0d0",
            "completion.meta": "#8a8f98",
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
    last_payload: dict[str, Any] | None = None
    _print_block(_colorize_startup(_startup_lines(env)))

    while True:
        try:
            line = prompt_session.prompt(
                [("class:prompt", "kc › ")],
                bottom_toolbar=lambda: HTML(_status_bar(env)),
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
            _print_block(_colorize_startup(_startup_lines(env)))
            continue
        if value == "/help":
            _print_block(_help_lines(language=language))
            continue
        if value == "/json":
            if last_payload is None:
                print(text["no_json"])
            else:
                print(f"{text['last_json']}:")
                print(json.dumps(last_payload, ensure_ascii=False, indent=2))
            continue

        try:
            command, params = _slash_to_command(value)
            payload = run_command(command, params, env=env)
        except ValueError as exc:
            payload = {"ok": False, "command": value.lstrip("/").split()[0] or "input", "error": {"kind": "input", "message": str(exc)}}
        last_payload = payload
        print()
        print(_colorize_transcript(_redact_transcript_command(value)))
        print(_colorize_summary(_format_result(payload, language=language)))
        print(_json_hint(text))
        language = _active_language(env)
        text = TEXT[language]


def run_modern_tui(*, env: Mapping[str, str] | None = None) -> int:
    if not is_prompt_tui_available():
        return run_interactive_tui(env=env)
    return _run_prompt_loop(env=env)
