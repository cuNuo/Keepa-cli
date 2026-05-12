"""
tests/test_service_commands.py
文件说明：验证 Agent-safe command service 的正式业务命令。
主要职责：覆盖 products/categories 的 dry-run、fixture/offline 和预算信息流。
依赖边界：不访问真实 Keepa API，只使用测试 fixture。
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keepa_cli.service import run_command


FIXTURES = Path("tests/fixtures")


class ServiceCommandTests(unittest.TestCase):
    def test_docs_commands_expose_zread_resources(self):
        index = run_command("docs.index", env={})
        self.assertTrue(index["ok"])
        self.assertEqual(index["data"]["stable_entrypoints"]["zread_current"], "keepa://zread/wiki/current")
        self.assertEqual(index["data"]["stable_entrypoints"]["risk_taxonomy_schema"], "keepa://schema/risk-taxonomy")
        self.assertEqual(index["data"]["stable_entrypoints"]["workflow_runtime_schema"], "keepa://schema/workflow-runtime-contract")
        self.assertIn("keepa://schema/risk-taxonomy", index["data"]["recommended_read_order"])
        self.assertIn("keepa://schema/workflow-runtime-contract", index["data"]["recommended_read_order"])
        resource_uris = {item["uri"] for item in index["data"]["resources"]}
        self.assertIn("keepa://context/policy", resource_uris)
        self.assertIn("keepa://schema/risk-taxonomy", resource_uris)
        self.assertIn("keepa://schema/workflow-runtime-contract", resource_uris)

        current = run_command("docs.read", {"uri": "keepa://zread/wiki/current"}, env={})
        self.assertTrue(current["ok"])
        self.assertEqual(current["data"]["json"]["version"], "2026-05-10-215740")

        runtime_schema = run_command("docs.read", {"uri": "keepa://schema/workflow-runtime-contract"}, env={})
        self.assertTrue(runtime_schema["ok"])
        self.assertEqual(runtime_schema["data"]["json"]["$id"], "keepa://schema/workflow-runtime-contract")

        risk_schema = run_command("docs.read", {"uri": "keepa://schema/risk-taxonomy"}, env={})
        self.assertTrue(risk_schema["ok"])
        self.assertEqual(risk_schema["data"]["json"]["$id"], "keepa://schema/risk-taxonomy")
        self.assertIn("price_unstable", risk_schema["data"]["json"]["$defs"]["risk_code"]["enum"])

        page = run_command("docs.read", {"page": "1-gai-lan"}, env={})
        self.assertTrue(page["ok"])
        self.assertEqual(page["data"]["mime_type"], "text/markdown")
        self.assertIn("Keepa CLI", page["data"]["text"])

    def test_research_context_policy_and_resolution_are_local(self):
        policy = run_command("context.policy", env={})
        self.assertTrue(policy["ok"])
        self.assertEqual(policy["data"]["mode"], "live_read_allowed_for_real_research")
        self.assertTrue(policy["data"]["live_keepa"]["allowed_by_default"])
        self.assertIn("evidence/runtime-logs/", policy["data"]["roots"]["never_commit"])

        resolved = run_command("research.target.resolve", {"query": "B001GZ6QEC", "domain": "US"}, env={})
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["data"]["primary"]["type"], "asin")
        self.assertEqual(resolved["data"]["primary"]["id"], "B001GZ6QEC")
        self.assertEqual(resolved["data"]["next_actions"][0]["tool"], "products_get")

        context = run_command("research.context.query", {"target_type": "asin", "target_id": "B001GZ6QEC"}, env={})
        self.assertTrue(context["ok"])
        self.assertIn("keepa://asin/B001GZ6QEC/fixture", context["data"]["recommended_read_order"])

        workflow_context = run_command("research.context.query", {"question": "mcp workflow runtime schema"}, env={})
        self.assertTrue(workflow_context["ok"])
        self.assertIn("keepa://workflow/runtime-contract", workflow_context["data"]["recommended_read_order"])
        self.assertIn("keepa://schema/workflow-runtime-contract", workflow_context["data"]["recommended_read_order"])

        risk_context = run_command("research.context.query", {"question": "risk taxonomy schema for agent"}, env={})
        self.assertTrue(risk_context["ok"])
        self.assertIn("keepa://schema/risk-taxonomy", risk_context["data"]["recommended_read_order"])

    def test_research_brief_export_summarizes_local_payloads(self):
        payload = run_command(
            "research_brief.export",
            {
                "input": ["tests/fixtures/agent_eval_category_search_output.json", "tests/fixtures/agent_eval_seller_output.json"],
                "title": "fixture research brief",
            },
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "research_brief.export")
        brief = payload["data"]["brief"]
        self.assertEqual(brief["view"], "research_brief_export")
        self.assertGreaterEqual(brief["input_summary"]["research_graph_count"], 2)
        self.assertIn("decision_summary", brief["recommended_read_order"])
        self.assertIn("entity_graph_summary", brief["data_quality"]["present"])

    def test_products_get_builds_official_product_request_with_fixture(self):
        payload = run_command(
            "products.get",
            {
                "asin": ["B001GZ6QEC"],
                "domain": "US",
                "history": "0",
                "fixture": "product_B001GZ6QEC.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "products.get")
        self.assertEqual(payload["request"]["endpoint"], "/product")
        self.assertEqual(payload["request"]["params_redacted"]["domain"], "1")
        self.assertEqual(payload["request"]["params_redacted"]["asin"], "B001GZ6QEC")
        self.assertEqual(payload["request"]["params_redacted"]["history"], "0")
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 1)
        self.assertEqual(payload["data"]["body"]["products"][0]["asin"], "B001GZ6QEC")

    def test_products_get_full_preset_requests_low_cost_complete_fields(self):
        payload = run_command(
            "products.get",
            {"asin": ["B001GZ6QEC"], "domain": "US", "full": True, "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        params = payload["request"]["params_redacted"]
        self.assertEqual(params["history"], "1")
        self.assertEqual(params["stats"], "0")
        self.assertEqual(params["videos"], "1")
        self.assertEqual(params["aplus"], "1")
        self.assertNotIn("rating", params)
        self.assertNotIn("offers", params)
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 1)

    def test_products_get_full_preset_allows_custom_stats_and_temporal_windows(self):
        payload = run_command(
            "products.get",
            {
                "asin": ["B0TESTAGENT"],
                "domain": "US",
                "full": True,
                "stats_window": "365",
                "fixture": "product_agent_view_B0TEST.json",
                "agent_view": True,
                "temporal_windows": ["30,180", "365"],
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["params_redacted"]["stats"], "365")
        temporal = payload["data"]["products"][0]["temporal_features"]
        self.assertEqual(temporal["windows_days"], [30, 180, 365])
        new_features = temporal["series"]["new"]
        self.assertIn("recent_180d", new_features["windows"])
        self.assertIn("dispersion", new_features)
        self.assertIn("change_profile", new_features)
        self.assertIn("shape", new_features)

    def test_products_get_rejects_asin_and_code_together(self):
        payload = run_command(
            "products.get",
            {"asin": ["B001GZ6QEC"], "code": ["9780786222728"], "domain": "US", "dry_run": True},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "invalid_argument")

    def test_products_get_can_write_large_body_output(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "product.json"
            payload = run_command(
                "products.get",
                {
                    "asin": ["B001GZ6QEC"],
                    "domain": "US",
                    "fixture": "product_B001GZ6QEC.json",
                    "out": str(out_path),
                },
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            self.assertTrue(out_path.is_file())
            self.assertEqual(payload["data"]["output"]["path"], str(out_path))
            self.assertEqual(payload["data"]["output"]["result_count"], 1)

    def test_products_get_agent_view_summarizes_large_product_fields(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "raw-product.json"
            payload = run_command(
                "products.get",
                {
                    "asin": ["B0TESTAGENT"],
                    "domain": "US",
                    "fixture": "product_agent_view_B0TEST.json",
                    "agent_view": True,
                    "history_limit": 2,
                    "out": str(out_path),
                },
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            data = payload["data"]
            product = data["products"][0]
            self.assertEqual(data["view"], "agent_product")
            self.assertEqual(data["product_count"], 1)
            self.assertNotIn("body", data)
            self.assertTrue(out_path.is_file())
            self.assertEqual(data["raw"]["output"]["path"], str(out_path))
            self.assertEqual(data["raw"]["output"]["result_count"], 1)
            self.assertEqual(product["identity"]["asin"], "B0TESTAGENT")
            self.assertEqual(product["pricing"]["current"]["new"]["amount"], 14.99)
            self.assertEqual(product["pricing"]["buy_box"]["seller_id"], "A1FIXTURE")
            self.assertEqual(product["demand"]["monthly_sold"], 100000)
            self.assertEqual(product["rating"]["rating"]["value"], 4.3)
            self.assertEqual(product["rating"]["review_count"]["value"], 11598)
            self.assertEqual(product["offers"]["total_offer_count"], 6)
            self.assertEqual(product["media"]["video_count"], 1)
            self.assertEqual(product["aplus"]["module_count"], 1)
            new_history = product["history_summary"]["series"]["new"]
            self.assertEqual(new_history["point_count"], 3)
            self.assertEqual(len(new_history["last_points"]), 2)
            self.assertEqual(new_history["omitted_points"], 1)
            new_features = product["temporal_features"]["series"]["new"]
            self.assertEqual(new_features["latest_value"], 13.99)
            self.assertEqual(new_features["change_abs"], -2.0)
            self.assertEqual(new_features["trend_direction"], "down")
            self.assertEqual(new_features["recent_30d"]["change_pct"], -12.5078)
            self.assertEqual(product["selection_signals"]["price_stability"]["new_price_trend"], "down")
            self.assertEqual(product["agent_brief"]["key_facts"]["asin"], "B0TESTAGENT")
            self.assertIn("evidence_index", product["agent_brief"]["read_order"])
            self.assertEqual(product["agent_brief"]["temporal_takeaways"][0]["series"], "new")
            self.assertEqual(product["agent_brief"]["decision_context"]["demand"]["monthly_sold"], 100000)
            self.assertEqual(product["agent_brief"]["temporal_takeaways"][0]["windows"]["recent_30d"]["change_pct"], -12.5078)
            self.assertEqual(product["agent_brief"]["temporal_takeaways"][0]["volatility"]["mad"], 1.0)
            self.assertEqual(product["agent_brief"]["temporal_takeaways"][0]["momentum"]["down_steps"], 2)
            self.assertEqual(product["agent_brief"]["temporal_takeaways"][0]["shape"]["max_drawdown_abs"], -2.0)
            self.assertEqual(list(product["agent_brief"]["temporal_by_window"].keys())[0], "recent_7d")
            window_30d = product["agent_brief"]["temporal_by_window"]["recent_30d"]
            self.assertEqual(window_30d["series"]["new"]["change_pct"], -12.5078)
            self.assertTrue(window_30d["signal_summary"]["rank_improved"])
            self.assertIn("offers.offers", product["agent_brief"]["missing_data"])
            self.assertEqual(product["evidence_index"]["temporal_features"]["path"], "temporal_features")
            self.assertTrue(product["raw_field_presence"]["csv"])

    def test_products_get_agent_view_supports_profiles_fields_and_chunks(self):
        with TemporaryDirectory() as temp_dir:
            chunks_dir = Path(temp_dir) / "chunks"
            payload = run_command(
                "products.get",
                {
                    "asin": ["B0TESTAGENT"],
                    "domain": "US",
                    "fixture": "product_agent_view_B0TEST.json",
                    "agent_view": True,
                    "view": "summary",
                    "fields": "agent_brief,identity,pricing,data_quality,next_actions,selection_signals,temporal_features,evidence_index",
                    "chunks_dir": str(chunks_dir),
                },
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            data = payload["data"]
            product = data["products"][0]
            self.assertEqual(data["profile"], "summary")
            self.assertIn("identity", product)
            self.assertIn("pricing", product)
            self.assertIn("data_quality", product)
            self.assertIn("selection_signals", product)
            self.assertIn("temporal_features", product)
            self.assertIn("agent_brief", product)
            self.assertIn("evidence_index", product)
            self.assertNotIn("history_summary", product)
            self.assertIn("offers.offers", product["data_quality"]["missing"])
            self.assertTrue(product["next_actions"])
            self.assertEqual(product["next_actions"][0]["estimated_tokens"], 13)
            self.assertTrue(any(item["name"] == "identity" for item in data["chunks"]))
            self.assertTrue(any(item["name"] == "agent_brief" for item in data["chunks"]))
            self.assertTrue(any(item["name"] == "evidence_index" for item in data["chunks"]))
            self.assertTrue((chunks_dir / "B0TESTAGENT-identity.json").is_file())
            self.assertTrue((chunks_dir / "B0TESTAGENT-agent_brief.json").is_file())

    def test_products_compare_returns_agent_safe_rows(self):
        payload = run_command(
            "products.compare",
            {
                "asin": ["B0TESTAGENT"],
                "domain": "US",
                "fixture": "product_agent_view_B0TEST.json",
                "full": True,
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "products.compare")
        row = payload["data"]["rows"][0]
        self.assertEqual(row["asin"], "B0TESTAGENT")
        self.assertEqual(row["new_price"], 14.99)
        self.assertEqual(row["monthly_sold"], 100000)
        self.assertIn("selection_signals", row)

    def test_products_compare_can_keep_bounded_history_points(self):
        payload = run_command(
            "products.compare",
            {
                "asin": ["B0TESTAGENT"],
                "domain": "US",
                "fixture": "product_agent_view_B0TEST.json",
                "full": True,
                "history_limit": 2,
                "keep_history_points": True,
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        row = payload["data"]["rows"][0]
        self.assertTrue(payload["data"]["source_view"]["history_points_retained"])
        self.assertIn("bounded_history_points", row)
        self.assertLessEqual(len(row["bounded_history_points"]["series"]["new"]["last_points"]), 2)

    def test_products_compare_real_full_history_fixture_retains_multiple_asin_points(self):
        payload = run_command(
            "products.compare",
            {
                "asin": ["B0D8W1YVBX", "B0F7XPYCSJ"],
                "domain": "US",
                "fixture": "products_multi_asin_full_history_sanitized.json",
                "full": True,
                "history_limit": 80,
                "keep_history_points": True,
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        rows = payload["data"]["rows"]
        self.assertEqual([row["asin"] for row in rows], ["B0D8W1YVBX", "B0F7XPYCSJ"])
        for row in rows:
            bounded = row["bounded_history_points"]["series"]
            self.assertIn("new", bounded)
            self.assertIn("sales_rank", bounded)
            self.assertGreaterEqual(len(bounded["new"]["last_points"]), 2)
        self.assertTrue(payload["data"]["source_view"]["history_points_retained"])

    def test_categories_get_uses_category_endpoint_and_parents_flag(self):
        payload = run_command(
            "categories.get",
            {"category": ["0"], "domain": "US", "parents": True, "fixture": "category_roots_US.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/category")
        self.assertEqual(payload["request"]["params_redacted"]["category"], "0")
        self.assertEqual(payload["request"]["params_redacted"]["parents"], "1")
        self.assertEqual(payload["token_bucket"]["estimated"]["estimated_tokens"], 1)
        self.assertIn("172282", payload["data"]["body"]["categories"])

    def test_categories_search_uses_official_search_type_category(self):
        payload = run_command(
            "categories.search",
            {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["request"]["endpoint"], "/search")
        self.assertEqual(payload["request"]["params_redacted"]["type"], "category")
        self.assertEqual(payload["request"]["params_redacted"]["term"], "home kitchen")
        self.assertIn("1055398", payload["data"]["body"]["categories"])

    def test_history_export_expands_product_csv_fixture(self):
        payload = run_command(
            "history.export",
            {
                "asin": "B001GZ6QEC",
                "domain": "US",
                "series": "amazon,new",
                "format": "json",
                "fixture": "product_history_B001GZ6QEC.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "history.export")
        self.assertEqual(payload["request"]["endpoint"], "/product")
        self.assertEqual(payload["request"]["params_redacted"]["history"], "1")
        self.assertEqual(payload["data"]["row_count"], 6)
        self.assertEqual(payload["data"]["fields"][0], "asin")
        self.assertEqual(payload["data"]["rows"][0]["series"], "amazon")

    def test_history_trend_returns_analysis_summary(self):
        payload = run_command(
            "history.trend",
            {
                "asin": "B001GZ6QEC",
                "domain": "US",
                "series": "amazon",
                "window_days": [30, 90],
                "fixture": "product_history_B001GZ6QEC.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertTrue(payload["ok"])
        summary = payload["data"]["analysis"]["series"]["amazon"]["all_time"]
        self.assertEqual(summary["points"], 3)
        self.assertEqual(summary["latest"]["value"], 10.99)
        self.assertEqual(summary["change"]["absolute"], -2.0)

    def test_history_export_reports_missing_csv_field(self):
        payload = run_command(
            "history.export",
            {
                "asin": "B001GZ6QEC",
                "domain": "US",
                "fixture": "product_B001GZ6QEC.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "history_unavailable")

    def test_history_export_reports_empty_series(self):
        payload = run_command(
            "history.export",
            {
                "asin": "B001GZ6QEC",
                "domain": "US",
                "series": "amazon",
                "fixture": "product_history_empty_B001GZ6QEC.json",
            },
            fixture_dir=FIXTURES,
            env={},
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "history_empty")

    def test_history_export_can_write_csv_file(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "history.csv"
            payload = run_command(
                "history.export",
                {
                    "asin": "B001GZ6QEC",
                    "domain": "US",
                    "series": "amazon",
                    "format": "csv",
                    "out": str(out_path),
                    "fixture": "product_history_B001GZ6QEC.json",
                },
                fixture_dir=FIXTURES,
                env={},
            )

            self.assertTrue(payload["ok"])
            self.assertTrue(out_path.is_file())
            self.assertEqual(payload["data"]["output"]["row_count"], 3)
            self.assertEqual(payload["data"]["output"]["path"], str(out_path))


if __name__ == "__main__":
    unittest.main()
