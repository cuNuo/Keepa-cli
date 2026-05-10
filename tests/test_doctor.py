"""
tests/test_doctor.py
文件说明：验证 doctor 健康检查报告。
主要职责：覆盖缺失认证、有环境变量认证和凭据不泄露场景。
依赖边界：使用显式 env 映射，不读取真实环境变量。
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from keepa_cli.doctor import build_doctor_report


class DoctorTests(unittest.TestCase):
    def test_doctor_reports_missing_auth_without_failing(self):
        env = {}
        report = build_doctor_report(env=env, fixture_available=True)

        self.assertFalse(report["auth"]["available"])
        self.assertEqual(report["auth"]["source"], "missing")
        self.assertTrue(report["offline"]["fixture_available"])

    def test_explicit_empty_env_does_not_read_real_environment(self):
        with patch.dict(os.environ, {"KEEPA_API_KEY": "REAL_SECRET"}, clear=False):
            report = build_doctor_report(env={}, fixture_available=True)

        self.assertFalse(report["auth"]["available"])
        self.assertEqual(report["auth"]["source"], "missing")
        self.assertNotIn("REAL_SECRET", str(report))

    def test_doctor_detects_env_auth_without_leaking_key(self):
        env = {"KEEPA_API_KEY": "SECRET123"}
        report = build_doctor_report(env=env, fixture_available=False)

        self.assertTrue(report["auth"]["available"])
        self.assertEqual(report["auth"]["source"], "env")
        self.assertNotIn("SECRET123", str(report))

    def test_doctor_detects_config_auth_without_leaking_key(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('api_key = "SECRET123"\n', encoding="utf-8")

            report = build_doctor_report(env={"KEEPA_CLI_CONFIG": str(config_path)}, fixture_available=True)

        self.assertTrue(report["auth"]["available"])
        self.assertEqual(report["auth"]["source"], "config")
        self.assertNotIn("SECRET123", str(report))

    def test_doctor_reports_invalid_config_without_crashing(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('api_key = ".\\.venv\\Scripts\\python.exe -m keepa_cli"\n', encoding="utf-8")

            report = build_doctor_report(env={"KEEPA_CLI_CONFIG": str(config_path)}, fixture_available=True)

        self.assertFalse(report["auth"]["available"])
        self.assertEqual(report["auth"]["source"], "config_error")
        self.assertEqual(report["auth"]["error"]["kind"], "toml_decode_error")

    def test_env_auth_takes_precedence_over_config_auth(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('api_key = "CONFIG_SECRET"\n', encoding="utf-8")

            report = build_doctor_report(
                env={"KEEPA_API_KEY": "ENV_SECRET", "KEEPA_CLI_CONFIG": str(config_path)},
                fixture_available=True,
            )

        self.assertTrue(report["auth"]["available"])
        self.assertEqual(report["auth"]["source"], "env")
        self.assertNotIn("ENV_SECRET", str(report))
        self.assertNotIn("CONFIG_SECRET", str(report))


if __name__ == "__main__":
    unittest.main()
