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

from keepa_cli.config import (
    build_config_report,
    load_config,
    render_config_toml,
    set_api_token,
    set_language,
    set_max_tokens_per_request,
    validate_api_token,
)


class ConfigTests(unittest.TestCase):
    def test_default_config_report_is_agent_readable(self):
        report = build_config_report(env={})

        self.assertFalse(report["exists"])
        self.assertTrue(report["valid"])
        self.assertIsNone(report["error"])
        self.assertEqual(report["config"]["default_domain"], "US")
        self.assertEqual(report["config"]["language"], "en")
        self.assertIn("config.toml", report["path"])

    def test_invalid_toml_falls_back_to_defaults_with_error_report(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('api_key = ".\\.venv\\Scripts\\python.exe -m keepa_cli"\n', encoding="utf-8")

            loaded = load_config(config_path)
            report = build_config_report(config_path)

        self.assertEqual(loaded["default_domain"], "US")
        self.assertIn("_config_error", loaded)
        self.assertFalse(report["valid"])
        self.assertEqual(report["error"]["kind"], "toml_decode_error")
        self.assertNotIn("api_key", report["config"])

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
            token = "A" * 64

            result = set_api_token(token, path=config_path)
            loaded = load_config(config_path)
            report = build_config_report(config_path)

        self.assertTrue(result["written"])
        self.assertEqual(result["auth_source"], "config")
        self.assertEqual(loaded["api_key"], token)
        self.assertEqual(report["config"]["api_key"], "[REDACTED]")
        self.assertNotIn(token, str(report))

    def test_set_api_token_rejects_empty_value(self):
        with self.assertRaises(ValueError):
            set_api_token("  ", path="unused.toml")

    def test_validate_api_token_requires_64_visible_characters(self):
        self.assertEqual(validate_api_token("A" * 64), "A" * 64)

        for value in ("A" * 63, "A" * 65, "A" * 32 + " " + "A" * 31, "A" * 32 + "\n" + "A" * 31):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_api_token(value)

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

    def test_set_max_tokens_per_request_persists_positive_integer(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"

            result = set_max_tokens_per_request("250", path=config_path)
            loaded = load_config(config_path)

        self.assertTrue(result["written"])
        self.assertEqual(result["max_tokens_per_request"], 250)
        self.assertEqual(loaded["max_tokens_per_request"], 250)

    def test_set_max_tokens_per_request_rejects_non_positive_value(self):
        for value in ("0", "-1", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    set_max_tokens_per_request(value, path="unused.toml")


if __name__ == "__main__":
    unittest.main()
