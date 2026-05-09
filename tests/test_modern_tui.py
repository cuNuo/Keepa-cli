"""
tests/test_modern_tui.py
文件说明：验证 Textual 现代 TUI 的入口、命令目录与降级路径。
主要职责：确保现代 TUI 使用组件化元数据，同时缺少框架时仍可回退标准库 TUI。
依赖边界：测试不启动真实终端应用，不访问真实 Keepa API。
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from keepa_cli.ui import modern_tui


class ModernTuiTests(unittest.TestCase):
    def test_command_catalog_groups_agent_safe_workflows(self):
        catalog = modern_tui.build_command_catalog()

        labels = {item.label for item in catalog}
        commands = {item.slash for item in catalog}
        groups = {item.group for item in catalog}

        self.assertIn("Product", labels)
        self.assertIn("/product B001GZ6QEC --fixture product_B001GZ6QEC.json", commands)
        self.assertIn("Inspect", groups)
        self.assertIn("Operate", groups)
        self.assertTrue(all(item.service_command for item in catalog))

    def test_command_catalog_defaults_to_english_and_can_switch_to_chinese(self):
        english = modern_tui.build_command_catalog(language="en")
        chinese = modern_tui.build_command_catalog(language="zh")

        self.assertEqual(english[0].label, "Doctor")
        self.assertEqual(chinese[0].label, "诊断")

    def test_stylesheet_contains_textual_layout_selectors(self):
        stylesheet = modern_tui.MODERN_TUI_CSS

        self.assertIn("#status-bar", stylesheet)
        self.assertIn("#result-panel", stylesheet)
        self.assertIn("#quickbar", stylesheet)
        self.assertIn("#command-row", stylesheet)
        self.assertNotIn("CommandButton", stylesheet)

    def test_run_modern_tui_falls_back_when_textual_is_missing(self):
        with (
            patch("keepa_cli.ui.modern_tui.is_textual_available", return_value=False),
            patch("keepa_cli.ui.modern_tui.run_interactive_tui", return_value=0) as fallback,
        ):
            exit_code = modern_tui.run_modern_tui(env={})

        self.assertEqual(exit_code, 0)
        fallback.assert_called_once_with(env={})

    def test_run_modern_tui_starts_textual_app_when_available(self):
        class FakeApp:
            def __init__(self, *, env=None):
                self.env = env

            def run(self):
                return None

        with (
            patch("keepa_cli.ui.modern_tui.is_textual_available", return_value=True),
            patch("keepa_cli.ui.modern_tui._create_app_class", return_value=FakeApp) as create_app,
        ):
            exit_code = modern_tui.run_modern_tui(env={"KEEPA_API_KEY": "secret"})

        self.assertEqual(exit_code, 0)
        create_app.assert_called_once()

    def test_textual_app_updates_result_panel_from_shortcut(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(100, 32)) as pilot:
                await pilot.press("f1")
                return str(pilot.app.query_one("#result-body").renderable)

        rendered = asyncio.run(run_smoke())

        self.assertIn("[doctor] OK", rendered)

    def test_textual_app_saves_token_from_input(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke(config_path: Path):
            app_class = modern_tui._create_app_class()
            async with app_class(env={"KEEPA_CLI_CONFIG": str(config_path)}).run_test(size=(100, 32)) as pilot:
                token_input = pilot.app.query_one("#token-input")
                token_input.value = "A" * 64
                await pilot.click("#save-token")
                body = str(pilot.app.query_one("#result-body").renderable)
                token_value = token_input.value
                return body, token_value

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            rendered, token_value = asyncio.run(run_smoke(config_path))
            content = config_path.read_text(encoding="utf-8")

        self.assertIn("Token saved", rendered)
        self.assertEqual(token_value, "")
        self.assertIn(f'api_key = "{"A" * 64}"', content)
        self.assertNotIn("A" * 64, rendered)

    def test_textual_app_rejects_invalid_token_before_writing(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke(config_path: Path):
            app_class = modern_tui._create_app_class()
            async with app_class(env={"KEEPA_CLI_CONFIG": str(config_path)}).run_test(size=(100, 32)) as pilot:
                pilot.app.query_one("#token-input").value = "short"
                await pilot.click("#save-token")
                return str(pilot.app.query_one("#result-body").renderable), config_path.exists()

        with TemporaryDirectory() as temp_dir:
            rendered, exists = asyncio.run(run_smoke(Path(temp_dir) / "config.toml"))

        self.assertIn("64", rendered)
        self.assertFalse(exists)

    def test_textual_app_uses_chinese_when_configured(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke(config_path: Path):
            config_path.write_text('language = "zh"\n', encoding="utf-8")
            app_class = modern_tui._create_app_class()
            async with app_class(env={"KEEPA_CLI_CONFIG": str(config_path)}).run_test(size=(100, 32)) as pilot:
                command_input = pilot.app.query_one("#command-input")
                command_input.value = "/"
                await pilot.pause()
                return str(pilot.app.query_one("#quickbar").renderable)

        with TemporaryDirectory() as temp_dir:
            rendered = asyncio.run(run_smoke(Path(temp_dir) / "config.toml"))

        self.assertIn("诊断", rendered)

    def test_textual_app_hides_settings_after_existing_config(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke(config_path: Path):
            config_path.write_text(
                f'api_key = "{"A" * 64}"\nmax_tokens_per_request = 250\n',
                encoding="utf-8",
            )
            app_class = modern_tui._create_app_class()
            async with app_class(env={"KEEPA_CLI_CONFIG": str(config_path)}).run_test(size=(100, 32)) as pilot:
                return "hidden" in pilot.app.query_one("#settings-row").classes

        with TemporaryDirectory() as temp_dir:
            hidden = asyncio.run(run_smoke(Path(temp_dir) / "config.toml"))

        self.assertTrue(hidden)

    def test_command_input_has_initial_focus(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(80, 24)) as pilot:
                return pilot.app.focused.id

        focused_id = asyncio.run(run_smoke())

        self.assertEqual(focused_id, "command-input")

    def test_textual_app_suggests_commands_after_slash(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(100, 32)) as pilot:
                command_input = pilot.app.query_one("#command-input")
                command_input.value = "/pro"
                await pilot.pause()
                return str(pilot.app.query_one("#quickbar").renderable)

        rendered = asyncio.run(run_smoke())

        self.assertIn("/product", rendered)

    def test_textual_app_selects_suggestion_with_arrow_keys(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(100, 32)) as pilot:
                command_input = pilot.app.query_one("#command-input")
                command_input.value = "/"
                await pilot.press("down")
                await pilot.press("enter")
                return command_input.value

        value = asyncio.run(run_smoke())

        self.assertEqual(value, "/capabilities")

    def test_textual_app_outputs_parsed_command_and_copyable_json(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(100, 32)) as pilot:
                command_input = pilot.app.query_one("#command-input")
                command_input.value = "/doctor"
                await pilot.press("enter")
                title = str(pilot.app.query_one("#result-title").renderable)
                copy_text = str(pilot.app.query_one("#result-copy-body").renderable)
                return title, copy_text

        title, copy_text = asyncio.run(run_smoke())

        self.assertIn("doctor", title)
        self.assertIn('"command": "doctor"', copy_text)

    def test_textual_app_copy_output_is_scrollable(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(80, 18)) as pilot:
                command_input = pilot.app.query_one("#command-input")
                command_input.value = "/capabilities"
                await pilot.press("enter")
                output = pilot.app.query_one("#result-copy")
                before = output.scroll_y
                output.scroll_down()
                await pilot.pause()
                return before, output.scroll_y, output.max_scroll_y

        before, after, max_scroll_y = asyncio.run(run_smoke())

        self.assertGreater(max_scroll_y, 0)
        self.assertGreaterEqual(after, before)

    def test_textual_app_saves_max_tokens_setting(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke(config_path: Path):
            app_class = modern_tui._create_app_class()
            async with app_class(env={"KEEPA_CLI_CONFIG": str(config_path)}).run_test(size=(100, 32)) as pilot:
                max_tokens = pilot.app.query_one("#max-tokens-input")
                max_tokens.value = "250"
                await pilot.click("#save-max-tokens")
                body = str(pilot.app.query_one("#result-body").renderable)
                return body

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            rendered = asyncio.run(run_smoke(config_path))
            content = config_path.read_text(encoding="utf-8")

        self.assertIn("Budget saved", rendered)
        self.assertIn("max_tokens_per_request = 250", content)


if __name__ == "__main__":
    unittest.main()
