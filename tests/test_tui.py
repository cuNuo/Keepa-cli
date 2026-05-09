"""
tests/test_tui.py
文件说明：验证标准库 TUI 工作台的信息流。
主要职责：确保 TUI 只通过 command service 执行业务命令并输出人类摘要。
依赖边界：不使用真实终端控制，不访问真实 Keepa API。
"""

import unittest
from io import StringIO
from unittest.mock import patch

from keepa_cli.ui.tui import run_interactive_tui, run_tui_session


class TuiTests(unittest.TestCase):
    def test_tui_session_runs_doctor_and_fixture_product(self):
        output = run_tui_session(
            [
                "/doctor",
                "/product B001GZ6QEC --domain US --fixture product_B001GZ6QEC.json",
                "/quit",
            ],
            env={},
        )

        rendered = "\n".join(output)
        self.assertIn("╭", rendered)
        self.assertIn("Keepa CLI 工作台", rendered)
        self.assertIn("Agent-first Keepa API workspace", rendered)
        self.assertIn("常用命令", rendered)
        self.assertIn("上下文", rendered)
        self.assertIn("结果", rendered)
        self.assertIn("[doctor] OK", rendered)
        self.assertIn("[products.get] OK", rendered)
        self.assertIn("B001GZ6QEC", rendered)
        self.assertIn("Fixture product", rendered)
        self.assertIn("再见", rendered)

    def test_tui_unknown_command_returns_structured_error_summary(self):
        output = run_tui_session(["/unknown", "/quit"], env={})

        rendered = "\n".join(output)
        self.assertIn("[unknown] ERROR", rendered)
        self.assertIn("unsupported_command", rendered)

    def test_tui_history_command_returns_trend_summary(self):
        output = run_tui_session(
            ["/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json", "/quit"],
            env={},
        )

        rendered = "\n".join(output)
        self.assertIn("[history.trend] OK", rendered)
        self.assertIn("amazon", rendered)
        self.assertIn("10.99", rendered)

    def test_piped_interactive_tui_prints_session_output_on_separate_lines(self):
        stdin = StringIO("/doctor\n/quit\n")
        stdout = StringIO()

        with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            exit_code = run_interactive_tui(env={})

        rendered = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("kc> /doctor", rendered)
        self.assertNotIn("kc> +", rendered)


if __name__ == "__main__":
    unittest.main()
