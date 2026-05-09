"""
tests/test_project_tools.py
文件说明：验证项目级发布门禁、fixture 同步和 cassette 脱敏工具。
主要职责：确保本地质量入口可被 CI 与 Agent 稳定调用。
依赖边界：只使用临时目录和标准库，不访问真实 Keepa API。
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_fixture_sync import compare_fixture_dirs
from scripts.redact_cassette import redact_cassette_payload


class ProjectToolTests(unittest.TestCase):
    def test_fixture_sync_detects_missing_and_mismatched_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "tests" / "fixtures"
            right = root / "keepa_cli" / "fixtures"
            left.mkdir(parents=True)
            right.mkdir(parents=True)
            (left / "same.json").write_text('{"ok": true}\n', encoding="utf-8")
            (right / "same.json").write_text('{"ok": true}\n', encoding="utf-8")
            (left / "missing_in_right.json").write_text("{}\n", encoding="utf-8")
            (right / "missing_in_left.json").write_text("{}\n", encoding="utf-8")
            (left / "different.json").write_text('{"value": 1}\n', encoding="utf-8")
            (right / "different.json").write_text('{"value": 2}\n', encoding="utf-8")

            result = compare_fixture_dirs(left, right)

        self.assertFalse(result.ok)
        self.assertEqual(result.missing_in_package, ["missing_in_right.json"])
        self.assertEqual(result.missing_in_tests, ["missing_in_left.json"])
        self.assertEqual(result.mismatched, ["different.json"])

    def test_cassette_redaction_removes_query_and_json_secrets(self):
        payload = {
            "url": "https://api.keepa.com/product?key=SECRET&domain=1&token=TOKEN",
            "headers": {"Authorization": "Bearer SECRET"},
            "body": {"api_key": "SECRET", "nested": [{"token": "TOKEN"}, {"safe": "value"}]},
        }

        redacted = redact_cassette_payload(payload)

        self.assertEqual(redacted["url"], "https://api.keepa.com/product?key=%5BREDACTED%5D&domain=1&token=%5BREDACTED%5D")
        self.assertEqual(redacted["headers"]["Authorization"], "[REDACTED]")
        self.assertEqual(redacted["body"]["api_key"], "[REDACTED]")
        self.assertEqual(redacted["body"]["nested"][0]["token"], "[REDACTED]")
        self.assertEqual(redacted["body"]["nested"][1]["safe"], "value")

    def test_cassette_redaction_round_trips_json_payload(self):
        payload = [{"request": {"url": "https://api.keepa.com/token?key=SECRET"}}]
        redacted = redact_cassette_payload(json.loads(json.dumps(payload)))

        self.assertEqual(redacted[0]["request"]["url"], "https://api.keepa.com/token?key=%5BREDACTED%5D")


if __name__ == "__main__":
    unittest.main()
