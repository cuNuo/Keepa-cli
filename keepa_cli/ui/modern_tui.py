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
        "hero_title": "Command Deck",
        "hero_flow": "Inspect  Preview  Export  Record",
        "token_placeholder": "Keepa token",
        "save": "Save",
        "result": "Result",
        "ready": "Ready",
        "config": "Config",
        "token_empty": "Token is empty",
        "token_saved": "Token saved",
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
        "hero_title": "命令面板",
        "hero_flow": "检查  预览  导出  记录",
        "token_placeholder": "Keepa token",
        "save": "保存",
        "result": "结果",
        "ready": "就绪",
        "config": "配置",
        "token_empty": "Token 不能为空",
        "token_saved": "Token 已保存",
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
    layout: horizontal;
    height: 1fr;
}

#sidebar {
    width: 32;
    min-width: 28;
    background: #161b20;
    border-right: tall #33414b;
    padding: 1 1;
}

#brand {
    height: auto;
    margin-bottom: 1;
    padding: 1;
    border: round #4f7d7a;
    background: #0f1d1f;
    color: #e6f4f1;
    text-style: bold;
}

#token-row {
    height: 3;
    margin-bottom: 1;
}

#token-input {
    width: 1fr;
    height: 3;
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

.status-card {
    height: auto;
    margin: 0 0 1 0;
    padding: 1;
    border: round #35424b;
    background: #11181d;
}

#command-rail {
    height: 1fr;
    scrollbar-color: #8fb7a8;
}

CommandButton {
    width: 100%;
    height: 3;
    min-height: 3;
    margin: 0 0 1 0;
    border: round #313b42;
    background: #1c2329;
    color: #dce4e8;
}

CommandButton:hover {
    background: #26323a;
    border: round #8fb7a8;
}

#main {
    width: 1fr;
    padding: 1 2;
}

#hero {
    height: 4;
    padding: 1 2;
    border: round #47616d;
    background: #172026;
    color: #f5f0df;
}

#command-input {
    margin-top: 1;
    height: 3;
    border: round #8fb7a8;
    background: #0f1418;
}

#result-panel {
    height: 1fr;
    margin-top: 1;
    padding: 1 2;
    border: round #47616d;
    background: #11171b;
}

#result-title {
    height: 1;
    color: #f2c66d;
    text-style: bold;
}

#result-body {
    height: 1fr;
    margin-top: 1;
    color: #dce4e8;
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


def _create_app_class():
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, ScrollableContainer, Vertical
    from textual.message import Message
    from textual.widgets import Button, Footer, Header, Input, Static

    class CommandButton(Button):
        def __init__(self, item: CommandItem) -> None:
            super().__init__(item.label, id=f"cmd-{item.service_command.replace('.', '-')}")
            self.item = item

        class Selected(Message):
            def __init__(self, item: CommandItem) -> None:
                self.item = item
                super().__init__()

        def on_button_pressed(self) -> None:
            self.post_message(self.Selected(self.item))

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

        def compose(self) -> ComposeResult:
            context = _doctor_context(self.env)
            config = build_config_report(env=self.env)
            config_data = config.get("config", {}) if isinstance(config.get("config"), dict) else {}
            language = _language(str(config_data.get("language", "en")))
            text = TEXT[language]
            default_domain = config_data.get("default_domain", "US")
            yield Header(show_clock=True)
            with Horizontal(id="workspace"):
                with Vertical(id="sidebar"):
                    yield Static(text["brand"], id="brand")
                    yield Static(
                        "\n".join(
                            [
                                f"Auth      {context['auth']}",
                                f"Domain    {default_domain}",
                                f"Schema    {SCHEMA_VERSION}",
                            ]
                        ),
                        classes="status-card",
                    )
                    with Horizontal(id="token-row"):
                        yield Input(placeholder=text["token_placeholder"], password=True, id="token-input")
                        yield Button(text["save"], id="save-token")
                    with ScrollableContainer(id="command-rail"):
                        for item in build_command_catalog(language):
                            yield CommandButton(item)
                with Vertical(id="main"):
                    yield Static(
                        "\n".join(
                            [
                                text["hero_title"],
                                text["hero_flow"],
                            ]
                        ),
                        id="hero",
                    )
                    yield Input(placeholder="/doctor", id="command-input")
                    with Vertical(id="result-panel"):
                        yield Static(text["result"], id="result-title")
                        yield Static(text["ready"], id="result-body")
            yield Footer()

        def on_command_button_selected(self, event: CommandButton.Selected) -> None:
            self._run_slash(event.item.slash)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "token-input":
                self._save_token(event.value)
                return
            value = event.value.strip()
            if not value:
                return
            event.input.value = ""
            if value in {"/quit", "quit", "exit"}:
                self.exit()
                return
            self._run_slash(value)

        def action_doctor(self) -> None:
            self._run_slash("/doctor")

        def action_capabilities(self) -> None:
            self._run_slash("/capabilities")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "save-token":
                token = self.query_one("#token-input", Input).value
                self._save_token(token)

        def _run_slash(self, slash: str) -> None:
            command, params = _slash_to_command(slash)
            payload = run_command(command, params, env=self.env)
            title = f"Result  {slash}"
            self.query_one("#result-title", Static).update(title)
            self.query_one("#result-body", Static).update(_format_result(payload))

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
                self.query_one("#result-body", Static).update(f"{text['token_saved']}\n{path}")
            else:
                self.query_one("#result-body", Static).update(_format_result(payload))

        def _text(self) -> dict[str, str]:
            config = build_config_report(env=self.env)
            config_data = config.get("config", {}) if isinstance(config.get("config"), dict) else {}
            return TEXT[_language(str(config_data.get("language", "en")))]

    return KeepaModernTui


def run_modern_tui(*, env: dict[str, str] | None = None) -> int:
    if not is_textual_available():
        return run_interactive_tui(env=env)
    app_class = _create_app_class()
    app_class(env=env).run()
    return 0
