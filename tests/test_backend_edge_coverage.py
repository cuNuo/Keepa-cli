"""
tests/test_backend_edge_coverage.py
文件说明：补齐后端 helper、防御分支和资源契约的边界覆盖。
主要职责：用离线合成数据覆盖图表、工作流解析、MCP 资源、研究图谱和命令族异常路径。
依赖边界：不访问真实 Keepa API，不读取真实凭据；真实请求相关路径仅用 dry-run、fixture 或 fake payload。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from keepa_cli.agent.cache_keys import _safe_for_cache_key
from keepa_cli.agent.prompts import get_mcp_prompt
from keepa_cli.agent.resources import path_to_resource_uri, read_mcp_resource, text_to_resource_token
from keepa_cli.agent.stdio import handle_stdio_message
from keepa_cli.agent.tools import get_tool_definition, resolve_toolset_groups, tool_params_to_command_params, validate_tool_arguments
from keepa_cli.agent.workflow_resolver import resolve_workflow_arguments
from keepa_cli.agent_eval import (
    _assert_next_actions_executable,
    _assert_spec,
    _resolve_path,
    check_agent_eval_fixtures,
)
from keepa_cli.analysis import analyze_history_rows, _round_value
from keepa_cli.cache import (
    SQLiteResponseCache,
    build_response_cache_key,
    default_cache_path,
    resolve_cache_ttl_seconds,
)
from keepa_cli.cassettes import _fixture_name, _redact_url, promote_cassette_fixture
from keepa_cli.client import KeepaClient
from keepa_cli.commands.cache import handle_cache_command
from keepa_cli.commands.categories import handle_category_command
from keepa_cli.commands.common import as_list, live_cache_options, optional_params
from keepa_cli.commands.deals import handle_deals_command
from keepa_cli.commands.docs import handle_docs_command
from keepa_cli.commands.finder import handle_finder_command
from keepa_cli.commands.history import _find_product, _history_rows_from_payload, _keepa_body_from_payload, handle_history_command
from keepa_cli.commands.tracking import handle_tracking_command, sanitize_webhook_payload, tracking_body
from keepa_cli.commands.workflows import handle_workflow_command
from keepa_cli.config import build_config_report, default_config_path, init_config, load_config
from keepa_cli.domains import resolve_domain
from keepa_cli.figures import (
    _dedupe_history_series,
    _dedupe_products,
    _history_points,
    _history_small_multiples,
    _normalized_axes,
    _num,
    _panel_history_lines,
    _panel_history_small_multiples,
    _panel_metric_small_multiples,
    _product_rows_for_figures,
    _raw_temporal_windows,
    _window_heatmap_for_figures,
    _window_sort_key,
    _xy_axes,
)
from keepa_cli.high_value import attach_output_if_requested, load_selection, selection_to_query_value, write_body_output
from keepa_cli.history_export import build_history_export_data, extract_history_rows, history_rows_to_jsonl, normalize_series_names
from keepa_cli.product_view import (
    _coefficient_of_variation,
    _history_summary,
    _latest_percentile,
    _limit_list,
    _normalize_fields,
    _normalize_profile,
    _normalize_temporal_windows,
    _percentile,
    _ratio_pct,
    _sampling_features,
    _slope_per_day,
    _stats_summary,
    _temporal_by_window,
    _temporal_features,
    _window_change,
    _zscore,
    build_agent_product_view,
    build_product_compare_view,
)
from keepa_cli.redaction import redact_value
from keepa_cli.research_brief import build_research_brief
from keepa_cli.research_context import query_research_context, resolve_research_target
from keepa_cli.research_graph import (
    _choose_variant,
    _node_conflicts,
    _resolve_preferred_source,
    _select_node_variant_for_resolution,
    _truncate_text,
    _variant_matches_source,
    build_category_products_graph,
    build_deals_graph,
    build_research_graph,
    build_topsellers_graph,
    graph_diagnostics,
    graph_edge,
    graph_node,
    merge_research_graphs,
)
from keepa_cli.risk_schema import risk_schema_summary, validate_risk_taxonomy
from keepa_cli.schema_docs import generate_product_agent_schema
from keepa_cli.schema_snapshot import build_agent_schema_snapshot
from keepa_cli.service import run_command
from keepa_cli.token_budget import estimate_request_budget
from keepa_cli.transport import _cassette_key
from keepa_cli.workflows import build_report, build_workflow_plan, explain_cache


FIXTURES = Path("tests/fixtures")


def _graph(root: str = "selection") -> dict[str, object]:
    return build_research_graph(
        root=root,
        nodes=[
            graph_node(root, "selection", "Selection", category_id="172282"),
            graph_node("product:B000000001", "product", "P1", asin="B000000001", monthly_sold=10),
            graph_node("category:172282", "category", "Kitchen", category_id="172282"),
        ],
        edges=[
            graph_edge(root, "product:B000000001", "contains_product", evidence_path="unit.root"),
            graph_edge("product:B000000001", "category:172282", "listed_in", evidence_path="unit.category"),
        ],
    )


def _csv_product() -> dict[str, object]:
    csv = [[] for _ in range(18)]
    csv[1] = [6_000_000, 1000, 6_043_200, 800, 6_129_600, 1200, 6_525_600, 1400]
    csv[3] = [6_000_000, 1000, 6_043_200, 900, 6_129_600, 850, 6_525_600, 700]
    csv[16] = [6_000_000, 10, 6_043_200, 12]
    return {"asin": "B000000001", "title": "CSV product", "csv": csv}


class BackendEdgeCoverageTests(unittest.TestCase):
    def test_figures_private_helpers_cover_fallbacks_and_empty_rendering(self) -> None:
        body_rows = _product_rows_for_figures({"data": {"body": {"products": [{"asin": "B000000001", "title": "Body"}]}}})
        top_rows = _product_rows_for_figures({"products": [{"asin": "B000000002", "title": "Top"}]})
        graph_rows = _product_rows_for_figures({"research_graph": _graph()})
        self.assertEqual(body_rows[0]["asin"], "B000000001")
        self.assertEqual(top_rows[0]["asin"], "B000000002")
        self.assertEqual(graph_rows[0]["asin"], "B000000001")

        self.assertEqual(_history_points("bad"), [])
        self.assertEqual(_history_points([{"value": "1,200.50"}, "skip", {"value": "bad"}])[0]["value"], 1200.5)
        duplicate_series = [
            {"asin": "B1", "name": "new", "points": [{"value": 1}, {"value": 2}]},
            {"asin": "B1", "name": "new", "points": [{"value": 3}, {"value": 4}]},
        ]
        self.assertEqual(len(_dedupe_history_series(duplicate_series)), 1)
        self.assertEqual(len(_dedupe_products([{"asin": "B1"}, {"asin": "B1"}, {"title": "T"}])), 2)

        raw_windows = _raw_temporal_windows(_csv_product())
        heatmap = _window_heatmap_for_figures({"data": {"products": [_csv_product(), {"temporal_by_window": {"bad": "skip"}}]}})
        self.assertIn("recent_30d", raw_windows)
        self.assertTrue(any(cell["series"] == "new" for cell in heatmap))

        self.assertEqual(_num("$1,234.50"), 1234.5)
        self.assertIsNone(_num("not-number"))
        self.assertIsNone(_num(True))
        self.assertEqual(_window_sort_key("recent_30d"), 30)
        self.assertEqual(_window_sort_key("window-90-days"), 90)
        self.assertGreater(_window_sort_key("unknown"), 1_000_000)

        history_rows = _history_small_multiples(
            [
                {"asin": "B2", "name": "new", "points": [{"value": 0}, {"value": 4}], "unit": "currency"},
                {"asin": "B2", "name": "sales_rank", "points": [{"value": 100}, {"value": 80}], "unit": "rank"},
                {"asin": "", "name": "new", "points": [{"value": 1}, {"value": 2}]},
                {"asin": "B3", "name": "unsupported", "points": [{"value": 1}, {"value": 2}]},
            ]
        )
        self.assertEqual(history_rows[0]["series"][0]["metric"], "new")
        self.assertIsNone(history_rows[0]["series"][0]["change_pct"])

        self.assertIn("No history_summary", _panel_history_lines([], x=0, y=0, w=600, h=300))
        self.assertIn("No bounded history", _panel_history_small_multiples([], x=0, y=0, w=600, h=300))
        self.assertIn("No comparable", _panel_metric_small_multiples([], x=0, y=0, w=600, h=300))
        self.assertTrue(_normalized_axes(0, 0, 100, 80, x_label="x", y_label="y", y_ticks=False, x_ticks=False))
        self.assertTrue(_xy_axes(0, 0, 100, 80, x_label="x", y_label="y", min_value=0, max_value=10, x_ticks=3))

    def test_workflow_resolver_covers_reference_shapes_and_derived_params(self) -> None:
        graph = _graph("selection")
        cached = {
            "ok": True,
            "command": "products.compare",
            "data": {
                "body": {"products": [{"asin": "B000000001"}, {"asin": "B000000002"}]},
                "trackings": [{"asin": "B000000003"}],
                "category_candidates": [{"category_id": "172282"}],
                "research_graph": graph,
            },
        }
        cache = {"cache:key": cached}
        resource_uri = "keepa://research/b64:" + text_to_resource_token("cache:key")

        params, resolution = resolve_workflow_arguments(
            "categories_products",
            {"resource_uris": resource_uri, "workflow_context": [resource_uri]},
            session_cache=cache,
        )
        self.assertEqual(params["category"], "172282")
        self.assertGreaterEqual(resolution["payload_count"], 1)

        params, _ = resolve_workflow_arguments("products_get", {"resource_uri": resource_uri}, session_cache=cache)
        self.assertEqual(params["asin"], "B000000001")
        params, _ = resolve_workflow_arguments("tracking_get", {"artifact": {"cache_key": "cache:key"}}, session_cache=cache)
        self.assertEqual(params["asin"], "B000000003")
        params, _ = resolve_workflow_arguments("audit_cost", {"params": {}, "resource_uri": resource_uri}, session_cache=cache)
        self.assertEqual(params["params"]["asin"], "B000000003")
        params, _ = resolve_workflow_arguments("research_brief_export", {"resource_uri": resource_uri}, session_cache=cache)
        self.assertIn("payload", params)
        params, _ = resolve_workflow_arguments("figures_research", {"workflow_context": {"outputs": [{"graph": graph}]}}, session_cache=cache)
        self.assertTrue(Path(params["input"]).is_file())

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "payload.json"
            path.write_text(json.dumps(cached), encoding="utf-8")
            output_uri = path_to_resource_uri(path, kind="output")
            params, resolution = resolve_workflow_arguments(
                "reports_build",
                {
                    "artifacts": [{"raw": {"report": {"path": str(path)}}}],
                    "resource_uris": [output_uri],
                    "workflow_context": {"outputs": [{"resource_uris": [output_uri]}]},
                },
                session_cache=cache,
            )
            self.assertEqual(params["input"], str(path))
            self.assertTrue(any(item.get("kind") == "resource_path" for item in resolution["resolved"]))

        _, unresolved = resolve_workflow_arguments(
            "products_compare",
            {"resource_uris": [123, "missing-cache-key", "keepa://graphs/missing-root"]},
            session_cache={},
        )
        self.assertTrue(any(item.get("kind") == "unsupported" for item in unresolved["resolved"]))
        self.assertTrue(any(item.get("kind") == "unresolved" for item in unresolved["resolved"]))
        self.assertTrue(unresolved["missing_inputs"])

    def test_mcp_resources_cover_static_dynamic_and_error_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs/schema").mkdir(parents=True)
            (root / "evidence/tasks").mkdir(parents=True)
            (root / "tests/fixtures").mkdir(parents=True)
            (root / "keepa_cli/fixtures").mkdir(parents=True)
            (root / ".zread/wiki/versions/v1").mkdir(parents=True)
            for name in ("products.agent-view.schema.json", "workflow-runtime-contract.schema.json", "risk-taxonomy.schema.json"):
                (root / "docs/schema" / name).write_text("{}", encoding="utf-8")
            (root / "evidence/manifest.csv").write_text(
                "logical_path,kind,title\n"
                "evidence/tasks/unit.md,task,Unit\n",
                encoding="utf-8",
            )
            (root / "evidence/tasks/unit.md").write_text("# Unit\n", encoding="utf-8")
            (root / "tests/fixtures/unit.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            (root / "tests/fixtures/category_graph.json").write_text(json.dumps({"data": {"research_graph": _graph("fixture-root")}}), encoding="utf-8")
            (root / "tests/fixtures/bad.json").write_text("{", encoding="utf-8")
            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            (root / ".zread/wiki/versions/v1/wiki.json").write_text(
                json.dumps({"pages": [{"slug": "overview", "file": "overview.md", "title": "Overview"}]}),
                encoding="utf-8",
            )
            (root / ".zread/wiki/versions/v1/overview.md").write_text("# Overview\n", encoding="utf-8")

            self.assertEqual(read_mcp_resource("keepa://schema/products-agent-view", root=root)["mimeType"], "application/json")
            self.assertEqual(read_mcp_resource("keepa://schema/workflow-runtime-contract", root=root)["mimeType"], "application/json")
            self.assertEqual(read_mcp_resource("keepa://schema/risk-taxonomy", root=root)["mimeType"], "application/json")
            self.assertEqual(read_mcp_resource("keepa://fixtures/manifest", root=root)["mimeType"], "text/csv")
            self.assertEqual(read_mcp_resource("keepa://fixtures/unit.json", root=root)["mimeType"], "application/json")
            evidence_uri = "keepa://evidence/" + text_to_resource_token("evidence/tasks/unit.md")
            self.assertIn("# Unit", read_mcp_resource(evidence_uri, root=root)["text"])
            self.assertIn("# Overview", read_mcp_resource("keepa://zread/wiki/page/Overview", root=root)["text"])
            graph_result = json.loads(read_mcp_resource("keepa://graphs/fixture-root", root=root)["text"])
            self.assertEqual(graph_result["match_count"], 1)

            cache_key = "compare:unit"
            cache = {cache_key: {"data": {"research_graph": _graph("cache-root"), "rows": [{"asin": "B000000001"}]}}}
            figure_resource = json.loads(
                read_mcp_resource("keepa://research/b64:" + text_to_resource_token(cache_key) + "/figures", session_cache=cache)["text"]
            )
            missing_figure_resource = json.loads(read_mcp_resource("keepa://research/missing/figures", session_cache=cache)["text"])
            self.assertTrue(figure_resource["found"])
            self.assertFalse(missing_figure_resource["found"])

            for uri in (
                "keepa://cache-key/products.get/",
                "keepa://cache-key/products.get/" + text_to_resource_token("[]"),
                "keepa://workflow//policy",
                "keepa://workflow/" + text_to_resource_token("[]") + "/policy",
                "keepa://workflow/" + text_to_resource_token(json.dumps({"name": "unknown"})) + "/policy",
                "keepa://evidence/" + text_to_resource_token("docs/outside.md"),
                "keepa://evidence/" + text_to_resource_token("evidence/tasks/missing.md"),
                "keepa://zread/wiki/page/",
                "keepa://zread/wiki/page/missing",
            ):
                with self.subTest(uri=uri):
                    with self.assertRaises(ValueError):
                        read_mcp_resource(uri, root=root)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".zread/wiki/current").parent.mkdir(parents=True)
            (root / ".zread/wiki/current").write_text("bad", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                read_mcp_resource("keepa://zread/wiki/current", root=root)

    def test_product_view_research_graph_and_brief_edge_helpers(self) -> None:
        self.assertEqual(_stats_summary("bad"), {})
        self.assertFalse(_history_summary({"csv": "bad"}, 2)["available"])
        self.assertFalse(_temporal_features({"csv": []}, windows=(7,))["available"])
        self.assertIsNone(_window_change([{"keepa_minute": 1, "value": 1}], days=1))
        self.assertIsNone(_window_change([{"keepa_minute": 1, "value": 1}, {"keepa_minute": 2, "value": 2}], days=0))
        self.assertIsNone(_coefficient_of_variation([]))
        self.assertIsNone(_coefficient_of_variation([0, 0]))
        self.assertEqual(_sampling_features([1]), {})
        self.assertEqual(_percentile([], 0.5), 0.0)
        self.assertIsNone(_latest_percentile([]))
        self.assertIsNone(_zscore([1], 1))
        self.assertIsNone(_ratio_pct(1, 0))
        self.assertIsNone(_slope_per_day(1, 0))
        self.assertEqual(_normalize_fields(123), ["123"])
        self.assertEqual(_normalize_temporal_windows(["30,7", "bad", 0]), (7, 30))
        self.assertEqual(_limit_list(("a", "b"), 1), ["a"])
        self.assertEqual(_normalize_profile("unknown"), "research")

        temporal = _temporal_by_window({"series": {"new": "skip", "used": {"windows": {"recent_7d": "skip"}}}})
        self.assertEqual(temporal, {})

        raw_view = build_agent_product_view({"output": {"path": "out.json"}, "body": {"products": []}})
        self.assertEqual(raw_view["raw"]["output"]["path"], "out.json")
        compare = build_product_compare_view({"products": [{"bad": True}, "skip"]})
        self.assertEqual(compare["product_count"], 1)

        conflicts = _node_conflicts(
            [
                {"id": "product:B1", "label": "A", "attributes": {"asin": "B1"}},
                {"id": "product:B1", "label": "B", "attributes": {"asin": "B1", "brand": "B"}},
            ]
        )
        self.assertTrue(conflicts)
        self.assertIsNone(_choose_variant([], preferred_source=None))
        self.assertEqual(_choose_variant([{"source_weight": 1}, {"source_weight": 3}], preferred_source=None)["source_weight"], 3)
        self.assertTrue(_variant_matches_source({"source_index": 2}, {"index": 2}))
        self.assertEqual(_resolve_preferred_source("01", {"1": {"index": 1, "root": "root"}})["matched"], True)
        self.assertEqual(_select_node_variant_for_resolution([{"id": "a"}, {"id": "b"}], [{"root": "x"}, {"root": "y"}], {"source_root": "y"})["id"], "b")
        self.assertIsNone(_truncate_text("", 3))
        self.assertEqual(_truncate_text("abcdef", 3), "...")

        graph = {"root": "root", "nodes": [graph_node("root", "root", "root"), graph_node("orphan", "product", "orphan")], "edges": ["bad"]}
        self.assertEqual(graph_diagnostics(graph)["orphan_node_count"], 1)
        self.assertEqual(merge_research_graphs(["skip"])["sources"], [])
        self.assertEqual(build_category_products_graph(category_id="172282", candidates=[{"bad": True}])["entity_counts"].get("product", 0), 0)
        self.assertEqual(build_deals_graph(deals=[{"bad": True}])["entity_counts"].get("deal", 0), 0)
        self.assertGreaterEqual(build_topsellers_graph(sellers=[{"seller_id": "S1"}])["entity_counts"]["seller"], 1)

        brief = build_research_brief(
            {
                "title": "Brief",
                "payload": {
                    "agent_brief": {"recommended_next_actions": [{"tool": "doctor", "params": {}}]},
                    "output": {"path": "out.json", "format": "json"},
                },
                "graph": [_graph("brief-root")],
            }
        )
        self.assertEqual(brief["id"], "brief-root")
        with self.assertRaises(ValueError):
            build_research_brief({})

    def test_agent_tools_eval_history_and_small_modules(self) -> None:
        self.assertEqual(resolve_toolset_groups(["", "research"]), {"research"})
        with self.assertRaises(ValueError):
            resolve_toolset_groups("missing")

        products_get = get_tool_definition("products_get")
        assert products_get is not None
        self.assertTrue(tool_params_to_command_params(products_get, {"temporal_window_days": [7], "view": "deal"})["agent_view"])
        products_compare = get_tool_definition("products_compare")
        assert products_compare is not None
        self.assertEqual(tool_params_to_command_params(products_compare, {"temporal_window_days": [30]})["temporal_windows"], [30])
        categories_products = get_tool_definition("categories_products")
        assert categories_products is not None
        self.assertEqual(tool_params_to_command_params(categories_products, {"temporal_window_days": [90]})["temporal_windows"], [90])
        audit_cost = get_tool_definition("audit_cost")
        assert audit_cost is not None
        self.assertEqual(tool_params_to_command_params(audit_cost, {})["target_command"], "products.get")

        validation_cases = [
            ("finder_query", {}, "selection"),
            ("products_get", {"asin": "B1", "code": "123"}, "cannot be combined"),
            ("products_compare", {"asin": ["B1"]}, "at least two"),
            ("workflow_plan", {"name": "category-research"}, "term is required"),
            ("workflow_plan", {"name": "product-research"}, "asin is required"),
            ("research_graph_merge", {}, "one of input"),
            ("research_brief_export", {}, "one of input"),
            ("figures_research", {}, "input is required"),
        ]
        for tool_name, args, expected in validation_cases:
            tool = get_tool_definition(tool_name)
            assert tool is not None
            self.assertTrue(any(expected in error for error in validate_tool_arguments(tool, args)))
        self.assertTrue(validate_tool_arguments(products_get, {"unexpected": 1}))
        self.assertEqual(validate_tool_arguments(products_get, None), [])

        with self.assertRaises(AssertionError):
            _resolve_path({"x": 1}, "x.$json")
        with self.assertRaises(KeyError):
            _resolve_path({"x": {}}, "x.missing")
        for value in ("bad", [123], [{"tool": "doctor", "params": [1]}], [{"tool": "missing.command", "params": {}}], [{"tool": "products_get", "params": {"asin": "B1", "code": "C1"}}]):
            with self.subTest(next_action=value):
                with self.assertRaises(AssertionError):
                    _assert_next_actions_executable(value, "actions")
        with self.assertRaises(AssertionError):
            _assert_spec({"x": 1}, {"assertions": [{"path": "x", "equals": 2}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": 1}, {"assertions": [{"path": "x", "min": 2}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": "abc"}, {"assertions": [{"path": "x", "contains": "z"}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": []}, {"assertions": [{"path": "x", "contains_item": {"a": 1}}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": [{"a": 1}]}, {"assertions": [{"path": "x", "not_contains_item": {"a": 1}}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": [1]}, {"assertions": [{"path": "x", "length": 2}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": []}, {"assertions": [{"path": "x", "length_min": 1}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": "abc"}, {"assertions": [{"path": "x", "contains_any": ["z"]}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": "abc"}, {"assertions": [{"path": "x", "not_contains": "a"}]})
        with self.assertRaises(AssertionError):
            _assert_spec({"x": {"risk_taxonomy": {"codes": ["unknown"]}}}, {"assertions": [{"path": "x", "risk_schema_valid": True}]})
        with self.assertRaises(AssertionError):
            check_agent_eval_fixtures(Path(tempfile.mkdtemp()), FIXTURES)

        self.assertEqual(_keepa_body_from_payload({"data": "bad"}), {})
        self.assertEqual(_keepa_body_from_payload({"data": {"products": []}}), {"products": []})
        self.assertIsNone(_find_product({}, "B1"))
        self.assertIsNone(_find_product({"products": ["bad"]}, "B1"))
        self.assertEqual(_find_product({"products": [{"asin": "B2"}]}, "B1")["asin"], "B2")
        error, rows, product = _history_rows_from_payload("history.export", {"asin": "B1"}, {"ok": True, "data": {"products": []}})
        self.assertEqual(error["error"]["kind"], "product_not_found")
        self.assertIsNone(rows)
        self.assertIsNone(product)
        dry = handle_history_command("history.export", {"asin": "B001GZ6QEC", "dry_run": True}, fixture_dir=FIXTURES)
        self.assertTrue(dry["data"]["dry_run"])
        trend_missing = handle_history_command("history.trend", {"asin": "B1"}, fixture_dir=FIXTURES)
        self.assertFalse(trend_missing["ok"])
        with self.assertRaises(ValueError):
            handle_history_command("history.unknown", {}, fixture_dir=FIXTURES)

    def test_cache_config_cassettes_and_command_family_edges(self) -> None:
        self.assertEqual(_safe_for_cache_key(("a", {"key": "secret"})), ["a", {"key": "[REDACTED]"}])
        self.assertIn("temperature", get_mcp_prompt("category_research", {"domain": "US", "term": "temperature"})["messages"][0]["content"]["text"])
        stdio_events = handle_stdio_message(json.dumps({"id": 1, "method": "doctor", "params": {}}))
        self.assertEqual(stdio_events[2]["payload"]["command"], "doctor")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(default_config_path({"XDG_CONFIG_HOME": str(root / "xdg")}), root / "xdg" / "keepa-cli" / "config.toml")
            config_path = root / "config.toml"
            config_path.write_text("bad = [", encoding="utf-8")
            self.assertEqual(load_config(config_path)["_config_error"]["kind"], "toml_decode_error")
            self.assertFalse(build_config_report(config_path)["valid"])
            written = init_config(config_path, dry_run=False)
            self.assertTrue(written["written"])

            self.assertEqual(default_cache_path({"XDG_CACHE_HOME": str(root / "cache")}), root / "cache" / "keepa-cli" / "response-cache.sqlite")
            self.assertEqual(resolve_cache_ttl_seconds(env={"KEEPA_CLI_CACHE_TTL_SECONDS": "0"}), 0)
            self.assertEqual(resolve_cache_ttl_seconds({"cache_ttl_seconds": -5}, env={}), 0)
            key = build_response_cache_key(method="GET", endpoint="/product", params={"asin": "B1"}, json_body={"token": "secret"})
            cache = SQLiteResponseCache(root / "cache.sqlite")
            self.assertIsNone(cache.get("missing", now=1))
            self.assertFalse(cache.inspect("missing", now=1)["found"])
            self.assertFalse(cache.prune_expired(dry_run=True, now=1)["pruned"])
            cache.set(cache_key=key, method="get", endpoint="/product", params={}, request={}, body={"ok": True}, token_bucket={}, ttl_seconds=0, now=1)
            self.assertIsNone(cache.get(key, now=2))
            self.assertFalse(cache.inspect("missing", now=2)["found"])
            self.assertGreaterEqual(cache.prune_expired(dry_run=False, now=2)["expired_entries_removed"], 0)
            cache.set(cache_key=key, method="get", endpoint="/product", params={}, request={}, body={"ok": True}, token_bucket={}, ttl_seconds=10, now=2)
            self.assertTrue(cache.inspect(key, now=3)["found"])
            self.assertGreaterEqual(cache.clear(dry_run=False, now=3)["entries_removed"], 1)

            cassette = root / "cassette.json"
            cassette.write_text(json.dumps({"request": {"url": "https://x.test/?key=secret"}, "response": {"body": {"products": []}}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                _fixture_name("")
            with self.assertRaises(ValueError):
                _fixture_name("../bad")
            self.assertEqual(_redact_url("https://x.test/path"), "https://x.test/path")
            promote_cassette_fixture(cassette, name="unit", tests_dir=root / "fixtures", package_dir=root / "fixtures", manifest_path=root / "manifest.csv")
            promote_cassette_fixture(cassette, name="unit", tests_dir=root / "fixtures", package_dir=root / "fixtures", manifest_path=root / "manifest.csv")

            body_list = write_body_output({"body": [1, 2]}, root / "list.json")
            body_self = write_body_output({"answer": True}, root / "self.json")
            self.assertEqual(body_list["result_count"], 2)
            self.assertEqual(body_self["result_count"], 1)
            self.assertEqual(selection_to_query_value({"b": 2, "a": 1}), '{"a":1,"b":2}')
            with self.assertRaises(ValueError):
                load_selection(selection_file="")
            bad_selection = root / "bad-selection.json"
            bad_selection.write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_selection(selection_file=bad_selection)
            non_object = root / "non-object.json"
            non_object.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_selection(selection_file=non_object)
            payload = {"ok": True, "data": "bad"}
            self.assertIs(attach_output_if_requested(payload, root / "ignored.json"), payload)
            dry_payload = {"ok": True, "data": {"dry_run": True}}
            self.assertIs(attach_output_if_requested(dry_payload, root / "ignored.json"), dry_payload)

        self.assertEqual(as_list(123), ["123"])
        self.assertEqual(optional_params({"a": 1, "b": None}, ["a", "b"]), {"a": 1})
        self.assertEqual(live_cache_options({"cache_ttl": "5", "no_cache": True}), {"cache_ttl_seconds": 5, "no_cache": True})
        self.assertIsNone(handle_deals_command("deals.query", {"selection": {}, "dry_run": True}, fixture_dir=FIXTURES).get("error"))
        with self.assertRaises(ValueError):
            handle_deals_command("deals.unknown", {}, fixture_dir=FIXTURES)
        self.assertIsNone(handle_finder_command("finder.query", {"selection": {}, "dry_run": True}, fixture_dir=FIXTURES).get("error"))
        with self.assertRaises(ValueError):
            handle_finder_command("finder.unknown", {}, fixture_dir=FIXTURES)
        with self.assertRaises(ValueError):
            handle_docs_command("docs.unknown", {})
        with self.assertRaises(ValueError):
            handle_workflow_command("workflow.unknown", {})
        with self.assertRaises(ValueError):
            handle_cache_command("cache.unknown", {}, env={})
        self.assertFalse(handle_tracking_command("tracking.remove", {"asin": " ", "dry_run": True}, fixture_dir=FIXTURES)["ok"])
        with self.assertRaises(ValueError):
            tracking_body({"tracking": None})
        unchanged = {"request": {}}
        self.assertIs(sanitize_webhook_payload(unchanged), unchanged)
        self.assertFalse(handle_category_command("categories.products", {"category": "172282", "limit": 0}, fixture_dir=FIXTURES)["ok"])
        self.assertFalse(handle_category_command("categories.search", {"term": "x"}, fixture_dir=FIXTURES)["ok"])
        self.assertTrue(handle_category_command("categories.products", {"category": "172282", "dry_run": True}, fixture_dir=FIXTURES)["ok"])

    def test_miscellaneous_backend_edges(self) -> None:
        schema = {
            "$defs": {
                "risk_code": {"enum": ["data_missing"]},
                "severity": {"enum": ["low"]},
                "risk_item": {"required": ["code", "severity", "evidence_path"]},
            }
        }
        invalid = validate_risk_taxonomy(
            [
                {
                    "risk_taxonomy": {
                        "codes": ["unknown"],
                        "highest_severity": "critical",
                        "items": ["bad", {"code": "unknown", "severity": "bad"}],
                    }
                }
            ],
            schema,
        )
        self.assertFalse(invalid["ok"])
        self.assertEqual(risk_schema_summary(schema)["known_codes"], ["data_missing"])

        self.assertEqual(_round_value(1), 1)
        self.assertEqual(analyze_history_rows([{"series": "new", "keepa_minute": 1, "value": None}])["series"]["new"]["all_time"], {"points": 0})
        with self.assertRaises(ValueError):
            normalize_series_names(123)
        self.assertEqual(extract_history_rows({"asin": "B1", "csv": [[1, -1]]}, "amazon"), [])
        self.assertEqual(history_rows_to_jsonl([{"a": 1}]).strip(), '{"a":1}')
        self.assertEqual(build_history_export_data(asin="B1", domain="US", rows=[{"a": 1}], output_format="csv")["content"].splitlines()[0], "asin,series,timestamp,keepa_minute,value,raw_value,unit")

        self.assertEqual(resolve_domain("1").domain_id, 1)
        with self.assertRaises(ValueError):
            resolve_domain("missing")
        self.assertEqual(redact_value({"token": "secret"})["token"], "[REDACTED]")
        snapshot = build_agent_schema_snapshot({"products_get_agent_view": {"ok": True, "data": {"value": 1}}})
        self.assertEqual(snapshot["products_get_agent_view"]["data"]["value"], "int")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot_path = root / "snapshot.json"
            output_path = root / "schema.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            self.assertTrue(Path(generate_product_agent_schema(snapshot_path, output_path)["path"]).is_file())
        import urllib.request

        request = urllib.request.Request("https://example.com?key=secret&a=1")
        self.assertIn("%5BREDACTED%5D", _cassette_key(request)["url"])
        self.assertEqual(estimate_request_budget("products.get", {"asin": ("B1", "B2")}).estimated_tokens, 2)
        self.assertTrue(estimate_request_budget("products.get", {"offers": 1}).notes)

        client = KeepaClient(fixture_dir=FIXTURES)
        missing = client.request(command="products.get", method="GET", path="/product", params={}, fixture="missing.json")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["kind"], "fixture_not_found")
        self.assertFalse(run_command("bestsellers.get", {"category": "172282"}, fixture_dir=FIXTURES, env={})["ok"])
        self.assertTrue(run_command("research_graph.merge", {"graph": _graph()}, env={})["ok"])
        self.assertFalse(run_command("research_graph.merge", {}, env={})["ok"])

        with self.assertRaises(ValueError) as workflow_error:
            build_workflow_plan(name="product-research", term=None, asin=None, domain="US", goal="research", hydrate_top=1)
        self.assertIn("requires --asin", str(workflow_error.exception))
        self.assertIn("get-product-summary", json.dumps(build_workflow_plan(name="product-research", term=None, asin="B1", domain="US", goal="deal", hydrate_top=1)))
        figureless = build_report(input_path=str(FIXTURES / "product_B001GZ6QEC.json"), output_format="markdown", out=None, title="No figures", embed_figures=False)
        self.assertNotIn("## Figures", figureless["content"])
        self.assertEqual(explain_cache(input_path=None, command=None, endpoint="x")["endpoint"], "x")


if __name__ == "__main__":
    unittest.main()
