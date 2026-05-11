"""
tests/test_backend_branch_coverage.py
文件说明：补齐后端控制面和真实请求保护分支覆盖。
主要职责：验证参数错误、确认阻断、MCP/stdio 错误协议和会话缓存边界。
依赖边界：只使用 dry-run、fixture、临时目录和 fake payload，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from keepa_cli.agent.mcp import handle_mcp_message, iter_mcp_output, iter_mcp_stream
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.stdio import handle_stdio_message, iter_stdio_output
from keepa_cli.commands.categories import category_search_view, handle_category_command, hydrate_category_products
from keepa_cli.commands.products import handle_product_command
from keepa_cli.commands.tracking import handle_tracking_command, redact_url_query_secrets, sanitize_webhook_payload, tracking_body
from keepa_cli.service import run_command


FIXTURES = Path("tests/fixtures")


class BackendBranchCoverageTests(unittest.TestCase):
    def test_service_core_routes_and_invalid_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            cassette = Path(temp_dir) / "cassette.json"
            cassette.write_text(
                json.dumps(
                    {
                        "request": {"url": "https://api.keepa.com/product?key=SECRET"},
                        "response": {"body": {"products": [{"asin": "B001GZ6QEC"}]}},
                    }
                ),
                encoding="utf-8",
            )
            out = Path(temp_dir) / "redacted.json"

            self.assertTrue(run_command("domains.list", env={})["ok"])
            self.assertTrue(run_command("config.show", {"path": str(config_path)}, env={})["ok"])
            self.assertTrue(run_command("config.init", {"path": str(config_path), "dry_run": True}, env={})["ok"])
            self.assertTrue(run_command("config.set-language", {"path": str(config_path), "language": "zh", "dry_run": True}, env={})["ok"])
            self.assertTrue(run_command("request.get", {"path": "/product", "dry_run": True}, fixture_dir=FIXTURES, env={})["ok"])

            graph_missing = run_command("graphs.image", {"domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={})
            seller_missing = run_command("sellers.get", {"domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={})
            bestsellers_missing = run_command("bestsellers.get", {"domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={})
            cassette_missing = run_command("cassettes.sanitize", {"input": str(cassette)}, env={})
            promoted_missing = run_command("cassettes.promote", {"input": str(cassette)}, env={})
            promoted_verify_missing = run_command("cassettes.promote_and_verify", {"input": str(cassette)}, env={})

            self.assertEqual(graph_missing["error"]["kind"], "invalid_argument")
            self.assertEqual(seller_missing["error"]["kind"], "invalid_argument")
            self.assertEqual(bestsellers_missing["error"]["kind"], "invalid_argument")
            self.assertEqual(cassette_missing["error"]["kind"], "invalid_argument")
            self.assertEqual(promoted_missing["error"]["kind"], "invalid_argument")
            self.assertEqual(promoted_verify_missing["error"]["kind"], "invalid_argument")

            sanitized = run_command("cassettes.sanitize", {"input": str(cassette), "out": str(out)}, env={})
            self.assertTrue(sanitized["ok"])
            self.assertNotIn("SECRET", out.read_text(encoding="utf-8"))

            dry_verify = run_command(
                "cassettes.promote_and_verify",
                {
                    "input": str(cassette),
                    "name": "branch_dry_run_fixture",
                    "tests_dir": str(Path(temp_dir) / "tests-fixtures"),
                    "package_dir": str(Path(temp_dir) / "package-fixtures"),
                    "manifest": str(Path(temp_dir) / "manifest.csv"),
                    "dry_run": True,
                    "run_eval": True,
                },
                env={},
            )
            self.assertTrue(dry_verify["ok"])
            self.assertEqual(dry_verify["data"]["fixture_sync"]["skipped"], "dry_run")
            self.assertEqual(dry_verify["data"]["agent_eval"]["skipped"], "dry_run")

            bad_json = Path(temp_dir) / "bad.json"
            bad_json.write_text("{", encoding="utf-8")
            invalid = run_command("research_graph.merge", {"input": str(bad_json)}, env={})
            self.assertFalse(invalid["ok"])
            self.assertEqual(invalid["error"]["kind"], "invalid_argument")

    def test_product_category_and_tracking_error_branches(self) -> None:
        cases = [
            run_command("products.compare", {"domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("products.search", {"term": "   ", "domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("categories.get", {"domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command(
                "categories.get",
                {"categories": [str(index) for index in range(11)], "domain": "US", "dry_run": True},
                fixture_dir=FIXTURES,
                env={},
            ),
            run_command("categories.search", {"term": "", "domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("categories.finder-selection", {"domain": "US"}, fixture_dir=FIXTURES, env={}),
            run_command("categories.products", {"domain": "US", "dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("categories.products", {"category": "172282", "hydrate_top": -1, "dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("tracking.get", {"dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("tracking.remove", {"dry_run": True}, fixture_dir=FIXTURES, env={}),
            run_command("tracking.webhook", {"dry_run": True}, fixture_dir=FIXTURES, env={}),
        ]

        for payload in cases:
            with self.subTest(command=payload["command"]):
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"]["kind"], "invalid_argument")

        confirmation = run_command("categories.products", {"category": "172282", "domain": "US"}, fixture_dir=FIXTURES, env={})
        self.assertFalse(confirmation["ok"])
        self.assertEqual(confirmation["error"]["kind"], "confirmation_required")

        product_code = run_command(
            "products.get",
            {"code": ["9780786222728"], "domain": "US", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )
        product_search = run_command(
            "products.search",
            {"term": "coffee grinder", "domain": "US", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )
        categories_dry = run_command(
            "categories.products",
            {"category": "172282", "domain": "US", "dry_run": True, "hydrate_top": 2},
            fixture_dir=FIXTURES,
            env={},
        )
        sellers_update = run_command(
            "sellers.get",
            {"seller": "A2L77EE7U53NWQ", "domain": "US", "update": 0, "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )
        topsellers_category = run_command(
            "topsellers.list",
            {"domain": "US", "category": "172282"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertEqual(product_code["request"]["params_redacted"]["code"], "9780786222728")
        self.assertEqual(product_search["request"]["params_redacted"]["type"], "product")
        self.assertTrue(categories_dry["ok"])
        self.assertEqual(categories_dry["data"]["hydration"]["reason"], "dry-run never hydrates products")
        self.assertEqual(len(categories_dry["data"]["next_actions"]), 2)
        self.assertEqual(sellers_update["request"]["params_redacted"]["update"], 0)
        self.assertEqual(topsellers_category["error"]["kind"], "confirmation_required")

    def test_command_helpers_cover_unusual_input_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tracking_file = Path(temp_dir) / "tracking.json"
            tracking_file.write_text(json.dumps([{"asin": "B001GZ6QEC"}, {"asin": "B09YNQCQKR"}]), encoding="utf-8")

            self.assertEqual(tracking_body({"tracking": {"asin": "B001GZ6QEC"}})[0]["asin"], "B001GZ6QEC")
            self.assertEqual(len(tracking_body({"tracking_file": str(tracking_file)})), 2)
            self.assertEqual(tracking_body({"tracking": '{"asin":"B001GZ6QEC"}'})[0]["asin"], "B001GZ6QEC")
            with self.assertRaises(ValueError):
                tracking_body({"tracking": ["not-object"]})
            with self.assertRaises(ValueError):
                tracking_body({"tracking_file": str(Path(temp_dir) / "missing.json")})

        redacted = redact_url_query_secrets("https://example.com/hook?token=secret&keep=ok")
        self.assertIn("token=%5BREDACTED%5D", redacted)
        self.assertIn("keep=ok", redacted)
        unchanged = {"data": {}}
        self.assertIs(sanitize_webhook_payload(unchanged), unchanged)
        payload = {"request": {"params_redacted": {"url": "https://example.com/hook?api_key=secret"}}}
        self.assertEqual(sanitize_webhook_payload(payload)["request"]["params_redacted"]["url"], "https://example.com/hook?api_key=%5BREDACTED%5D")

        search_view = category_search_view({"categories": {"bad": "skip", "1": {"catId": 1, "name": "Home", "matched": True}}}, term="home", domain="US")
        self.assertEqual(search_view["category_candidate_count"], 1)

        empty_hydration = hydrate_category_products([], hydrate_top=2, params={"domain": "US"}, fixture_dir=FIXTURES)
        self.assertTrue(empty_hydration["enabled"])
        self.assertEqual(empty_hydration["products"], [])

        with self.assertRaises(ValueError):
            handle_product_command("products.unknown", {}, fixture_dir=FIXTURES)
        with self.assertRaises(ValueError):
            handle_category_command("categories.unknown", {}, fixture_dir=FIXTURES)
        unsupported_tracking = handle_tracking_command("tracking.unknown", {}, fixture_dir=FIXTURES)
        self.assertFalse(unsupported_tracking["ok"])
        self.assertEqual(unsupported_tracking["error"]["kind"], "unsupported_command")

    def test_mcp_stdio_and_session_error_branches(self) -> None:
        parse_error = handle_mcp_message("{", env={})
        invalid_request = handle_mcp_message("[]", env={})
        invalid_params = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "bad", "method": "tools/list", "params": "bad"}), env={})
        initialized = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "note", "method": "notifications/initialized"}), env={})
        unknown_method = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "missing", "method": "missing"}), env={})
        unknown_resource = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "resource", "method": "resources/read", "params": {"uri": "keepa://missing"}}), env={})
        bad_prompt_args = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "prompt-args", "method": "prompts/get", "params": {"name": "keepa.product_research", "arguments": [1]}}), env={})
        unknown_prompt = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "prompt", "method": "prompts/get", "params": {"name": "missing"}}), env={})
        bad_tool_args = handle_mcp_message(json.dumps({"jsonrpc": "2.0", "id": "tool", "method": "tools/call", "params": {"name": "keepa.products_get", "arguments": [1]}}), env={})

        self.assertEqual(parse_error["error"]["code"], -32700)
        self.assertEqual(invalid_request["error"]["code"], -32600)
        self.assertEqual(invalid_params["error"]["code"], -32602)
        self.assertIsNone(initialized)
        self.assertEqual(unknown_method["error"]["code"], -32601)
        self.assertEqual(unknown_resource["error"]["code"], -32602)
        self.assertEqual(bad_prompt_args["error"]["code"], -32602)
        self.assertEqual(unknown_prompt["error"]["code"], -32602)
        self.assertEqual(bad_tool_args["error"]["code"], -32602)

        filtered = handle_mcp_message(
            json.dumps({"jsonrpc": "2.0", "id": "filter", "method": "tools/list", "params": {"allow_tools": "keepa.context_policy, keepa.products_get", "exclude_tools": 123}}),
            env={},
        )
        self.assertEqual(filtered["result"]["filters"]["allow_tools"], ["keepa.context_policy", "keepa.products_get"])
        self.assertEqual(filtered["result"]["filters"]["exclude_tools"], [])

        stdio_parse = handle_stdio_message("{", env={})
        stdio_bad_params = handle_stdio_message(json.dumps({"id": "bad", "method": "doctor", "params": []}), env={})
        stdio_lines = iter_stdio_output("\n{\"id\":\"1\",\"method\":\"doctor\",\"params\":{}}\n", env={})
        mcp_lines = iter_mcp_output("\n{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{}}\n", env={})
        stream_lines = list(iter_mcp_stream(["\n", "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"initialize\",\"params\":{}}"], env={}))

        self.assertEqual(stdio_parse[0]["payload"]["error"]["kind"], "invalid_json")
        self.assertEqual(stdio_bad_params[-2]["payload"]["command"], "doctor")
        self.assertTrue(stdio_lines)
        self.assertTrue(mcp_lines)
        self.assertTrue(stream_lines)

        session = AgentSession(runner=lambda command, params: {"ok": True, "command": command, "data": "not-a-dict", "token_bucket": {"tokens_consumed": "3"}})
        cache_miss = session.execute("doctor", {"from_cache": "missing"})
        payload = session.execute("doctor", {}, tool="keepa.doctor")
        cache_hit = session.execute("doctor", {}, tool="keepa.doctor")

        self.assertFalse(cache_miss["ok"])
        self.assertEqual(cache_miss["error"]["kind"], "cache_miss")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["budget_ledger"]["session_consumed"], 3)
        self.assertTrue(cache_hit["cache_hit"])


if __name__ == "__main__":
    unittest.main()
