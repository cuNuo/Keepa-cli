"""
tests/test_stdio.py
文件说明：验证 Agent stdio JSON Lines 协议。
主要职责：覆盖 doctor 事件流和高成本请求 confirmation_required。
依赖边界：直接调用协议处理函数，不启动真实子进程或访问网络。
"""

import json
import unittest

from keepa_cli.agent.stdio import handle_stdio_message


class StdioProtocolTests(unittest.TestCase):
    def test_doctor_message_returns_json_line_events(self):
        raw = json.dumps({"id": "1", "method": "doctor", "params": {}})
        events = handle_stdio_message(raw, env={})

        self.assertEqual(events[0]["id"], "1")
        self.assertEqual(events[0]["event"], "started")
        self.assertEqual(events[-1]["event"], "done")
        self.assertTrue(any(event.get("event") == "response" for event in events))

    def test_high_cost_message_returns_confirmation_required(self):
        raw = json.dumps(
            {
                "id": "2",
                "method": "bestsellers.get",
                "params": {"domain": "US", "category": "123"},
            }
        )
        events = handle_stdio_message(raw, env={})
        response = next(event for event in events if event["event"] == "response")

        self.assertFalse(response["payload"]["ok"])
        self.assertEqual(response["payload"]["error"]["kind"], "confirmation_required")

    def test_products_get_message_uses_fixture_service_path(self):
        raw = json.dumps(
            {
                "id": "3",
                "method": "products.get",
                "params": {
                    "asin": ["B001GZ6QEC"],
                    "domain": "US",
                    "history": "0",
                    "fixture": "product_B001GZ6QEC.json",
                },
            }
        )
        events = handle_stdio_message(raw, env={})
        response = next(event for event in events if event["event"] == "response")

        self.assertTrue(response["payload"]["ok"])
        self.assertEqual(response["payload"]["request"]["endpoint"], "/product")
        self.assertEqual(response["payload"]["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")


if __name__ == "__main__":
    unittest.main()
