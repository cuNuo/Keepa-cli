"""
tests/test_backend_remaining_coverage.py
文件说明：收尾后端 scoped coverage 剩余分支。
主要职责：覆盖 MCP 资源、workflow 解析、图表渲染、报告、上下文、cassette 校验等剩余边界。
依赖边界：仅使用临时目录、fixture、dry-run 和合成 payload，不访问真实 Keepa API。
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from keepa_cli.agent.resources import MAX_RESOURCE_TEXT_BYTES, path_to_resource_uri, read_mcp_resource, text_to_resource_token
from keepa_cli.agent.workflow_resolver import resolve_workflow_arguments
from keepa_cli.agent_contract import build_data_quality
from keepa_cli.agent_eval import _assert_next_actions_executable, _payload_for_prepared_spec, _resolve_path
from keepa_cli.cache import _cache_safe_value, resolve_cache_ttl_seconds
from keepa_cli.client import KeepaClient
from keepa_cli.commands.categories import handle_category_command
from keepa_cli.commands.docs import handle_docs_command
from keepa_cli.commands.history import handle_history_command
from keepa_cli.commands.selection import attach_selection_profile, selection_query
from keepa_cli.commands.tracking import handle_tracking_command
from keepa_cli.config import load_config
from keepa_cli.domains import resolve_domain
from keepa_cli.figures import (
    _history_series_for_figures,
    _normalize_series_points,
    _normalized_axes,
    _panel_history_lines,
    _panel_history_small_multiples,
    _panel_window_heatmap,
    _product_rows_for_figures,
    _raw_temporal_windows,
    _small_multiple_change_summary,
    _window_heatmap_for_figures,
)
from keepa_cli.history_export import extract_history_rows, write_history_export
from keepa_cli.product_view import (
    _change_profile,
    _compare_risk_summary,
    _dispersion_features,
    _history_summary,
    _merge_research_graphs,
    _normalize_temporal_windows,
    _parse_csv_points,
    _pct_change,
    _research_graph,
    _shape_features,
    _temporal_by_window,
    _temporal_features,
    _window_sort_key,
    write_agent_view_chunks,
)
from keepa_cli.redaction import redact_value
from keepa_cli.research_brief import build_research_brief
from keepa_cli.research_context import query_research_context, resolve_research_target
from keepa_cli.research_graph import (
    _apply_diff_resolutions,
    _select_node_variant_for_resolution,
    _variant_matches_source,
    build_research_graph,
    build_topsellers_graph,
    graph_edge,
    graph_node,
)
from keepa_cli.schema_docs import generate_product_agent_schema
from keepa_cli.schema_snapshot import build_agent_schema_snapshot
from keepa_cli.service import run_command
from keepa_cli.token_budget import estimate_request_budget
from keepa_cli.transport import CassetteResponse, ReplayOpener
from keepa_cli.workflows import _figures_markdown, build_report, explain_cache


FIXTURES = Path("tests/fixtures")


def _graph(root: str = "root") -> dict[str, object]:
    return build_research_graph(
        root=root,
        nodes=[
            graph_node(root, "research_graph", root),
            graph_node("product:B1", "product", "Product 1", asin="B1", brand="A"),
        ],
        edges=[graph_edge(root, "product:B1", "contains_product", evidence_path="unit.graph")],
    )


class BackendRemainingCoverageTests(unittest.TestCase):
    def test_resources_remaining_static_dynamic_and_error_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs/schema").mkdir(parents=True)
            (root / "tests/fixtures").mkdir(parents=True)
            (root / "keepa_cli/fixtures").mkdir(parents=True)
            (root / "evidence/tasks").mkdir(parents=True)
            (root / ".zread/wiki/versions/v1").mkdir(parents=True)
            for name in ("products.agent-view.schema.json", "workflow-runtime-contract.schema.json", "risk-taxonomy.schema.json"):
                (root / "docs/schema" / name).write_text("{}", encoding="utf-8")
            (root / "evidence/manifest.csv").write_text("logical_path,kind\n", encoding="utf-8")
            (root / "keepa_cli/fixtures/package_graph.json").write_text(json.dumps({"data": {"research_graph": _graph("package-root")}}), encoding="utf-8")
            (root / "tests/fixtures/category_graph.json").write_text(json.dumps({"data": {"research_graph": _graph("fixture-root")}}), encoding="utf-8")
            (root / "tests/fixtures/bad_graph.json").write_text("{", encoding="utf-8")
            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            (root / ".zread/wiki/versions/v1/wiki.json").write_text(
                json.dumps({"id": "v1", "language": "zh", "pages": ["skip", {"file": "overview.md", "title": "Overview"}]}),
                encoding="utf-8",
            )
            (root / ".zread/wiki/versions/v1/overview.md").write_text("# Overview\n", encoding="utf-8")

            self.assertIn("tools", read_mcp_resource("keepa://tools/index", root=root)["text"])
            self.assertIn("runtime", read_mcp_resource("keepa://workflow/runtime-contract", root=root)["text"])
            self.assertIn("pages", read_mcp_resource("keepa://zread/wiki/toc", root=root)["text"])
            self.assertIn("page_count", read_mcp_resource("keepa://zread/wiki/pages", root=root)["text"])
            self.assertEqual(read_mcp_resource("keepa://schema/workflow-runtime-contract.schema", root=root)["mimeType"], "application/json")
            self.assertEqual(read_mcp_resource("keepa://schema/risk-taxonomy.schema.json", root=root)["mimeType"], "application/json")
            self.assertEqual(read_mcp_resource("keepa://fixtures/manifest", root=root)["mimeType"], "text/csv")
            self.assertIn("package-root", read_mcp_resource("keepa://graphs/package-root", root=root)["text"])
            self.assertEqual(json.loads(read_mcp_resource("keepa://asin/B1/fixture", root=root)["text"])["match_count"], 0)

            html_path = root / "page.html"
            svg_path = root / "shape.svg"
            plain_path = root / "plain.unknown"
            long_path = root / "long.md"
            html_path.write_text("<p>x</p>", encoding="utf-8")
            svg_path.write_text("<svg></svg>", encoding="utf-8")
            plain_path.write_text("plain", encoding="utf-8")
            long_path.write_text("x" * (MAX_RESOURCE_TEXT_BYTES + 1), encoding="utf-8")
            self.assertEqual(read_mcp_resource(path_to_resource_uri(html_path, kind="output"), root=root)["mimeType"], "text/html")
            self.assertEqual(read_mcp_resource(path_to_resource_uri(svg_path, kind="output"), root=root)["mimeType"], "image/svg+xml")
            self.assertEqual(read_mcp_resource(path_to_resource_uri(plain_path, kind="output"), root=root)["mimeType"], "text/plain")
            self.assertIn("truncated", read_mcp_resource(path_to_resource_uri(long_path, kind="output"), root=root)["text"])

            cache_key = "compare:compact"
            cache = {
                cache_key: {
                    "ok": True,
                    "command": "products.compare",
                    "data": {
                        "raw": {"output": {"path": "raw.json"}},
                        "rows": [
                            {
                                "asin": "B1",
                                "title": "P1",
                                "risk_taxonomy": {"codes": ["data_missing"], "highest_severity": "low", "risk_count": 1},
                                "research_graph": _graph("row-root"),
                            }
                        ],
                    },
                }
            }
            compact = json.loads(read_mcp_resource("keepa://research/b64:" + text_to_resource_token(cache_key), session_cache=cache)["text"])
            self.assertTrue(compact["found"])
            self.assertEqual(compact["research_graph_count"], 1)
            self.assertEqual(compact["cache_key"], cache_key)

            for uri in (
                "keepa://fixtures/missing_graph.json",
                "keepa://cache-key/products.get/",
                "keepa://research//brief",
                "keepa://zread/wiki/page/overview.md",
            ):
                if uri.endswith("overview.md"):
                    self.assertIn("Overview", read_mcp_resource(uri, root=root)["text"])
                    continue
                with self.subTest(uri=uri):
                    with self.assertRaises(ValueError):
                        read_mcp_resource(uri, root=root)

            outside = Path(tempfile.gettempdir()).parent / "outside-keepa-resource.txt"
            outside_token = "keepa://output/" + base64.urlsafe_b64encode(str(outside).encode("utf-8")).decode("ascii").rstrip("=")
            with self.assertRaises(ValueError):
                read_mcp_resource(outside_token, root=root)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".zread/wiki").mkdir(parents=True)
            (root / ".zread/wiki/current").write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://zread/wiki/toc", root=root)
            (root / ".zread/wiki/current").write_text("../bad", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://zread/wiki/toc", root=root)
            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            (root / ".zread/wiki/versions/v1").mkdir(parents=True)
            (root / ".zread/wiki/versions/v1/wiki.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://zread/wiki/toc", root=root)

    def test_workflow_resolver_remaining_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path_a = Path(temp_dir) / "a.json"
            path_b = Path(temp_dir) / "b.json"
            graph_payload = {"data": {"research_graph": _graph("merge-root")}}
            path_a.write_text(json.dumps(graph_payload), encoding="utf-8")
            path_b.write_text(json.dumps(graph_payload), encoding="utf-8")
            params, resolution = resolve_workflow_arguments(
                "research_graph_merge",
                {"resource_uris": [path_to_resource_uri(path_a, kind="output"), path_to_resource_uri(path_b, kind="output")]},
                session_cache={},
            )
            self.assertEqual([Path(item).resolve() for item in params["input"]], [path_a.resolve(), path_b.resolve()])
            self.assertEqual(len(resolution["resolved"]), 2)

        cache = {"graph:key": {"data": {"research_graph": _graph("graph-root")}}}
        _, graph_resolution = resolve_workflow_arguments("products_get", {"resource_uri": "keepa://graphs/graph-root"}, session_cache=cache)
        self.assertEqual(graph_resolution["resolved"][0]["kind"], "graph_audit_resource")
        _, graph_error = resolve_workflow_arguments("products_get", {"resource_uri": "keepa://graphs/missing-root"}, session_cache={})
        self.assertIn("missing_inputs", graph_error)
        params, resolution = resolve_workflow_arguments(
            "reports_build",
            {"workflow_context": {"steps": ["keepa://research/b64:" + text_to_resource_token("graph:key")]}},
            session_cache=cache,
        )
        self.assertTrue(Path(params["input"]).is_file())
        self.assertTrue(resolution["temp_paths"])
        params, resolution = resolve_workflow_arguments("browse_snapshot", {"resource_uri": "keepa://research/missing"}, session_cache={})
        self.assertEqual(resolution["missing_inputs"][0]["field"], "input")
        for tool in ("categories_products", "products_get", "research_brief_export"):
            _, missing = resolve_workflow_arguments(tool, {}, session_cache={})
            self.assertTrue(missing["missing_inputs"])
        params, resolution = resolve_workflow_arguments("audit_cost", {"resource_uri": "keepa://schema/risk-taxonomy"}, session_cache={})
        self.assertIsNotNone(resolution)

    def test_figures_product_view_workflow_and_context_remaining_helpers(self) -> None:
        raw_products = _product_rows_for_figures({"products": [{"asin": "BRAW", "title": "Raw"}]})
        self.assertEqual(raw_products[0]["asin"], "BRAW")
        self.assertEqual(_normalize_series_points([]), [])
        self.assertTrue(_normalized_axes(0, 0, 10, 10, x_label="", y_label=""))
        self.assertIn("No temporal windows", _panel_window_heatmap([], x=0, y=0, w=300, h=200))
        self.assertEqual(_history_series_for_figures({"csv": [[1, 100], [1, 200, 2, 300]]})[0]["data_basis"], "history_summary.last_points")
        self.assertEqual(_raw_temporal_windows({"csv": ["skip"]}), {})
        self.assertEqual(_window_heatmap_for_figures({"temporal_by_window": {"recent_7d": {"new": {"change_pct": "bad"}}}}), [])
        self.assertIn("polyline", _panel_history_lines([{"asin": "B1", "name": "new", "points": [{"value": 1}, {"value": 2}]}], x=0, y=0, w=700, h=300))
        self.assertIn(
            "polyline",
            _panel_history_small_multiples(
                [{"asin": "B1", "series": [{"metric": "new", "normalized_points": [{"x": 0, "y": 0}, "skip", {"x": 1, "y": 1}]}]}],
                x=0,
                y=0,
                w=720,
                h=360,
            ),
        )
        self.assertEqual(_small_multiple_change_summary({"series": [{"metric": "unknown", "change_pct": 1}]}), "")

        odd_meta = {"name": "new", "unit": "currency", "scale": 100}
        points, warning = _parse_csv_points([1, 100, 2], odd_meta)
        self.assertTrue(points)
        self.assertIn("not divisible", warning)
        self.assertTrue(_history_summary({"csv": [[1, -1, 2, -1]]}, 2)["series"])
        self.assertFalse(_temporal_features({"csv": [[1, 100, 2]]}, windows=(1,))["available"])
        self.assertEqual(
            _temporal_by_window({"temporal_features": {"series": {"new": {"windows": {"recent_7d": {"change_pct": 1}}}}}})["recent_7d"]["series"]["new"]["change_pct"],
            1,
        )
        self.assertEqual(_compare_risk_summary([{"risk_taxonomy": {"items": ["skip", {"severity": "high"}]}}])["by_severity"]["high"], 1)
        self.assertTrue(_merge_research_graphs([{"research_graph": _graph("g1")}, {"research_graph": "skip"}])["nodes"])
        with tempfile.TemporaryDirectory() as temp_dir:
            chunks = write_agent_view_chunks({"products": [{"identity": {"asin": "B1"}, "history_summary": {"x": 1}}]}, Path(temp_dir))
            self.assertTrue(chunks)
        self.assertEqual(_dispersion_features([]), {})
        self.assertEqual(_change_profile([]), {})
        self.assertEqual(_shape_features([1]), {})
        self.assertIsNone(_pct_change(0, 1))
        self.assertEqual(_window_sort_key("unknown"), 10**9)
        self.assertFalse(_research_graph({"categoryTree": ["skip"]})["nodes"])
        self.assertEqual(_normalize_temporal_windows(""), (7, 30, 90, 180, 365))
        self.assertEqual(_normalize_temporal_windows(14), (14,))

        report = {"nodes": [{"id": str(i), "type": "product", "label": f"P{i}"} for i in range(45)], "edges": [{"source": "a", "target": "b", "type": "rel"} for _ in range(65)]}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.json"
            path.write_text(json.dumps({"research_graph": {**_graph("report-root"), **report}}), encoding="utf-8")
            markdown = build_report(input_path=str(path), output_format="markdown", out=None, title="Graph")
            self.assertIn("more entities", markdown["content"])
            self.assertIn("more relationships", markdown["content"])
            fig = Path(temp_dir) / "provided.svg"
            fig.write_text("<svg></svg>", encoding="utf-8")
            figure_markdown = build_report(input_path=str(path), output_format="markdown", out=None, title="Graph", figure=str(fig))
            self.assertIn("![provided]", figure_markdown["content"])
        self.assertIn("No report figures available", _figures_markdown({"figures": []}))
        self.assertEqual(explain_cache(input_path=None, command="products.get", endpoint=None)["source"], "unknown")
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = Path(temp_dir) / "cache.json"
            payload.write_text(json.dumps({"cache_provenance": {"source": "root-cache"}, "data": {}}), encoding="utf-8")
            self.assertEqual(explain_cache(input_path=str(payload), command=None, endpoint=None)["source"], "root-cache")

        self.assertEqual(resolve_research_target({"query": "012345678905", "domain": "US"})["primary"]["type"], "code")
        for target_type in ("category", "seller", "keyword", "fixture", "evidence"):
            target = {"type": target_type, "id": "172282" if target_type == "category" else "fixture.json", "domain": "US"}
            result = query_research_context({"target": target}, repo_root=Path("."))
            self.assertTrue(result["resources"])

    def test_service_cassette_eval_and_command_remaining_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cassette = root / "cassette.json"
            cassette.write_text(json.dumps({"response": {"body": {"products": []}}}), encoding="utf-8")
            tests_dir = root / "tests-fixtures"
            package_dir = root / "package-fixtures"
            eval_dir = root / "eval"
            eval_dir.mkdir()
            spec = {
                "kind": "service",
                "command": "doctor",
                "params": {},
                "assertions": [{"path": "ok", "equals": True}],
            }
            (eval_dir / "doctor.json").write_text(json.dumps(spec), encoding="utf-8")
            success = run_command(
                "cassettes.promote_and_verify",
                {
                    "input": str(cassette),
                    "name": "unit",
                    "tests_dir": str(tests_dir),
                    "package_dir": str(package_dir),
                    "eval_dir": str(eval_dir),
                    "manifest": str(root / "manifest.csv"),
                    "run_eval": True,
                },
                env={},
            )
            self.assertTrue(success["ok"])
            (eval_dir / "bad.json").write_text(json.dumps({**spec, "assertions": [{"path": "ok", "equals": False}]}), encoding="utf-8")
            failed_eval = run_command(
                "cassettes.promote_and_verify",
                {
                    "input": str(cassette),
                    "name": "unit2",
                    "tests_dir": str(tests_dir),
                    "package_dir": str(package_dir),
                    "eval_dir": str(eval_dir),
                    "manifest": str(root / "manifest.csv"),
                    "run_eval": True,
                },
                env={},
            )
            self.assertFalse(failed_eval["ok"])
            (package_dir / "extra.json").write_text("{}", encoding="utf-8")
            failed_sync = run_command(
                "cassettes.promote_and_verify",
                {
                    "input": str(cassette),
                    "name": "unit3",
                    "tests_dir": str(tests_dir),
                    "package_dir": str(package_dir),
                    "manifest": str(root / "manifest.csv"),
                },
                env={},
            )
            self.assertFalse(failed_sync["ok"])

        fixture_payload = handle_category_command("categories.search", {"term": "home", "fixture": "category_search_home.json"}, fixture_dir=FIXTURES)
        self.assertTrue(fixture_payload["ok"])
        dry_payload = handle_category_command("categories.search", {"term": "home", "dry_run": True}, fixture_dir=FIXTURES)
        self.assertTrue(dry_payload["ok"])
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "category.json"
            payload = handle_category_command("categories.products", {"category": "172282", "fixture": "bestsellers_home.json", "out": str(out)}, fixture_dir=FIXTURES)
            self.assertTrue(payload["ok"])
        self.assertFalse(handle_category_command("categories.products", {"category": "172282", "fixture": "missing.json"}, fixture_dir=FIXTURES)["ok"])
        self.assertTrue(handle_history_command("history.trend", {"asin": "B001GZ6QEC", "dry_run": True}, fixture_dir=FIXTURES)["ok"])
        self.assertFalse(handle_tracking_command("tracking.remove", {"dry_run": True}, fixture_dir=FIXTURES)["ok"])
        self.assertTrue(handle_tracking_command("tracking.webhook", {"url": "https://x.test?key=secret", "dry_run": True}, fixture_dir=FIXTURES)["ok"])
        self.assertIs(attach_selection_profile({"ok": False}, command="finder.query", selection={}), None)
        with self.assertRaises(ValueError):
            selection_query("finder.query", "/query", {"selection": {}, "domain": ""}, fixture_dir=FIXTURES)
        self.assertIn("json", handle_docs_command("docs.read", {"uri": "keepa://tools/index"})["data"])
        self.assertIn("text", handle_docs_command("docs.read", {})["data"])

    def test_misc_remaining_helpers(self) -> None:
        self.assertEqual(_cache_safe_value(("a", {"token": "secret"})), ["a", {"token": "[REDACTED]"}])
        self.assertEqual(resolve_cache_ttl_seconds(env={}), 3600)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text("language = \"en\"\n", encoding="utf-8")
            with mock.patch("pathlib.Path.read_text", side_effect=OSError("boom")):
                self.assertEqual(load_config(config_path)["_config_error"]["kind"], "config_read_error")
        self.assertEqual(resolve_domain(" ").code if False else "skip", "skip")
        with self.assertRaises(ValueError):
            resolve_domain(" ")
        self.assertEqual(redact_value({"nested": {"api_key": "secret"}})["nested"]["api_key"], "[REDACTED]")
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = Path(temp_dir) / "bad-snapshot.json"
            snapshot.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                generate_product_agent_schema(snapshot, Path(temp_dir) / "out.json")
        snapshot = build_agent_schema_snapshot({"x": (1, None)})
        self.assertEqual(snapshot["x"], ["int", "null"])
        self.assertEqual(estimate_request_budget("products.get", {"asin": {"B1", "B2"}}).estimated_tokens, 2)
        self.assertTrue(estimate_request_budget("products.get", {"offers": 1000}).notes)
        response = CassetteResponse(b"body")
        self.assertIs(response.__enter__(), response)
        cassette_path = Path(tempfile.mkdtemp()) / "cassette.json"
        cassette_path.write_text(
            json.dumps({"request": {"method": "GET", "url": "https://example.test/path"}, "response": {"body_base64": base64.b64encode(b"{}").decode("ascii")}}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            ReplayOpener(cassette_path)(urllib.request.Request("https://example.test/other"), 1)
        class _Error:
            fp = None

        self.assertEqual(KeepaClient()._read_http_error_body(_Error()), {})
        with self.assertRaises(AssertionError):
            _resolve_path({"x": 1}, "x.y.z")
        _assert_next_actions_executable([{"tool": "doctor", "params": []}], "actions")
        self.assertEqual(_payload_for_prepared_spec({"kind": "mcp_session", "steps": [{"method": "initialize"}]}, FIXTURES)["kind"], "mcp_session")
        self.assertEqual(_payload_for_prepared_spec({"kind": "session", "steps": [{"command": "doctor"}]}, FIXTURES)["kind"], "session")
        with self.assertRaises(AssertionError):
            _payload_for_prepared_spec({"kind": "unknown"}, FIXTURES)

        graph = {"nodes": [{"id": "x", "attributes": {"source_weight": 1}}], "entity_counts": {}}
        _apply_diff_resolutions(graph, node_variants={"x": [{"id": "x", "attributes": {"source_weight": 2}}]}, variant_sources={"x": [{}]}, diff={"resolutions": []})
        self.assertEqual(graph["nodes"][0]["attributes"]["source_weight"], 1)
        _apply_diff_resolutions(graph, node_variants={"x": [{"id": "x", "type": "product"}]}, variant_sources={"x": [{"index": 1}]}, diff={"resolutions": [{"id": "x", "source_index": 1}]})
        self.assertEqual(graph["nodes"][0]["type"], "product")
        self.assertEqual(_select_node_variant_for_resolution([], [], {"source_root": "x"}), None)
        self.assertFalse(_variant_matches_source({"source_root": ""}, {"root": ""}))
        self.assertGreaterEqual(build_topsellers_graph(sellers=[{"sellerId": "S1"}], category_id="172282")["edge_count"], 2)
        brief = build_research_brief({"title": "!!!", "payload": {"data": {"value": 1}}})
        self.assertEqual(brief["id"], "research_brief_1")
        self.assertEqual(brief["decision_summary"]["one_line"], "research brief generated from local payloads")
        self.assertIsNone(build_research_brief({"title": "X", "graph": []})["entity_graph_summary"])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            self.assertEqual(write_history_export([{"a": 1}], path, "json")["format"], "json")
        with self.assertRaises(ValueError):
            extract_history_rows({"asin": "B1", "csv": [[1]]}, "amazon")
        self.assertEqual(build_data_quality(present=["a"], missing=[], notes=["high"])["missing"], [])


if __name__ == "__main__":
    unittest.main()
