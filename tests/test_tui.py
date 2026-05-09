"""
tests/test_tui.py
文件说明：验证标准库 TUI 工作台的信息流。
主要职责：确保 TUI 只通过 command service 执行业务命令并输出人类摘要。
依赖边界：不使用真实终端控制，不访问真实 Keepa API。
"""

import unittest

from keepa_cli.ui.tui import run_tui_session


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
        self.assertIn("Keepa CLI 工作台", rendered)
        self.assertIn("doctor: ok", rendered)
        self.assertIn("products.get: ok", rendered)
        self.assertIn("B001GZ6QEC", rendered)
        self.assertIn("再见", rendered)

    def test_tui_unknown_command_returns_structured_error_summary(self):
        output = run_tui_session(["/unknown", "/quit"], env={})

        rendered = "\n".join(output)
        self.assertIn("unsupported_command", rendered)


if __name__ == "__main__":
    unittest.main()
