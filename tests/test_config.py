"""
tests/test_config.py
文件说明：验证本地配置默认值和 dry-run TOML 输出。
主要职责：确保 config 报告适合 Agent 读取且默认配置不包含密钥。
依赖边界：不写入用户真实配置目录。
"""

import unittest

from keepa_cli.config import build_config_report, render_config_toml


class ConfigTests(unittest.TestCase):
    def test_default_config_report_is_agent_readable(self):
        report = build_config_report(env={})

        self.assertFalse(report["exists"])
        self.assertEqual(report["config"]["default_domain"], "US")
        self.assertIn("config.toml", report["path"])

    def test_render_config_toml_contains_safe_defaults(self):
        rendered = render_config_toml()

        self.assertIn('default_domain = "US"', rendered)
        self.assertIn("max_tokens_per_request = 20", rendered)
        self.assertNotIn("KEEPA_API_KEY", rendered)


if __name__ == "__main__":
    unittest.main()
