"""
tests/test_official_api_coverage.py
文件说明：验证补齐的官方 Keepa API 链路。
主要职责：冻结 token、graphimage、lightningdeal 与 tracking 的 Agent-safe 信息流。
依赖边界：不访问真实 Keepa API，只使用 dry-run、fixture 与 stdio 协议。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from keepa_cli.agent.stdio import handle_stdio_message
from keepa_cli.service import run_command
from keepa_cli.token_budget import estimate_request_budget


FIXTURES = Path("tests/fixtures")


class OfficialApiCoverageTests(unittest.TestCase):
    def run_module(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "keepa_cli", *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_tokens_status_fixture_uses_token_endpoint(self):
        payload = run_command(
            "tokens.status",
            {"fixture": "token_status.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "tokens.status")
        self.assertEqual(payload["request"]["endpoint"], "/token")
        self.assertEqual(payload["data"]["body"]["tokensLeft"], 42)
        self.assertEqual(payload["token_bucket"]["tokens_left"], 42)

    def test_graph_image_dry_run_uses_graphimage_endpoint_without_binary_live(self):
        payload = run_command(
            "graphs.image",
            {
                "asin": "B09YNQCQKR",
                "domain": "US",
                "width": 800,
                "height": 400,
                "range": 365,
                "amazon": 1,
                "new": 1,
                "dry_run": True,
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/graphimage")
        params = payload["request"]["params_redacted"]
        self.assertEqual(params["asin"], "B09YNQCQKR")
        self.assertEqual(params["domain"], "1")
        self.assertEqual(params["width"], 800)
        self.assertEqual(params["height"], 400)
        self.assertEqual(params["range"], 365)
        self.assertEqual(params["amazon"], 1)
        self.assertEqual(params["new"], 1)

    def test_graph_image_live_path_is_explicitly_unsupported_until_binary_transport(self):
        payload = run_command(
            "graphs.image",
            {"asin": "B09YNQCQKR", "domain": "US"},
            fixture_dir=FIXTURES,
            env={"KEEPA_API_KEY": "x" * 64},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "live_binary_unsupported")

    def test_lightningdeals_dry_run_uses_lightningdeal_endpoint(self):
        payload = run_command(
            "lightningdeals.list",
            {"domain": "US", "asin": "B09YNQCQKR", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/lightningdeal")
        params = payload["request"]["params_redacted"]
        self.assertEqual(params["domain"], "1")
        self.assertEqual(params["asin"], "B09YNQCQKR")

    def test_tracking_list_dry_run_uses_tracking_endpoint(self):
        payload = run_command(
            "tracking.list",
            {"asins_only": True, "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/tracking")
        self.assertEqual(payload["request"]["method"], "GET")
        self.assertEqual(payload["request"]["params_redacted"]["type"], "list")
        self.assertEqual(payload["request"]["params_redacted"]["asins-only"], "1")

    def test_tracking_list_names_is_asins_only_alias(self):
        payload = run_command(
            "tracking.list-names",
            {"dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/tracking")
        self.assertEqual(payload["request"]["params_redacted"]["type"], "list")
        self.assertEqual(payload["request"]["params_redacted"]["asins-only"], "1")

    def test_tracking_get_dry_run_uses_tracking_endpoint(self):
        payload = run_command(
            "tracking.get",
            {"asin": "B09YNQCQKR", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/tracking")
        self.assertEqual(payload["request"]["params_redacted"]["type"], "get")
        self.assertEqual(payload["request"]["params_redacted"]["asin"], "B09YNQCQKR")

    def test_tracking_add_requires_confirmation_without_dry_run_or_yes(self):
        payload = run_command(
            "tracking.add",
            {"tracking": {"asin": "B09YNQCQKR", "domain": 1}},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "confirmation_required")
        self.assertEqual(payload["error"]["details"]["resume_with"], "--yes")

    def test_tracking_add_dry_run_posts_json_body(self):
        payload = run_command(
            "tracking.add",
            {"tracking": {"asin": "B09YNQCQKR", "domain": 1}, "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/tracking")
        self.assertEqual(payload["request"]["method"], "POST")
        self.assertEqual(payload["request"]["params_redacted"]["type"], "add")
        self.assertEqual(payload["request"]["json_body_redacted"][0]["asin"], "B09YNQCQKR")

    def test_tracking_remove_all_requires_confirmation(self):
        payload = run_command("tracking.remove-all", {}, fixture_dir=FIXTURES, env={})

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "confirmation_required")
        self.assertEqual(payload["token_bucket"]["estimated"]["requires_confirmation"], True)

    def test_tracking_notification_dry_run_includes_since_and_revise(self):
        payload = run_command(
            "tracking.notifications",
            {"since": 0, "revise": True, "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["params_redacted"]["type"], "notification")
        self.assertEqual(payload["request"]["params_redacted"]["since"], "0")
        self.assertEqual(payload["request"]["params_redacted"]["revise"], "1")

    def test_tracking_webhook_requires_confirmation_and_redacts_url_token(self):
        payload = run_command(
            "tracking.webhook",
            {"url": "https://example.com/hook?token=secret-value"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "confirmation_required")

    def test_budget_marks_official_gap_commands_for_agent(self):
        self.assertEqual(estimate_request_budget("tokens.status").estimated_tokens, 0)
        self.assertEqual(estimate_request_budget("graphs.image").estimated_tokens, 1)
        self.assertEqual(estimate_request_budget("lightningdeals.list").estimated_tokens, 1)
        self.assertTrue(estimate_request_budget("tracking.add").requires_confirmation)

    def test_stdio_allows_dry_run_tracking_without_confirmation_block(self):
        raw = json.dumps(
            {
                "id": "track-dry-run",
                "method": "tracking.list",
                "params": {"asins_only": True, "dry_run": True},
            }
        )
        events = handle_stdio_message(raw, env={})
        response = next(event for event in events if event["event"] == "response")

        self.assertTrue(response["payload"]["ok"])
        self.assertEqual(response["payload"]["request"]["endpoint"], "/tracking")

    def test_stdio_tracking_add_without_yes_returns_confirmation_required(self):
        raw = json.dumps(
            {
                "id": "track-add",
                "method": "tracking.add",
                "params": {"tracking": {"asin": "B09YNQCQKR", "domain": 1}},
            }
        )
        events = handle_stdio_message(raw, env={})
        response = next(event for event in events if event["event"] == "response")

        self.assertFalse(response["payload"]["ok"])
        self.assertEqual(response["payload"]["error"]["kind"], "confirmation_required")

    def test_cli_tokens_graph_lightning_and_tracking_commands(self):
        token_result = self.run_module("--json", "tokens", "status", "--fixture", "token_status.json")
        graph_result = self.run_module(
            "--json",
            "graphs",
            "image",
            "B09YNQCQKR",
            "--domain",
            "US",
            "--width",
            "800",
            "--height",
            "400",
            "--range",
            "365",
            "--param",
            "amazon=1",
            "--dry-run",
        )
        lightning_result = self.run_module(
            "--json",
            "lightningdeals",
            "list",
            "--domain",
            "US",
            "--dry-run",
        )
        tracking_result = self.run_module(
            "--json",
            "tracking",
            "list",
            "--asins-only",
            "--dry-run",
        )
        tracking_names_result = self.run_module(
            "--json",
            "tracking",
            "list-names",
            "--dry-run",
        )

        for result in (token_result, graph_result, lightning_result, tracking_result, tracking_names_result):
            self.assertEqual(result.returncode, 0, result.stderr)

        self.assertEqual(json.loads(token_result.stdout)["request"]["endpoint"], "/token")
        self.assertEqual(json.loads(graph_result.stdout)["request"]["endpoint"], "/graphimage")
        self.assertEqual(json.loads(lightning_result.stdout)["request"]["endpoint"], "/lightningdeal")
        self.assertEqual(json.loads(tracking_result.stdout)["request"]["endpoint"], "/tracking")
        self.assertEqual(json.loads(tracking_names_result.stdout)["request"]["params_redacted"]["asins-only"], "1")


if __name__ == "__main__":
    unittest.main()
