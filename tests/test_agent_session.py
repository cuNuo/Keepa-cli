"""
tests/test_agent_session.py
文件说明：验证 AgentSession 的 cache key、去重与 token ledger。
主要职责：确保 stdio/MCP 共享的会话状态可审计、可复用、不重复累计消耗。
依赖边界：使用 fake runner，不访问真实 Keepa API。
"""

import unittest

from keepa_cli.agent.session import AgentSession, build_cache_key


class AgentSessionTests(unittest.TestCase):
    def test_cache_key_is_stable_and_excludes_runtime_flags(self):
        left = build_cache_key("products.get", {"asin": ["B001"], "domain": "US", "yes": True})
        right = build_cache_key("products.get", {"domain": "US", "asin": ["B001"]})

        self.assertEqual(left, right)
        self.assertTrue(left.startswith("products.get:"))

    def test_repeated_successful_call_hits_cache_without_extra_consumed_tokens(self):
        calls = []

        def runner(command, params):
            calls.append((command, dict(params)))
            return {
                "ok": True,
                "command": command,
                "request": {},
                "token_bucket": {"estimated": {"estimated_tokens": 1}, "tokens_consumed": 1},
                "data": {"value": "fresh"},
            }

        session = AgentSession(env={}, runner=runner)
        first = session.execute("products.get", {"asin": ["B001"], "fixture": "product_B001GZ6QEC.json"})
        second = session.execute("products.get", {"asin": ["B001"], "fixture": "product_B001GZ6QEC.json"})

        self.assertEqual(len(calls), 1)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["cache_key"], first["cache_key"])
        self.assertEqual(second["budget_ledger"]["session_estimated"], 1)
        self.assertEqual(second["budget_ledger"]["session_consumed"], 1)
        self.assertEqual(second["budget_ledger"]["cache_hits"], 1)

    def test_from_cache_reuses_known_key(self):
        session = AgentSession(
            env={},
            runner=lambda command, params: {
                "ok": True,
                "command": command,
                "request": {},
                "token_bucket": {"estimated": {"estimated_tokens": 1}},
                "data": {"value": "cached"},
            },
        )
        first = session.execute("products.get", {"asin": ["B001"], "fixture": "product_B001GZ6QEC.json"})
        second = session.execute("products.get", {"from_cache": first["cache_key"]})

        self.assertTrue(second["ok"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["data"]["value"], "cached")

    def test_confirmation_required_updates_blocked_actions(self):
        session = AgentSession(env={})
        payload = session.execute("categories.products", {"category": "172282", "domain": "US"})

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "confirmation_required")
        self.assertEqual(payload["budget_ledger"]["session_estimated"], 50)
        self.assertEqual(payload["budget_ledger"]["blocked_actions"][0]["command"], "categories.products")

    def test_remaining_limit_tracks_estimated_budget(self):
        session = AgentSession(
            env={},
            max_tokens=5,
            runner=lambda command, params: {
                "ok": True,
                "command": command,
                "request": {},
                "token_bucket": {"estimated": {"estimated_tokens": 1}},
                "data": {},
            },
        )
        payload = session.execute("products.get", {"asin": ["B001"], "fixture": "product_B001GZ6QEC.json"})

        self.assertEqual(payload["budget_ledger"]["remaining_limit"], 4)


if __name__ == "__main__":
    unittest.main()
