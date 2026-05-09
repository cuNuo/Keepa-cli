"""
tests/test_envelope.py
文件说明：验证 Agent JSON envelope 的稳定结构。
主要职责：覆盖成功响应字段和错误响应中的凭据打码。
依赖边界：不调用 CLI 或网络，仅测试 envelope 纯函数。
"""

import json
import unittest

from keepa_cli.envelope import error_envelope, success_envelope


class EnvelopeTests(unittest.TestCase):
    def test_success_envelope_has_agent_stable_shape(self):
        payload = success_envelope(
            command="doctor",
            data={"auth": {"available": False}},
            request={"endpoint": "/status"},
            token_bucket={"tokens_left": None},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "doctor")
        self.assertIn("data", payload)
        self.assertIn("request", payload)
        self.assertIn("token_bucket", payload)
        json.dumps(payload)

    def test_error_envelope_redacts_secret_values(self):
        payload = error_envelope(
            command="request.get",
            kind="api_error",
            message="failed with key=SECRET123",
            status_code=402,
            details={"url": "https://api.keepa.com/product?key=SECRET123&domain=1"},
            secret_values=["SECRET123"],
        )

        encoded = json.dumps(payload)
        self.assertFalse(payload["ok"])
        self.assertNotIn("SECRET123", encoded)
        self.assertIn("[REDACTED]", encoded)


if __name__ == "__main__":
    unittest.main()
