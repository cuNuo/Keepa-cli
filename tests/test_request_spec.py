"""
tests/test_request_spec.py
文件说明：验证 Keepa API dry-run 请求规格。
主要职责：确保 method、endpoint、dry_run 和 params_redacted 字段稳定。
依赖边界：不执行网络请求，只测试请求描述构建。
"""

import unittest

from keepa_cli.request_spec import build_request_spec


class RequestSpecTests(unittest.TestCase):
    def test_builds_dry_run_get_request_without_secret_key(self):
        spec = build_request_spec(
            method="GET",
            path="/product",
            params={"domain": "1", "asin": "B001GZ6QEC", "key": "SECRET123"},
            dry_run=True,
        )

        as_dict = spec.to_dict()
        self.assertEqual(as_dict["method"], "GET")
        self.assertEqual(as_dict["endpoint"], "/product")
        self.assertTrue(as_dict["dry_run"])
        self.assertNotIn("SECRET123", str(as_dict))
        self.assertEqual(as_dict["params_redacted"]["key"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
