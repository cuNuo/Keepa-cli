"""
keepa_cli/ui/modern_tui.py
文件说明：提供基于 Textual 的现代终端工作台。
主要职责：渲染组件化 TUI、接收 slash 命令，并复用 Agent-safe command service。
依赖边界：Textual 仅延迟导入；缺少依赖时自动回退标准库 TUI。
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from typing import Any

from keepa_cli.capabilities import SCHEMA_VERSION
from keepa_cli.config import build_config_report
from keepa_cli.service import run_command
from keepa_cli.ui.tui import _doctor_context, _slash_to_command, _summarize_success, run_interactive_tui


TEXT: dict[str, dict[str, str]] = {
    "en": {
        "brand": "Keepa CLI",
        "token_placeholder": "Keepa token",
        "budget_placeholder": "Max tokens/request",
        "save": "Save",
        "budget_save": "Budget",
        "result": "Output",
        "ready": "Type / for commands",
        "settings": "Settings",
        "settings_hint": "Token or max tokens missing",
        "suggestions": "Commands",
        "config": "Config",
        "token_empty": "Token is empty",
        "token_saved": "Token saved",
        "budget_saved": "Budget saved",
        "doctor": "Doctor",
        "capabilities": "Capabilities",
        "domains": "Domains",
        "product": "Product",
        "history": "History",
        "finder": "Finder",
        "bestsellers": "Best Sellers",
        "graph": "Graph Image",
        "tracking": "Tracking",
    },
    "zh": {
        "brand": "Keepa CLI",
        "token_placeholder": "Keepa token",
        "budget_placeholder": "单次最大 token",
        "save": "保存",
        "budget_save": "预算",
        "result": "输出",
        "ready": "输入 / 查看命令",
        "settings": "设置",
        "settings_hint": "Token 或单次 token 上限未配置",
        "suggestions": "命令",
        "config": "配置",
        "token_empty": "Token 不能为空",
        "token_saved": "Token 已保存",
        "budget_saved": "预算已保存",
        "doctor": "诊断",
        "capabilities": "能力",
        "domains": "域名",
        "product": "产品",
        "history": "历史",
        "finder": "筛选",
        "bestsellers": "榜单",
        "graph": "图像",
        "tracking": "跟踪",
    },
}


MODERN_TUI_CSS = """
Screen {
    layout: vertical;
    background: #101418;
    color: #dce4e8;
}

#workspace {
    layout: vertical;
    height: 1fr;
    padding: 1 2;
}

#status-bar {
    height: 3;
    padding: 0 1;
    border-bottom: tall #33414b;
    background: #141a1f;
}

#brand {
    height: auto;
    width: 16;
    color: #e6f4f1;
    text-style: bold;
}

#status-line {
    width: 1fr;
    color: #9fb3bd;
}

#settings-row {
    height: 3;
    margin: 1 0 0 0;
}

#settings-row.hidden {
    display: none;
}

#token-input {
    width: 1fr;
    height: 3;
    border: round #47616d;
    background: #0f1418;
}

#max-tokens-input {
    width: 20;
    height: 3;
    margin-left: 1;
    border: round #47616d;
    background: #0f1418;
}

#save-token {
    width: 9;
    height: 3;
    margin-left: 1;
    border: round #8fb7a8;
    background: #1f302e;
}

#save-max-tokens {
    width: 10;
    height: 3;
    margin-left: 1;
    border: round #8fb7a8;
    background: #1f302e;
}

#quickbar {
    height: auto;
    max-height: 6;
    margin-top: 1;
    padding: 1;
    border: round #35424b;
    background: #11181d;
    color: #dce4e8;
}

#quickbar.hidden {
    display: none;
}

#result-panel {
    height: 1fr;
    margin-top: 1;
    padding: 1 2;
    border: round #47616d;
    background: #11171b;
}

#command-input {
    height: 3;
    border: round #8fb7a8;
    background: #0f1418;
}

#command-row {
    height: 3;
    margin-top: 1;
}

#result-title {
    height: 1;
    color: #f2c66d;
    text-style: bold;
}

#result-body {
    height: auto;
    max-height: 8;
    margin-top: 1;
    color: #dce4e8;
}

#result-copy {
    height: 1fr;
    margin-top: 1;
    border: round #35424b;
    background: #0f1418;
    scrollbar-size: 1 1;
}

#result-copy .text-area--cursor-line {
    background: #0f1418;
}
"""


@dataclass(frozen=True)
class CommandItem:
    label: str
    group: str
    slash: str
    service_command: str
    description: str


def is_textual_available() -> bool:
    return importlib.util.find_spec("textual") is not None


def _language(value: str | None) -> str:
    return "zh" if str(value).lower() == "zh" else "en"


def build_command_catalog(language: str = "en") -> tuple[CommandItem, ...]:
    text = TEXT[_language(language)]
    return (
        CommandItem(
            label=text["doctor"],
            group="Inspect",
            slash="/doctor",
            service_command="doctor",
            description="Auth and local status",
        ),
        CommandItem(
            label=text["capabilities"],
            group="Inspect",
            slash="/capabilities",
            service_command="capabilities",
            description="Agent protocol surface",
        ),
        CommandItem(
            label=text["domains"],
            group="Inspect",
            slash="/domains",
            service_command="domains.list",
            description="Amazon domain map",
        ),
        CommandItem(
            label=text["product"],
            group="Catalog",
            slash="/product B001GZ6QEC --fixture product_B001GZ6QEC.json",
            service_command="products.get",
            description="Fixture product lookup",
        ),
        CommandItem(
            label=text["history"],
            group="Catalog",
            slash="/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json",
            service_command="history.trend",
            description="Price history summary",
        ),
        CommandItem(
            label=text["finder"],
            group="Operate",
            slash="/finder --selection-file keepa_cli/fixtures/finder_selection.json --dry-run",
            service_command="finder.query",
            description="Finder dry-run",
        ),
        CommandItem(
            label=text["bestsellers"],
            group="Operate",
            slash="/bestsellers 172282 --domain US --dry-run",
            service_command="bestsellers.get",
            description="Best sellers dry-run",
        ),
        CommandItem(
            label=text["graph"],
            group="Operate",
            slash="/graph B09YNQCQKR --domain US --param amazon=1 --dry-run",
            service_command="graphs.image",
            description="Graph image spec",
        ),
        CommandItem(
            label=text["tracking"],
            group="Operate",
            slash="/tracking-list --asins-only --dry-run",
            service_command="tracking.list",
            description="Tracking dry-run",
        ),
    )


def build_tui_metadata(*, selected_runtime: str | None = None) -> dict[str, Any]:
    return {
        "preferred_runtime": "textual",
        "fallback_runtime": "classic",
        "selected_runtime": selected_runtime or ("textual" if is_textual_available() else "classic"),
        "schema_version": SCHEMA_VERSION,
        "textual_available": is_textual_available(),
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


def _format_result(payload: dict[str, Any]) -> str:
    command = str(payload.get("command", "unknown"))
    if payload.get("ok"):
        lines = _summarize_success(payload)
        return "\n".join(lines)
    error = payload.get("error", {})
    if isinstance(error, dict):
        return "\n".join(
            [
                f"[{command}] ERROR",
                f"类型    {error.get('kind', 'unknown')}",
                f"说明    {error.get('message', '')}",
            ]
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _has_configured_token(config_data: dict[str, Any]) -> bool:
    return str(config_data.get("api_key", "")).strip() == "[REDACTED]"


def _has_configured_budget(config_data: dict[str, Any]) -> bool:
    try:
        return int(config_data.get("max_tokens_per_request", 0)) > 0
    except (TypeError, ValueError):
        return False


def _settings_needed(config_data: dict[str, Any]) -> bool:
    return not (_has_configured_token(config_data) and _has_configured_budget(config_data))


def _create_app_class():
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, ScrollableContainer, Vertical
    from textual.events import Key
    from textual.widgets import Button, Header, Input, Static, TextArea
    from rich.text import Text

    class KeepaModernTui(App[None]):
        CSS = MODERN_TUI_CSS
        TITLE = "Keepa CLI Command Deck"
        SUB_TITLE = "offline-first Agent-safe workspace"
        BINDINGS = [
            ("ctrl+c", "quit", "退出"),
            ("ctrl+d", "quit", "退出"),
            ("f1", "doctor", "Doctor"),
            ("f2", "capabilities", "Capabilities"),
        ]

        def __init__(self, *, env: dict[str, str] | None = None) -> None:
            super().__init__()
            self.env = env
            self._suggestions: list[CommandItem] = []
            self._suggestion_index = 0

        def compose(self) -> ComposeResult:
            context = _doctor_context(self.env)
            config = build_config_report(env=self.env)
            config_data = config.get("config", {}) if isinstance(config.get("config"), dict) else {}
            language = _language(str(config_data.get("language", "en")))
            text = TEXT[language]
            default_domain = config_data.get("default_domain", "US")
            max_tokens = config_data.get("max_tokens_per_request", 20)
            settings_classes = "" if _settings_needed(config_data) else "hidden"
            yield Header(show_clock=True)
            with Vertical(id="workspace"):
                with Horizontal(id="status-bar"):
                    yield Static(text["brand"], id="brand")
                    yield Static(
                        f"Auth {context['auth']}   Domain {default_domain}   Max/request {max_tokens}   Schema {SCHEMA_VERSION}",
                        id="status-line",
                    )
                yield Static("", id="quickbar", classes="hidden")
                with Horizontal(id="settings-row", classes=settings_classes):
                    yield Input(placeholder=text["token_placeholder"], password=True, id="token-input")
                    yield Button(text["save"], id="save-token")
                    yield Input(placeholder=text["budget_placeholder"], id="max-tokens-input")
                    yield Button(text["budget_save"], id="save-max-tokens")
                with Vertical(id="result-panel"):
                    yield Static(text["result"], id="result-title")
                    yield Static(text["ready"], id="result-body")
                    with ScrollableContainer(id="result-copy"):
                        yield Static("", id="result-copy-body")
                with Vertical(id="command-row"):
                    yield Input(placeholder="/doctor", id="command-input")

        def on_mount(self) -> None:
            self.query_one("#command-input", Input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "token-input":
                self._save_token(event.value)
                return
            if event.input.id == "max-tokens-input":
                self._save_max_tokens(event.value)
                return
            value = event.value.strip()
            if not value:
                return
            if event.input.id == "command-input" and self._suggestions:
                selected = self._suggestions[self._suggestion_index]
                if value != selected.slash:
                    self._accept_suggestion()
                    return
            event.input.value = ""
            self._hide_suggestions()
            if value in {"/quit", "quit", "exit"}:
                self.exit()
                return
            self._run_slash(value)

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id != "command-input":
                return
            self._update_suggestions(event.value)

        def on_key(self, event: Key) -> None:
            focused = self.focused
            if not isinstance(focused, Input) or focused.id != "command-input" or not self._suggestions:
                return
            if event.key in {"down", "ctrl+n"}:
                self._move_suggestion(1)
                event.stop()
                event.prevent_default()
            if event.key in {"up", "ctrl+p"}:
                self._move_suggestion(-1)
                event.stop()
                event.prevent_default()

        def action_doctor(self) -> None:
            self._run_slash("/doctor")

        def action_capabilities(self) -> None:
            self._run_slash("/capabilities")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "save-token":
                token = self.query_one("#token-input", Input).value
                self._save_token(token)
            if event.button.id == "save-max-tokens":
                value = self.query_one("#max-tokens-input", Input).value
                self._save_max_tokens(value)

        def _run_slash(self, slash: str) -> None:
            command, params = _slash_to_command(slash)
            payload = run_command(command, params, env=self.env)
            title = f"Result  {command}"
            formatted = _format_result(payload)
            detail = json.dumps(payload, ensure_ascii=False, indent=2)
            self.query_one("#result-title", Static).update(title)
            self.query_one("#result-body", Static).update(Text(formatted))
            self.query_one("#result-copy-body", Static).update(Text(detail))

        def _save_token(self, token: str) -> None:
            text = self._text()
            token = token.strip()
            if not token:
                self.query_one("#result-title", Static).update(text["config"])
                self.query_one("#result-body", Static).update(text["token_empty"])
                return
            payload = run_command("config.set-token", {"token": token}, env=self.env)
            self.query_one("#token-input", Input).value = ""
            self.query_one("#result-title", Static).update(text["config"])
            if payload.get("ok"):
                data = payload.get("data", {})
                path = data.get("path", "") if isinstance(data, dict) else ""
                self.query_one("#result-body", Static).update(Text(f"{text['token_saved']}\n{path}"))
                self._refresh_status()
                self._collapse_settings_if_complete()
            else:
                self.query_one("#result-body", Static).update(Text(_format_result(payload)))

        def _save_max_tokens(self, value: str) -> None:
            text = self._text()
            payload = run_command("config.set-max-tokens", {"max_tokens": value}, env=self.env)
            self.query_one("#max-tokens-input", Input).value = ""
            self.query_one("#result-title", Static).update(text["config"])
            if payload.get("ok"):
                data = payload.get("data", {})
                max_tokens = data.get("max_tokens_per_request", "") if isinstance(data, dict) else ""
                self.query_one("#result-body", Static).update(Text(f"{text['budget_saved']}\n{max_tokens}"))
                self._refresh_status()
                self._collapse_settings_if_complete()
            else:
                self.query_one("#result-body", Static).update(Text(_format_result(payload)))

        def _text(self) -> dict[str, str]:
            config = build_config_report(env=self.env)
            config_data = config.get("config", {}) if isinstance(config.get("config"), dict) else {}
            return TEXT[_language(str(config_data.get("language", "en")))]

        def _quickbar(self, language: str) -> str:
            commands = build_command_catalog(language)
            return "\n".join(f"{item.label:<13} {item.slash}" for item in commands[:5])

        def _update_suggestions(self, value: str) -> None:
            quickbar = self.query_one("#quickbar", Static)
            query = value.strip().lower()
            if not query.startswith("/"):
                self._hide_suggestions()
                return
            language = _language(str(build_config_report(env=self.env).get("config", {}).get("language", "en")))
            matches = [
                item
                for item in build_command_catalog(language)
                if item.slash.lower().startswith(query) or item.label.lower().startswith(query.lstrip("/"))
            ][:5]
            self._suggestions = matches
            self._suggestion_index = min(self._suggestion_index, max(len(matches) - 1, 0))
            if not matches:
                quickbar.update("")
                quickbar.add_class("hidden")
                return
            quickbar.update(self._render_suggestions())
            quickbar.remove_class("hidden")

        def _hide_suggestions(self) -> None:
            quickbar = self.query_one("#quickbar", Static)
            quickbar.update("")
            quickbar.add_class("hidden")
            self._suggestions = []
            self._suggestion_index = 0

        def _render_suggestions(self) -> Text:
            rendered = Text()
            for index, item in enumerate(self._suggestions):
                prefix = "> " if index == self._suggestion_index else "  "
                style = "bold #f2c66d" if index == self._suggestion_index else "#dce4e8"
                rendered.append(f"{prefix}{item.label:<13} {item.slash}", style=style)
                if index < len(self._suggestions) - 1:
                    rendered.append("\n")
            return rendered

        def _move_suggestion(self, delta: int) -> None:
            if not self._suggestions:
                return
            self._suggestion_index = (self._suggestion_index + delta) % len(self._suggestions)
            self.query_one("#quickbar", Static).update(self._render_suggestions())

        def _accept_suggestion(self) -> None:
            selected = self._suggestions[self._suggestion_index]
            self.query_one("#command-input", Input).value = selected.slash
            self._hide_suggestions()

        def _refresh_status(self) -> None:
            context = _doctor_context(self.env)
            config = build_config_report(env=self.env)
            config_data = config.get("config", {}) if isinstance(config.get("config"), dict) else {}
            default_domain = config_data.get("default_domain", "US")
            max_tokens = config_data.get("max_tokens_per_request", 20)
            self.query_one("#status-line", Static).update(
                f"Auth {context['auth']}   Domain {default_domain}   Max/request {max_tokens}   Schema {SCHEMA_VERSION}"
            )

        def _collapse_settings_if_complete(self) -> None:
            config = build_config_report(env=self.env)
            config_data = config.get("config", {}) if isinstance(config.get("config"), dict) else {}
            settings = self.query_one("#settings-row")
            if _settings_needed(config_data):
                settings.remove_class("hidden")
            else:
                settings.add_class("hidden")

    return KeepaModernTui


def run_modern_tui(*, env: dict[str, str] | None = None) -> int:
    if not is_textual_available():
        return run_interactive_tui(env=env)
    app_class = _create_app_class()
    app_class(env=env).run()
    return 0
