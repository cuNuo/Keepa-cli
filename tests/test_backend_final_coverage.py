"""
tests/test_backend_final_coverage.py
文件说明：补齐后端 scoped coverage 的最后一批边界分支。
主要职责：覆盖 MCP 资源、Agent tool registry、workflow resolver 与本地转换的防御路径。
依赖边界：仅使用临时目录、fixture、session cache 和合成 payload，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keepa_cli.agent.resources import (
    build_resource_manifest,
    compact_payload_for_mcp,
    list_mcp_resource_templates,
    list_mcp_resources,
    path_to_resource_uri,
    read_mcp_resource,
    text_to_resource_token,
)
from keepa_cli.agent.prompts import get_mcp_prompt
from keepa_cli.agent.stdio import handle_stdio_message
from keepa_cli.agent.tools import (
    get_tool_definition,
    list_mcp_tools,
    resolve_toolset_groups,
    tool_names,
    tool_params_to_command_params,
    validate_tool_arguments,
    workflow_runtime_contract,
)
from keepa_cli.agent.workflow_resolver import _first, _merge_values, resolve_workflow_arguments
from keepa_cli.agent_contract import build_data_quality
from keepa_cli.agent_eval import _assert_next_actions_executable
from keepa_cli.commands.cache import handle_cache_command
from keepa_cli.commands.categories import handle_category_command
from keepa_cli.commands.docs import handle_docs_command
from keepa_cli.commands.history import handle_history_command
from keepa_cli.commands.selection import selection_query
from keepa_cli.commands.tracking import handle_tracking_command
from keepa_cli.figures import (
    _filter_figure_specs,
    _history_small_multiples,
    _normalize_figure_set,
    _panel_history_lines,
    _panel_history_small_multiples,
    _panel_window_heatmap,
    _product_metric_row,
    _product_rows_for_figures,
    _raw_temporal_windows,
    _num,
    _window_heatmap_for_figures,
)
from keepa_cli.history_export import extract_history_rows
from keepa_cli.product_view import (
    _history_summary,
    _merge_research_graphs,
    _normalize_temporal_windows,
    _research_graph,
    _temporal_by_window,
    write_agent_view_chunks,
)
from keepa_cli.redaction import redact_value
from keepa_cli.research_brief import build_research_brief
from keepa_cli.research_context import query_research_context, resolve_research_target
from keepa_cli.research_graph import _apply_diff_resolutions, build_research_graph, graph_edge, graph_node
from keepa_cli.schema_snapshot import build_agent_schema_snapshot
from keepa_cli.token_budget import estimate_request_budget
from keepa_cli.workflows import _product_rows, _report_figure_info, _step_profile, explain_cache


FIXTURES = Path("tests/fixtures")


def _graph(root: str = "root") -> dict[str, object]:
    graph = build_research_graph(
        root=root,
        nodes=[
            graph_node(root, "selection", "Root", category_id="172282"),
            graph_node("product:B1", "product", "Product 1", asin="B1", brand="Brand"),
        ],
        edges=[graph_edge(root, "product:B1", "contains_product", evidence_path="unit.graph")],
    )
    graph["sources"] = [{"root": root, "index": 1}]
    graph["diagnostics"] = {"duplicate_node_count": 1, "orphan_node_count": 0, "conflict_count": 0, "highest_source_weight": 2}
    return graph


def _csv_product() -> dict[str, object]:
    csv = [[] for _ in range(18)]
    csv[1] = [6_000_000, 1000, 6_001_440, 800]
    csv[3] = [6_000_000, 900, 6_001_440, 700]
    return {"asin": "B1", "title": "CSV", "csv": csv}


class BackendFinalCoverageTests(unittest.TestCase):
    def test_mcp_resource_contract_error_and_boundary_paths(self) -> None:
        self.assertTrue(list_mcp_resources())
        self.assertTrue(list_mcp_resource_templates())
        self.assertTrue(path_to_resource_uri(Path("tests/fixtures/bestsellers_home.json")).startswith("keepa://chunk/"))
        self.assertTrue(text_to_resource_token("cache:key"))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs/schema").mkdir(parents=True)
            (root / "docs/schema/products.agent-view.schema.json").write_text("{}", encoding="utf-8")
            (root / "docs/schema/workflow-runtime-contract.schema.json").write_text("{}", encoding="utf-8")
            (root / "docs/schema/risk-taxonomy.schema.json").write_text("{}", encoding="utf-8")
            (root / "evidence/tasks").mkdir(parents=True)
            (root / "evidence/manifest.csv").write_text(
                "logical_path,title,status,updated_at,summary\n"
                "evidence/tasks/task.md,Task,done,2026-05-11,summary\n",
                encoding="utf-8",
            )
            (root / "evidence/tasks/task.md").write_text("# Task\n", encoding="utf-8")
            (root / "tests/fixtures").mkdir(parents=True)
            (root / "tests/fixtures/graph_fixture.json").write_text(json.dumps({"research_graph": _graph("root")}), encoding="utf-8")
            (root / "keepa_cli/fixtures").mkdir(parents=True)
            (root / ".zread/wiki/versions/v1").mkdir(parents=True)
            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            (root / ".zread/wiki/versions/v1/wiki.json").write_text(
                json.dumps({"id": "v1", "pages": ["skip", {"file": "overview.md", "slug": "overview", "title": "Overview"}]}),
                encoding="utf-8",
            )
            (root / ".zread/wiki/versions/v1/overview.md").write_text("# Overview\n", encoding="utf-8")

            evidence_uri = "keepa://evidence/" + text_to_resource_token("evidence/tasks/task.md")
            self.assertIn("# Task", read_mcp_resource(evidence_uri, root=root)["text"])
            self.assertIn("Overview", read_mcp_resource("keepa://zread/wiki/page/Overview", root=root)["text"])
            self.assertIn("Overview", read_mcp_resource("keepa://zread/wiki/page/b64:" + text_to_resource_token("overview.md"), root=root)["text"])
            self.assertEqual(json.loads(read_mcp_resource("keepa://graphs/b64:" + text_to_resource_token("root"), root=root)["text"])["match_count"], 1)
            self.assertEqual(json.loads(read_mcp_resource("keepa://evidence/recent", root=root)["text"])["items"][0]["logical_path"], "evidence/tasks/task.md")

            for uri in (
                "keepa://schema/missing",
                "keepa://fixtures/../bad.json",
                "keepa://asin//bad",
                "keepa://evidence/" + text_to_resource_token("../bad.md"),
                "keepa://zread/wiki/page/missing",
                "keepa://missing",
            ):
                with self.subTest(uri=uri):
                    with self.assertRaises(ValueError):
                        read_mcp_resource(uri, root=root)

            (root / ".zread/wiki/current").write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://zread/wiki/current", root=root)
            (root / ".zread/wiki/current").write_text("versions/../bad", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://zread/wiki/current", root=root)

        outside_uri = path_to_resource_uri(Path.home() / "definitely-outside-keepa-resource.txt", kind="output")
        with self.assertRaises(ValueError):
            read_mcp_resource(outside_uri, root=Path.cwd())

    def test_mcp_resource_compaction_and_research_figure_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chunk = Path(temp_dir) / "chunk.json"
            output = Path(temp_dir) / "output.html"
            svg = Path(temp_dir) / "figure.svg"
            plain = Path(temp_dir) / "plain.bin"
            chunk.write_text("{}", encoding="utf-8")
            output.write_text("<p>x</p>", encoding="utf-8")
            svg.write_text("<svg></svg>", encoding="utf-8")
            plain.write_text("plain", encoding="utf-8")
            payload = {
                "ok": True,
                "data": {
                    "products": [
                        {
                            "agent_brief": {"one_line": "brief", "key_facts": {"asin": "B1"}, "risk_codes": ["data_missing"]},
                            "identity": {"asin": "B1"},
                            "data_quality": {"confidence": "high"},
                            "risk_taxonomy": {"codes": ["data_missing"]},
                            "selection_signals": {"score": 1},
                            "next_actions": [{"tool": "keepa.products_get"}],
                            "evidence_index": {"identity": {"path": "identity"}},
                            "research_graph": _graph("product:B1"),
                        }
                    ],
                    "rows": [{"asin": "B1", "title": "Row", "risk_taxonomy": {"codes": ["data_missing"]}, "research_graph": _graph("row")}],
                    "raw": {"output": {"path": str(output), "format": "html", "size_bytes": output.stat().st_size}},
                    "chunks": [{"path": str(chunk), "format": "json", "size_bytes": chunk.stat().st_size, "section": "identity"}],
                    "output": {"path": str(svg), "format": "svg", "size_bytes": svg.stat().st_size},
                    "extra": [{"path": str(plain), "format": "bin", "size_bytes": plain.stat().st_size}],
                    "research_graph": _graph("data"),
                },
            }
            manifest = build_resource_manifest(payload)
            compact = compact_payload_for_mcp(payload)
            self.assertGreaterEqual(manifest["resource_count"], 4)
            self.assertIn("mcp_resource_manifest", compact)
            self.assertIn("research_graph_summary", compact["data"])
            self.assertIn("evidence_index_summary", compact["data"]["products"][0])
            self.assertIn("research_graph_summary", compact["data"]["rows"][0])
            self.assertEqual(read_mcp_resource(path_to_resource_uri(output, kind="output"), root=Path.cwd())["mimeType"], "text/html")
            self.assertEqual(read_mcp_resource(path_to_resource_uri(svg, kind="output"), root=Path.cwd())["mimeType"], "image/svg+xml")
            self.assertEqual(read_mcp_resource(path_to_resource_uri(plain, kind="output"), root=Path.cwd())["mimeType"], "text/plain")

        figure_payload = {
            "ok": True,
            "command": "products.get",
            "data": {"products": [{"asin": "B1", "title": "P1"}], "research_graph": _graph("product:B1")},
        }
        cache = {"fig:key": figure_payload}
        self.assertTrue(json.loads(read_mcp_resource("keepa://research/b64:" + text_to_resource_token("fig:key") + "/figures", session_cache=cache)["text"])["found"])
        self.assertTrue(json.loads(read_mcp_resource("keepa://research/b64:" + text_to_resource_token("fig:key") + "/figures/history", session_cache=cache)["text"])["found"])
        self.assertFalse(json.loads(read_mcp_resource("keepa://research/b64:" + text_to_resource_token("missing") + "/figures", session_cache=cache)["text"])["found"])

    def test_agent_tool_registry_and_validation_edges(self) -> None:
        self.assertEqual(resolve_toolset_groups(["", "all"]), None)
        self.assertIn("research", resolve_toolset_groups(["research", "docs"]))
        with self.assertRaises(ValueError):
            resolve_toolset_groups("missing")

        tools = list_mcp_tools(toolsets="all", allow_tools=["keepa.products_get", "missing"], exclude_tools=["missing"], profile="offline_fixture_only")
        self.assertEqual([tool["name"] for tool in tools], ["keepa.products_get"])
        self.assertFalse(tools[0]["x-keepa"]["active"])
        self.assertIsNotNone(get_tool_definition("keepa.products_get"))
        self.assertIsNone(get_tool_definition("missing"))
        self.assertIn("keepa.products_get", tool_names())
        self.assertIn("tools", workflow_runtime_contract())

        product_get = get_tool_definition("keepa.products_get")
        product_compare = get_tool_definition("keepa.products_compare")
        category_products = get_tool_definition("keepa.categories_products")
        audit_cost = get_tool_definition("keepa.audit_cost")
        workflow_plan = get_tool_definition("keepa.workflow_plan")
        assert product_get and product_compare and category_products and audit_cost and workflow_plan
        self.assertEqual(tool_params_to_command_params(product_get, {"temporal_window_days": [7], "view": "summary"})["temporal_windows"], [7])
        self.assertTrue(tool_params_to_command_params(product_get, {"view": "summary"})["agent_view"])
        self.assertEqual(tool_params_to_command_params(product_compare, {"temporal_window_days": [7]})["temporal_windows"], [7])
        self.assertEqual(tool_params_to_command_params(category_products, {"temporal_window_days": [7]})["temporal_windows"], [7])
        self.assertEqual(tool_params_to_command_params(audit_cost, {})["target_command"], "products.get")
        self.assertTrue(any("term is required" in error for error in validate_tool_arguments(workflow_plan, {"name": "category-research"})))
        self.assertTrue(any("asin is required" in error for error in validate_tool_arguments(workflow_plan, {"name": "product-research"})))

    def test_workflow_resolver_remaining_resource_shapes(self) -> None:
        graph = _graph("root")
        cached = {
            "ok": True,
            "command": "products.compare",
            "data": {
                "research_graph": graph,
                "rows": [{"asin": "B1"}, {"asin": "B2"}],
                "category_candidates": [{"category_id": "172282"}],
                "trackings": [{"asin": "B3"}],
            },
        }
        cache = {"cache:key": cached}
        resource = "keepa://research/b64:" + text_to_resource_token("cache:key")
        params, resolution = resolve_workflow_arguments("keepa.research_graph_merge", {"resource_uri": resource + "/graph"}, session_cache=cache)
        self.assertIn("graph", params)
        self.assertGreaterEqual(resolution["graph_count"], 1)
        params, resolution = resolve_workflow_arguments("keepa.reports_build", {"workflow_context": {"outputs": [{"payload": {"x": 1}}]}}, session_cache=cache)
        self.assertTrue(Path(params["input"]).is_file())
        self.assertTrue(resolution["temp_paths"])
        params, resolution = resolve_workflow_arguments("keepa.products_compare", {"resource_uris": ["keepa://graphs/missing"]}, session_cache=cache)
        self.assertTrue(resolution["resolved"][0].get("error") or "resource_uris" in resolution["resolved"][0])
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"resource_uri": "keepa://missing"}, session_cache=cache)
        self.assertIn("error", resolution["resolved"][0])
        params, resolution = resolve_workflow_arguments("keepa.audit_cost", {"params": {}, "workflow_context": {"steps": {"one": resource}}}, session_cache=cache)
        self.assertEqual(params["params"]["asin"], "B3")
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"workflow_context": {"artifacts": resource}}, session_cache=cache)
        self.assertEqual(params["asin"], "B1")

    def test_figures_product_view_and_workflow_remaining_paths(self) -> None:
        self.assertEqual(_normalize_figure_set(None), "all")
        with self.assertRaises(ValueError):
            _normalize_figure_set("missing")
        self.assertEqual(_filter_figure_specs([{"name": "history-lines"}, {"name": "risk-graph-summary"}], "history"), [{"name": "history-lines"}])
        self.assertEqual(_product_rows_for_figures({"products": [{"asin": "B1"}, "skip"]})[0]["asin"], "B1")
        self.assertEqual(_raw_temporal_windows({"csv": [[]]}) or {}, {})
        self.assertEqual(_window_heatmap_for_figures({"temporal_features": {"series": {"new": {"windows": {"bad": "skip"}}}}}), [])
        self.assertEqual(_history_small_multiples(["skip", {"asin": "B1", "name": "new", "points": [{"value": 1}]}]), [])
        self.assertIn("polyline", _panel_history_lines([{"asin": "B1", "name": "new", "points": [{"value": 1}, "skip", {"value": 2}]}], x=0, y=0, w=650, h=300))
        self.assertIn("polyline", _panel_history_small_multiples([{"asin": "B1", "series": [{"metric": "new", "normalized_points": [{"x": 0, "y": 0}, "skip", {"x": 1, "y": 1}]}]}], x=0, y=0, w=650, h=300))

        summary = _history_summary({"csv": [["bad"], [1, -1, 2, -1]]}, 1)
        self.assertTrue(summary["warnings"])
        self.assertEqual(_temporal_by_window({"temporal_features": {"series": {"new": "skip", "sales_rank": {"windows": {"bad": "skip"}}}}}), {})
        self.assertTrue(_merge_research_graphs([{"research_graph": {"nodes": [{"id": "a"}], "edges": [{"source": "", "target": "", "type": ""}]}}])["nodes"])
        self.assertEqual(write_agent_view_chunks({"products": ["skip"]}, tempfile.mkdtemp()), [])
        graph = _research_graph({"identity": {"asin": "B1", "brand": "Brand", "manufacturer": "Maker"}, "category": {"category_tree": ["skip", {"id": 1, "name": "Root"}]}})
        self.assertIn("manufacturer:maker", json.dumps(graph))
        self.assertEqual(_normalize_temporal_windows("7,30"), (7, 30))

        self.assertEqual(_product_rows({"body": {"products": [{"asin": "B1", "title": "T", "brand": "B"}, "skip"]}})[0]["asin"], "B1")
        self.assertEqual(_step_profile("request.get", requires_confirmation=True), "live_read_allowed")
        self.assertEqual(explain_cache(input_path=None, command="products.get", endpoint=None)["source"], "unknown")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.json"
            input_path.write_text(json.dumps({"data": {"products": [{"asin": "B1", "title": "P1"}]}}), encoding="utf-8")
            info = _report_figure_info(input_path=str(input_path), out=None, title="T", figure=None, figures_dir=str(root / "figures"), figure_set="compare", enabled=True)
            self.assertEqual(info["mode"], "generated")
            figure = root / "provided.svg"
            figure.write_text("<svg></svg>", encoding="utf-8")
            provided = _report_figure_info(input_path=str(input_path), out=None, title="T", figure=str(figure), figures_dir=None, figure_set="all", enabled=True)
            self.assertEqual(provided["mode"], "provided")
            with self.assertRaises(ValueError):
                _report_figure_info(input_path=str(input_path), out=None, title="T", figure=str(root / "missing.svg"), figures_dir=None, figure_set="all", enabled=True)
            self.assertIsNone(_report_figure_info(input_path=str(input_path), out=None, title="T", figure=None, figures_dir=None, figure_set="all", enabled=False))

    def test_remaining_small_helpers_and_command_edges(self) -> None:
        self.assertEqual(build_data_quality(present=["a", "b"], missing=["c"])["confidence"], "low")
        self.assertEqual(build_data_quality(present=["a", "b", "c"], missing=["d"])["confidence"], "medium")
        self.assertTrue(build_agent_schema_snapshot({"x": {"items": [{"a": 1}, {"a": "s"}]}})["x"]["items"][0]["a"])
        self.assertEqual(redact_value({"a": [{"token": "x"}]})["a"][0]["token"], "[REDACTED]")
        self.assertEqual(estimate_request_budget("products.get", {"asin": [{"a": 1}]}).estimated_tokens, 1)
        self.assertEqual(build_research_brief({"payload": {"items": ["skip"]}})["decision_summary"]["items"], [])
        graph = {"nodes": [{"id": "x"}], "entity_counts": {}}
        _apply_diff_resolutions(graph, node_variants={"x": [{"id": "x", "type": "product"}]}, variant_sources={"x": [{}]}, diff={"resolutions": [{"id": "x"}]})
        self.assertEqual(graph["nodes"][0]["type"], "product")

        self.assertFalse(handle_category_command("categories.products", {"category": "172282", "limit": 0}, fixture_dir=FIXTURES)["ok"])
        self.assertTrue(handle_category_command("categories.products", {"category": "172282", "fixture": "bestsellers_home.json"}, fixture_dir=FIXTURES)["ok"])
        self.assertFalse(handle_tracking_command("tracking.remove", {}, fixture_dir=FIXTURES)["ok"])
        with self.assertRaises(ValueError):
            selection_query("finder.query", "/query", {"selection": {}, "domain": ""}, fixture_dir=FIXTURES)
        self.assertFalse(handle_history_command("history.export", {"asin": "B1"}, fixture_dir=FIXTURES)["ok"])
        with self.assertRaises(ValueError):
            extract_history_rows({"asin": "B1", "csv": [[1, 2]]}, "missing")

        with mock.patch("keepa_cli.commands.docs.read_mcp_resource", return_value={"uri": "u", "mimeType": "application/json", "text": "{"}):
            self.assertIsNone(handle_docs_command("docs.read", {"uri": "u"})["data"]["json"])
        fixture_target = resolve_research_target({"query": "product_B001GZ6QEC", "hint_type": "fixture", "domain": "US"}, repo_root=Path.cwd())
        self.assertEqual(fixture_target["next_actions"][0]["tool"], "keepa.query_research_context")
        context = query_research_context({"query": "not-present", "domain": "US", "limit": 1}, repo_root=Path(tempfile.mkdtemp()))
        self.assertEqual(context["target"]["type"], "keyword")

    def test_single_line_defensive_edges(self) -> None:
        with self.assertRaises(ValueError):
            get_mcp_prompt("keepa.product_research", {})
        events = handle_stdio_message(json.dumps({"id": 1, "method": "doctor", "params": 1}))
        self.assertEqual(events[0]["event"], "started")
        with self.assertRaises(AssertionError):
            _assert_next_actions_executable([{"tool": "keepa.doctor", "params": 1}], "actions")

        self.assertTrue(handle_cache_command("cache.clear", {})["ok"])
        self.assertFalse(handle_history_command("history.trend", {"asin": ["B1", "B2"]}, fixture_dir=FIXTURES)["ok"])
        self.assertFalse(handle_tracking_command("tracking.remove", {"asin": " "}, fixture_dir=FIXTURES)["ok"])
        self.assertTrue(handle_tracking_command("tracking.remove", {"asin": "B1", "dry_run": True}, fixture_dir=FIXTURES)["ok"])
        self.assertEqual(redact_value(("secret",), secret_values=["secret"]), ["[REDACTED]"])
        self.assertEqual(build_agent_schema_snapshot({"x": object()})["x"], "object")
        self.assertEqual(estimate_request_budget("products.get", {"asin": object()}).estimated_tokens, 1)
        self.assertEqual(
            build_research_brief({"payload": {"agent_brief": {"one_line": "one"}}})["decision_summary"]["items"][0]["one_line"],
            "one",
        )
        graph = {"nodes": [{"id": "x"}], "entity_counts": {}}
        _apply_diff_resolutions(graph, node_variants={"x": []}, variant_sources={"x": []}, diff={"resolutions": [{"id": "x"}]})
        self.assertEqual(graph["nodes"][0]["id"], "x")

    def test_last_resource_and_conversion_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs/schema").mkdir(parents=True)
            (root / "docs/schema/products.agent-view.schema.json").write_text("{}", encoding="utf-8")
            (root / "docs/schema/workflow-runtime-contract.schema.json").write_text("{}", encoding="utf-8")
            (root / "docs/schema/risk-taxonomy.schema.json").write_text("{}", encoding="utf-8")
            (root / "evidence/tasks").mkdir(parents=True)
            (root / "evidence/manifest.csv").write_text(
                "logical_path,title,status,updated_at,summary\n"
                "evidence/tasks/task.md,Task,done,2026-05-11,summary\n",
                encoding="utf-8",
            )
            (root / "evidence/tasks/task.md").write_text("# task\n", encoding="utf-8")
            (root / "keepa_cli/fixtures").mkdir(parents=True)
            (root / "tests/fixtures").mkdir(parents=True)
            (root / "tests/fixtures/local.json").write_text("{}", encoding="utf-8")
            (root / ".zread/wiki/versions/v1").mkdir(parents=True)
            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            (root / ".zread/wiki/versions/v1/wiki.json").write_text(json.dumps({"id": "v1", "pages": [{"file": "../bad.md", "slug": "bad"}]}), encoding="utf-8")

            self.assertEqual(read_mcp_resource("keepa://fixtures/", root=root)["mimeType"], "text/csv")
            self.assertEqual(read_mcp_resource("keepa://fixtures/local.json", root=root)["mimeType"], "application/json")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://cache-key/", root=root)
            with mock.patch("keepa_cli.agent.resources.run_command" if False else "keepa_cli.service.run_command", return_value={"ok": True, "data": "bad"}):
                with self.assertRaises(ValueError):
                    read_mcp_resource("keepa://workflow/" + text_to_resource_token(json.dumps({"name": "category-research"})) + "/policy", root=root)
            self.assertEqual(json.loads(read_mcp_resource("keepa://evidence/recent", root=root)["text"])["items"][0]["logical_path"], "evidence/tasks/task.md")
            with mock.patch("keepa_cli.agent.resources._is_relative_to", return_value=False):
                with self.assertRaises(ValueError):
                    read_mcp_resource("keepa://evidence/" + text_to_resource_token("evidence/tasks/task.md"), root=root)
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://zread/wiki/page/bad", root=root)

            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            with mock.patch("keepa_cli.agent.resources._is_relative_to", return_value=False):
                with self.assertRaises(ValueError):
                    read_mcp_resource("keepa://zread/wiki/current", root=root)
            (root / "data.csv").write_text("a,b\n", encoding="utf-8")
            self.assertEqual(read_mcp_resource(path_to_resource_uri(root / "data.csv", kind="output"), root=root)["mimeType"], "text/csv")

        with mock.patch("keepa_cli.agent.resources.Path.exists", return_value=False):
            payload = json.loads(read_mcp_resource("keepa://graphs/root")["text"])
            self.assertEqual(payload["sources_scanned"]["fixture_files"], 0)
        self.assertEqual(json.loads(read_mcp_resource("keepa://evidence/recent", root=Path(tempfile.mkdtemp()))["text"])["items"], [])
        with mock.patch("keepa_cli.agent.resources.Path.exists", return_value=False):
            self.assertEqual(json.loads(read_mcp_resource("keepa://asin/B1/fixture")["text"])["match_count"], 0)
        with self.assertRaises(ValueError):
            read_mcp_resource("keepa://prompts/missing")

        params, resolution = resolve_workflow_arguments("keepa.reports_build", {"resource_uri": "keepa://research/b64:" + text_to_resource_token("k")}, session_cache={"k": {"data": {"rows": [{"asin": "B1"}]}}})
        self.assertTrue(resolution["temp_paths"])
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"workflow_context": {"outputs": ["keepa://missing"]}}, session_cache={})
        self.assertIn("error", resolution["resolved"][0])
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"workflow_context": {"outputs": [["keepa://missing"]]}}, session_cache={})
        self.assertIn("error", resolution["resolved"][0])
        with mock.patch("keepa_cli.agent.resources.read_mcp_resource", side_effect=ValueError("boom")):
            params, resolution = resolve_workflow_arguments("keepa.products_get", {"resource_uris": ["keepa://graphs/missing"]}, session_cache={})
            self.assertIn("boom", resolution["resolved"][0]["error"])
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"workflow_context": {"artifacts": ["keepa://missing"]}}, session_cache={})
        self.assertIn("error", resolution["resolved"][0])
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"resource_uri": "keepa://research/missing"}, session_cache={})
        self.assertEqual(resolution["resolved"][0]["found"], False)
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"resource_uri": "keepa://research/b64:" + text_to_resource_token("k")}, session_cache={"k": {"data": {"rows": [{"asin": "B9"}]}}})
        self.assertEqual(params["asin"], "B9")
        params, resolution = resolve_workflow_arguments("keepa.products_get", {"resource_uri": "keepa://research/b64:" + text_to_resource_token("k")}, session_cache={"k": {"data": {"asin": "B8"}}})
        self.assertEqual(params["asin"], "B8")
        self.assertEqual(resolve_workflow_arguments("keepa.tracking_get", {})[1]["missing_inputs"][0]["field"], "asin")
        self.assertEqual(resolve_workflow_arguments("keepa.research_graph_merge", {})[1]["missing_inputs"][0]["field"], "graph")
        self.assertEqual(resolve_workflow_arguments("keepa.research_brief_export", {})[1]["missing_inputs"][0]["field"], "payload")
        self.assertEqual(resolve_workflow_arguments("keepa.reports_build", {})[1]["missing_inputs"][0]["field"], "input")
        self.assertEqual(resolve_workflow_arguments("keepa.products_compare", {"asin": []})[1]["missing_inputs"][0]["field"], "asin")

        self.assertEqual(_product_rows_for_figures({"data": {"body": {"products": ["skip", {"asin": "B2"}]}}})[0]["asin"], "B2")
        self.assertEqual(_product_metric_row({"asin": "B3"})["asin"], "B3")
        self.assertEqual(_product_rows_for_figures({"products": ["skip", {"asin": "B4"}]})[0]["asin"], "B4")
        self.assertEqual(_product_rows_for_figures({"data": {"products": []}, "products": ["skip", {"asin": "B5"}]})[0]["asin"], "B5")
        self.assertEqual(_raw_temporal_windows({"csv": ["skip"]}), {})
        self.assertEqual(_raw_temporal_windows({"temporal_features": {"series": {"new": "skip", "rank": {"windows": {"x": "skip"}}}}}), {})
        with mock.patch("keepa_cli.figures._temporal_features", return_value={"series": {"new": "skip", "rank": {"windows": {"x": "skip"}}}}):
            self.assertEqual(_raw_temporal_windows({"csv": []}), {})
        self.assertEqual(_raw_temporal_windows({"csv": [["skip"]]}) or {}, {})
        self.assertEqual(_raw_temporal_windows(_csv_product())["recent_7d"]["series"]["new"]["change_pct"], -20.0)
        self.assertEqual(_window_heatmap_for_figures({"temporal_features": {"series": {"new": {"windows": {"recent_7d": {"change_pct": "bad"}}}}}}), [])
        self.assertIn("No temporal windows", _panel_window_heatmap([{"series": "new"}], x=0, y=0, w=300, h=200))
        self.assertIn("Price / rank history", _panel_history_lines([{"asin": "B1", "name": "new", "points": [{"value": 1}]}], x=0, y=0, w=650, h=300))
        self.assertIn("history small multiples", _panel_history_small_multiples([{"asin": "B1", "series": [{"metric": "new", "normalized_points": [{"x": 0, "y": 0}]}]}], x=0, y=0, w=650, h=300))
        self.assertIsNone(_num({"bad": True}))
        self.assertEqual(extract_history_rows({"asin": "B1", "csv": [[]]}, "amazon"), [])
        self.assertEqual(extract_history_rows({"asin": "B1", "csv": [[1, -1]]}, "amazon", include_missing=True)[0]["value"], None)
        self.assertEqual(extract_history_rows({"asin": "B1", "csv": []}, "amazon"), [])
        self.assertEqual(extract_history_rows({"asin": "B1", "csv": [[1, -1]]}, "amazon"), [])
        self.assertTrue(handle_category_command("categories.products", {"category": "172282", "fixture": "bestsellers_home.json"}, fixture_dir=FIXTURES)["ok"])
        with mock.patch("keepa_cli.commands.categories.client") as client_factory:
            client_factory.return_value.request.return_value = {"ok": True, "data": "bad"}
            self.assertTrue(handle_category_command("categories.products", {"category": "172282", "yes": True}, fixture_dir=FIXTURES)["ok"])
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_payload = Path(temp_dir) / "cache.json"
            cache_payload.write_text(json.dumps({"data": {"cache_provenance": {"cache_hit": True, "source": "sqlite"}}}), encoding="utf-8")
            self.assertEqual(explain_cache(input_path=str(cache_payload), command="products.get", endpoint=None)["source"], "sqlite")
            input_path = Path(temp_dir) / "input.json"
            input_path.write_text(json.dumps({"data": {"products": [{"asin": "B1"}]}}), encoding="utf-8")
            with mock.patch("keepa_cli.workflows.build_research_figures", return_value={"figures": ["skip"], "schema_version": "x"}):
                self.assertEqual(_report_figure_info(input_path=str(input_path), out=None, title="T", figure=None, figures_dir=str(Path(temp_dir) / "figures"), figure_set="all", enabled=True)["figures"], [])

        self.assertFalse(handle_category_command("categories.products", {"category": "172282", "limit": -1}, fixture_dir=FIXTURES)["ok"])
        self.assertFalse(selection_query("finder.query", "/query", {"selection": {}, "domain": "US"}, fixture_dir=FIXTURES)["ok"])
        self.assertIn("category", resolve_research_target({"query": "category 172282", "hint_type": "category"})["next_actions"][0]["params"])
        self.assertTrue(_merge_research_graphs([{"research_graph": {"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "b", "type": "rel"}]}}])["edges"])
        self.assertTrue(_merge_research_graphs([{"research_graph": {"nodes": [{"id": "a"}], "edges": ["skip"]}}])["nodes"])
        self.assertIs(build_research_brief({"payload": {}, "graph": {"root": "g"}})["entity_graph_summary"]["root"], "g")
        values: dict[str, object] = {}
        _merge_values(values, {"category_ids": "172282"})
        self.assertEqual(values["category_ids"], "172282")
        self.assertEqual(_first("B1"), "B1")


if __name__ == "__main__":
    unittest.main()
