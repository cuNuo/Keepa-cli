"""
tests/test_config.py
文件说明：验证本地配置默认值和 dry-run TOML 输出。
主要职责：确保 config 报告适合 Agent 读取且默认配置不包含密钥。
依赖边界：不写入用户真实配置目录。
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from keepa_cli.config import build_config_report, load_config, render_config_toml, set_api_token, set_language


class ConfigTests(unittest.TestCase):
    def test_default_config_report_is_agent_readable(self):
        report = build_config_report(env={})

        self.assertFalse(report["exists"])
        self.assertEqual(report["config"]["default_domain"], "US")
        self.assertEqual(report["config"]["language"], "en")
        self.assertIn("config.toml", report["path"])

    def test_explicit_empty_env_ignores_real_appdata(self):
        with patch.dict("os.environ", {"APPDATA": "C:\\RealUser\\AppData\\Roaming"}, clear=False):
            report = build_config_report(env={})

        self.assertNotIn("RealUser", report["path"])

    def test_render_config_toml_contains_safe_defaults(self):
        rendered = render_config_toml()

        self.assertIn('default_domain = "US"', rendered)
        self.assertIn('language = "en"', rendered)
        self.assertIn("max_tokens_per_request = 20", rendered)
        self.assertNotIn("KEEPA_API_KEY", rendered)

    def test_set_api_token_writes_local_config_and_report_redacts_it(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"

            result = set_api_token("SECRET123", path=config_path)
            loaded = load_config(config_path)
            report = build_config_report(config_path)

        self.assertTrue(result["written"])
        self.assertEqual(result["auth_source"], "config")
        self.assertEqual(loaded["api_key"], "SECRET123")
        self.assertEqual(report["config"]["api_key"], "[REDACTED]")
        self.assertNotIn("SECRET123", str(report))

    def test_set_api_token_rejects_empty_value(self):
        with self.assertRaises(ValueError):
            set_api_token("  ", path="unused.toml")

    def test_set_language_persists_supported_language(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"

            result = set_language("zh", path=config_path)
            loaded = load_config(config_path)

        self.assertTrue(result["written"])
        self.assertEqual(result["language"], "zh")
        self.assertEqual(loaded["language"], "zh")

    def test_set_language_rejects_unknown_language(self):
        with self.assertRaises(ValueError):
            set_language("fr", path="unused.toml")


if __name__ == "__main__":
    unittest.main()
