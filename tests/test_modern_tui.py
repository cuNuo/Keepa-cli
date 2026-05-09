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

        self.assertIn("#sidebar", stylesheet)
        self.assertIn("#result-panel", stylesheet)
        self.assertIn(".status-card", stylesheet)
        self.assertIn("CommandButton", stylesheet)

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
                token_input.value = "SECRET123"
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
        self.assertIn('api_key = "SECRET123"', content)
        self.assertNotIn("SECRET123", rendered)

    def test_textual_app_uses_chinese_when_configured(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke(config_path: Path):
            config_path.write_text('language = "zh"\n', encoding="utf-8")
            app_class = modern_tui._create_app_class()
            async with app_class(env={"KEEPA_CLI_CONFIG": str(config_path)}).run_test(size=(100, 32)) as pilot:
                return str(pilot.app.query_one("#hero").renderable)

        with TemporaryDirectory() as temp_dir:
            rendered = asyncio.run(run_smoke(Path(temp_dir) / "config.toml"))

        self.assertIn("命令面板", rendered)

    def test_command_buttons_keep_visible_content_height_in_narrow_window(self):
        if not modern_tui.is_textual_available():
            self.skipTest("Textual 未安装，跳过真实 TUI 交互 smoke。")

        import asyncio

        async def run_smoke():
            app_class = modern_tui._create_app_class()
            async with app_class(env={}).run_test(size=(34, 30)) as pilot:
                doctor = pilot.app.query_one("#cmd-doctor")
                product = pilot.app.query_one("#cmd-products-get")
                return doctor.size.height, product.size.height, str(doctor.label), str(product.label)

        doctor_height, product_height, doctor_label, product_label = asyncio.run(run_smoke())

        self.assertGreaterEqual(doctor_height, 1)
        self.assertGreaterEqual(product_height, 1)
        self.assertIn("Doctor", doctor_label)
        self.assertIn("Product", product_label)


if __name__ == "__main__":
    unittest.main()
