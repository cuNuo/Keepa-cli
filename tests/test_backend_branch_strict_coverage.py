"""
tests/test_backend_branch_strict_coverage.py
文件说明：补齐后端 branch coverage 的严格分支测试。
主要职责：覆盖 line coverage 无法暴露的条件、循环与 fallback 分支。
依赖边界：仅使用 fixture、fake opener、mock 与临时目录，不访问真实 Keepa API。
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from keepa_cli.agent import mcp as mcp_module
from keepa_cli.agent.mcp import _jsonrpc_error, handle_mcp_message, iter_mcp_output, iter_mcp_stream
from keepa_cli.agent.resources import build_resource_manifest, compact_payload_for_mcp, path_to_resource_uri, read_mcp_resource, text_to_resource_token
from keepa_cli.agent.session import AgentSession, _consumed_tokens
from keepa_cli.agent.tools import _integer_schema, get_tool_definition, tool_params_to_command_params
from keepa_cli.agent.workflow_resolver import _collect_workflow_context_references, _merge_values, resolve_workflow_arguments
from keepa_cli.agent_eval import _payload_for_prepared_spec
from keepa_cli.cassettes import promote_cassette_fixture
from keepa_cli.cache import SQLiteResponseCache, build_response_cache_key
from keepa_cli.client import KeepaClient
from keepa_cli.commands.categories import categories_finder_selection, categories_products
from keepa_cli.commands.categories import client as categories_client
from keepa_cli.commands.products import product_get, product_search, products_compare
from keepa_cli.commands.tracking import handle_tracking_command
from keepa_cli.commands.workflows import handle_workflow_command
from keepa_cli.commands.tracking import sanitize_webhook_payload
from keepa_cli.config import set_api_token, set_language, set_max_tokens_per_request
from keepa_cli.figures import _panel_metric_small_multiples, _product_rows_for_figures, _temporal_signal_bars, _window_heatmap_for_figures, _window_sort_key as figure_window_sort_key
from keepa_cli.high_value import _result_count, write_body_output
from keepa_cli.history_export import extract_history_rows, normalize_series_names
from keepa_cli.product_view import (
    _agent_brief,
    _aplus,
    _brief_line,
    _data_quality,
    _data_quality_notes,
    _dedupe_graph_edges,
    _dedupe_graph_nodes,
    _merge_research_graphs,
    _next_actions,
    _research_graph,
    _risk_taxonomy,
    _video_samples,
    _window_change,
    _window_sort_key as product_window_sort_key,
)
from keepa_cli.redaction import redact_value
from keepa_cli.research_brief import _first_mapping, _risk_summary, build_research_brief
from keepa_cli.research_context import _unique
from keepa_cli.research_graph import (
    _asins_from_body,
    _choose_variant,
    _dedupe_graph_edges as rg_dedupe_edges,
    _dedupe_graph_nodes as rg_dedupe_nodes,
    _node_conflicts,
    _selection_values,
    _source_lookup,
    build_research_graph,
    graph_diagnostics,
    graph_diff,
    graph_edge,
    graph_node,
    merge_research_graphs,
)
from keepa_cli.service import run_command
from keepa_cli.transport import CassetteResponse
from keepa_cli.transport import _selected_headers
from keepa_cli.workflows import _figures_markdown, _research_graph_markdown, _workflow_artifacts, _workflow_inputs, build_batch_asins, build_report, build_workflow_plan, explain_cache


FIXTURES = Path("tests/fixtures")


class HeaderlessResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "HeaderlessResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class HeaderResponse(HeaderlessResponse):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = headers or {}

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)


class BranchStrictCoverageTests(unittest.TestCase):
    def test_mcp_session_and_tool_argument_branch_edges(self) -> None:
        self.assertNotIn("data", _jsonrpc_error("1", -1, "boom")["error"])
        self.assertIn("tools", handle_mcp_message(json.dumps({"id": 1, "method": "tools/list", "params": {"groups": ["research"]}}))["result"])
        self.assertIn("tools", handle_mcp_message(json.dumps({"id": 2, "method": "tools/list", "params": {"toolsets": ["all"]}}))["result"])
        self.assertEqual(iter_mcp_output("\n" + json.dumps({"id": 3, "method": "notifications/initialized"}) + "\n"), [])
        self.assertEqual(list(iter_mcp_stream(["\n", json.dumps({"id": 4, "method": "notifications/initialized"})])), [])

        session = AgentSession(runner=lambda command, params: {"ok": True, "command": command, "data": "text", "token_bucket": {}})
        response = handle_mcp_message(
            json.dumps({"id": 5, "method": "tools/call", "params": {"name": "doctor", "arguments": {"resource_uri": "keepa://research/missing"}}}),
            session=session,
        )
        self.assertIn("error", response)

        self.assertEqual(_consumed_tokens({"token_bucket": {}}, {"estimated_tokens": 7}), (7, "estimated_fallback"))
        self.assertEqual(_consumed_tokens({}, {"estimated_tokens": 3}), (3, "estimated_fallback"))
        no_cache_session = AgentSession(runner=lambda command, params: {"ok": True, "command": command, "data": {"value": 1}, "token_bucket": {}})
        first = no_cache_session.execute("doctor", {}, tool="doctor", use_cache=False)
        second = no_cache_session.execute("doctor", {}, tool="doctor", use_cache=False)
        self.assertFalse(first["cache_hit"])
        self.assertFalse(second["cache_hit"])
        self.assertNotIn("doctor", no_cache_session.cache)

        payload = {"ok": True, "data": {"provenance": []}}
        AgentSession._attach_mcp_provenance(payload, tool="doctor", cache_key="k", cache_hit=False)
        self.assertEqual(payload["data"]["provenance"], [])

        self.assertEqual(_integer_schema("number"), {"type": "integer", "description": "number"})
        tool = get_tool_definition("products_get")
        self.assertEqual(tool_params_to_command_params(tool, {"view": "raw"})["view"], "raw")
        workflow_session = AgentSession(runner=lambda command, params: {"ok": True, "command": command, "data": "not-dict", "token_bucket": {}})
        workflow_call = handle_mcp_message(
            json.dumps({"id": 6, "method": "tools/call", "params": {"name": "products_get", "arguments": {"resource_uri": "cache-key"}}}),
            session=workflow_session,
        )
        self.assertIn("result", workflow_call)
        resolved_session = AgentSession(runner=lambda command, params: {"ok": True, "command": command, "data": "not-dict", "token_bucket": {}})
        resolved_call = handle_mcp_message(
            json.dumps({"id": 7, "method": "tools/call", "params": {"name": "products_get", "arguments": {"artifact": {"payload": {"data": {"products": [{"asin": "B1"}]}}}}}}),
            session=resolved_session,
        )
        self.assertIn("result", resolved_call)

    def test_resource_compaction_and_graph_audit_branch_edges(self) -> None:
        self.assertIsNone(build_resource_manifest({"data": {"output": {"format": "json", "size_bytes": 1}}}))
        with tempfile.TemporaryDirectory() as temp_dir:
            path_one = Path(temp_dir) / "one.json"
            path_two = Path(temp_dir) / "two.json"
            path_one.write_text("{}", encoding="utf-8")
            path_two.write_text("{}", encoding="utf-8")
            manifest = build_resource_manifest({"outputs": [{"path": str(path_one), "format": "json", "size_bytes": 2}, {"path": "", "format": "json", "size_bytes": 0}, {"path": str(path_two), "format": "json", "size_bytes": 2}]})
            self.assertEqual(manifest["resource_count"], 3)
            with mock.patch("keepa_cli.agent.resources._collect_file_resources", side_effect=lambda value, resources, path_stack: resources.append({"path": ""})):
                self.assertIsNone(build_resource_manifest({"outputs": []}))
        compact = compact_payload_for_mcp({"ok": True, "meta": {"path": "x", "format": "json", "size_bytes": 1}})
        self.assertIn("mcp_resource_manifest", compact)
        compact = compact_payload_for_mcp(
            {
                "ok": True,
                "data": {
                    "rows": [{"asin": "B1", "risk_taxonomy": {"codes": ["data_missing"]}, "research_graph": {"nodes": [], "edges": [], "entity_counts": {}}}, "skip"],
                    "products": [{"identity": {"asin": "B2"}, "agent_brief": {"one_line": "x"}, "evidence_index": {}, "research_graph": {"nodes": [], "edges": [], "entity_counts": {}}}, "skip"],
                },
            }
        )
        self.assertIn("rows", compact["data"])
        self.assertIn("products", compact["data"])
        self.assertEqual(read_mcp_resource("keepa://graphs/root", session_cache={"bad": "skip"})["mimeType"], "application/json")
        compact_plain = compact_payload_for_mcp({"ok": True, "data": {"rows": [{"asin": "B1"}], "products": [{"identity": {"asin": "B2"}}]}})
        self.assertEqual(compact_plain["data"]["rows"][0]["asin"], "B1")
        self.assertEqual(compact_plain["data"]["products"][0]["identity"]["asin"], "B2")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "payload.json"
            output_path.write_text("{}", encoding="utf-8")
            compact_with_resource = compact_payload_for_mcp(
                {
                    "ok": True,
                    "data": {
                        "output": {"path": str(output_path), "format": "json", "size_bytes": output_path.stat().st_size},
                        "rows": [{"asin": "B1"}],
                        "products": [{"identity": {"asin": "B2"}}],
                    },
                }
            )
            self.assertNotIn("risk_taxonomy", compact_with_resource["data"]["rows"][0])
            self.assertNotIn("agent_brief", compact_with_resource["data"]["products"][0])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "evidence/tasks").mkdir(parents=True)
            logical = "evidence/tasks/task.md"
            (root / "evidence/manifest.csv").write_text(f"logical_path,title,status,updated_at,summary\n{logical},Task,done,2026-05-11,summary\n", encoding="utf-8")
            (root / logical).write_text("# task\n", encoding="utf-8")
            token = text_to_resource_token(logical)
            self.assertIn("# task", read_mcp_resource(f"keepa://evidence/{token}", root=root)["text"])
            root_without_manifest = Path(temp_dir) / "no-manifest"
            (root_without_manifest / "evidence/tasks").mkdir(parents=True)
            (root_without_manifest / logical).write_text("# task\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_mcp_resource(f"keepa://evidence/{token}", root=root_without_manifest)

    def test_client_transport_and_live_request_branch_edges(self) -> None:
        client = KeepaClient(opener=lambda request, timeout: HeaderlessResponse(json.dumps({"tokensLeft": 4, "tokensConsumed": 0}).encode("utf-8")))
        payload = client.request(command="request.get", method="GET", path="/token", params={"key": "K" * 64})
        self.assertTrue(payload["ok"])

        body = gzip.compress(json.dumps({"tokensLeft": 4}).encode("utf-8"))
        with self.assertRaises(ValueError):
            KeepaClient._decode_response_body(HeaderResponse(body, headers={"Content-Encoding": ""}))
        self.assertEqual(KeepaClient._decode_response_body(HeaderlessResponse(json.dumps({"ok": True}).encode("utf-8")))["ok"], True)
        self.assertEqual(_selected_headers(HeaderlessResponse(b"{}")), {})

        error = urllib.error.HTTPError("https://example.invalid", 400, "Bad", {}, None)
        self.assertEqual(KeepaClient._http_error_message(error, {"error": {"type": "bad_request"}}), "bad_request")
        self.assertEqual(KeepaClient._http_error_message(error, {"error": {"message": ""}}), str(error))

        client_429_no_wait = KeepaClient(
            opener=lambda request, timeout: (_ for _ in ()).throw(urllib.error.HTTPError("u", 429, "Too Many", {}, None)),
            sleeper=lambda seconds: None,
        )
        self.assertFalse(client_429_no_wait.request(command="request.get", method="GET", path="/x", params={"key": "K" * 64})["ok"])
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = SQLiteResponseCache(Path(temp_dir) / "responses.sqlite")
            cache_key = build_response_cache_key(method="GET", endpoint="/product", params={"asin": "B1"}, json_body=None)
            request_payload = {"method": "GET", "endpoint": "/product", "params_redacted": {"asin": "B1"}}
            cache.set(
                cache_key=cache_key,
                method="GET",
                endpoint="/product",
                params={"asin": "B1"},
                request=request_payload,
                body={"products": []},
                token_bucket={"estimated": {"estimated_tokens": 1}},
                ttl_seconds=60,
            )
            cached_payload = KeepaClient(response_cache=cache).request(command="products.get", method="GET", path="/product", params={"asin": "B1", "key": "K" * 64})
            self.assertTrue(cached_payload["token_bucket"]["cache_hit"])
            self.assertNotIn("cached_tokens_consumed", cached_payload["token_bucket"])

    def test_command_and_config_branch_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "selection.json"
            self.assertTrue(categories_finder_selection({"category": "172282", "out": out})["ok"])
            self.assertTrue(out.exists())
            local_selection = Path("selection-local.json")
            self.assertTrue(categories_finder_selection({"category": "172282", "out": str(local_selection)})["ok"])
            local_selection.unlink(missing_ok=True)

            with mock.patch("keepa_cli.commands.products.client") as client_factory:
                client_factory.return_value.request.return_value = {"ok": False, "command": "products.get", "error": {"kind": "x"}}
                self.assertFalse(product_get({"asin": "B1", "agent_view": True}, FIXTURES)["ok"])
                self.assertFalse(products_compare({"asin": ["B1"]}, FIXTURES)["ok"])

            with mock.patch("keepa_cli.commands.products.client") as client_factory:
                client_factory.return_value.request.return_value = {"ok": True, "command": "products.get", "data": "bad"}
                self.assertTrue(product_get({"asin": "B1", "agent_view": True}, FIXTURES)["ok"])
                self.assertTrue(products_compare({"asin": ["B1"]}, FIXTURES)["ok"])
            with mock.patch("keepa_cli.commands.products.write_body_output", return_value={"path": "raw.json"}):
                with mock.patch("keepa_cli.commands.products.build_agent_product_view", return_value={"raw": []}):
                    with mock.patch("keepa_cli.commands.products.client") as client_factory:
                        client_factory.return_value.request.return_value = {"ok": True, "command": "products.get", "data": {"body": {"products": []}}}
                        self.assertTrue(product_get({"asin": "B1", "agent_view": True, "out": "raw.json"}, FIXTURES)["ok"])

            self.assertFalse(product_search({"term": ""}, FIXTURES)["ok"])
            webhook_payload = handle_tracking_command("tracking.webhook", {"url": 123, "dry_run": True}, fixture_dir=FIXTURES)
            self.assertTrue(webhook_payload["ok"])
            self.assertEqual(webhook_payload["request"]["params_redacted"]["url"], "123")
            no_url_redaction = sanitize_webhook_payload({"request": {"params_redacted": {"url": 123}}})
            self.assertEqual(no_url_redaction["request"]["params_redacted"]["url"], 123)
            self.assertTrue(handle_workflow_command("audit.cost", {"commands": [{"command": "products.get", "params": {"asin": "B1"}}]})["ok"])

            token = "A" * 64
            dry_token = set_api_token(token, Path(temp_dir) / "cfg.toml", dry_run=True)
            self.assertTrue(dry_token["dry_run"])
            dry_lang = set_language("zh", Path(temp_dir) / "cfg.toml", dry_run=True)
            self.assertTrue(dry_lang["dry_run"])
            self.assertTrue(set_language("en", Path(temp_dir) / "cfg.toml", dry_run=False)["written"])
            dry_max = set_max_tokens_per_request(7, Path(temp_dir) / "cfg.toml", dry_run=True)
            self.assertTrue(dry_max["dry_run"])
            with mock.patch("keepa_cli.commands.categories.client") as client_factory:
                client_factory.return_value.request.return_value = {"ok": True, "data": {"body": {"bestSellersList": {"asinList": ["B1", "B2"], "categoryId": "172282"}}}}
                hydrated = categories_products({"category": "172282", "yes": True, "hydrate_top": 1}, FIXTURES)
                self.assertTrue(hydrated["ok"])
                self.assertTrue(hydrated["data"]["hydration"]["enabled"])
            original_categories_client = categories_client
            try:
                with mock.patch("keepa_cli.commands.categories.client") as client_factory:
                    client_factory.return_value.request.return_value = {"ok": True, "data": {"body": {"bestSellersList": {"asinList": ["B1"], "categoryId": "172282"}}}}
                    with mock.patch("keepa_cli.commands.categories.product_get", return_value={"ok": True, "data": {"products": []}}):
                        no_fixture_hydrated = categories_products({"category": "172282", "yes": True, "hydrate_top": 1}, FIXTURES)
                        self.assertEqual(no_fixture_hydrated["data"]["hydration"]["hydrated_count"], 0)
            finally:
                self.assertIs(categories_client, original_categories_client)

    def test_high_value_service_and_workflow_branch_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            self.assertEqual(_result_count({"sellers": {"A": {}}}), 1)
            self.assertEqual(_result_count({"bestSellersList": {"asinList": "bad"}}), 1)
            self.assertEqual(write_body_output({"body": []}, temp / "out.json")["result_count"], 0)
            local_body_output = Path("body-local.json")
            self.assertEqual(write_body_output({"body": {"products": []}}, local_body_output)["result_count"], 0)
            local_body_output.unlink(missing_ok=True)

            asin_file = temp / "asins.txt"
            asin_file.write_text("B1\n\nB2\n", encoding="utf-8")
            batch = build_batch_asins(asin_file=str(asin_file), domain="US", dry_run=True, fixture=None, out=None)
            self.assertNotIn("output", batch)

            graph = {
                "root": "root",
                "nodes": [],
                "edges": [],
                "diagnostics": {"duplicate_node_count": 0, "orphan_node_count": 0, "conflict_count": 0},
            }
            input_path = temp / "graph.json"
            input_path.write_text(json.dumps(graph), encoding="utf-8")
            report = build_report(input_path=str(input_path), output_format="markdown", out=None, title="T", embed_figures=False)
            self.assertNotIn("### Entities", report["content"])
            json_report = build_report(input_path=str(input_path), output_format="json", out=None, title="T", embed_figures=False)
            self.assertNotIn("figures", json_report["content"])

            figure_file = temp / "figure.svg"
            figure_file.write_text("<svg></svg>", encoding="utf-8")
            json_report_with_figures = build_report(input_path=str(input_path), output_format="json", out=None, title="T", figure=str(figure_file), embed_figures=True)
            self.assertIn("figures", json_report_with_figures["content"])
            self.assertNotIn("MCP resource", _figures_markdown({"figures": [{"name": "x", "path": "x.svg"}]}))

            direct_cache = temp / "cache.json"
            direct_cache.write_text(json.dumps({"cache_provenance": {"source": "direct"}}), encoding="utf-8")
            self.assertEqual(explain_cache(input_path=str(direct_cache), command=None, endpoint=None)["source"], "direct")
            self.assertEqual(explain_cache(input_path=None, command="products.get", endpoint="x")["source"], "unknown")
            self.assertIn("tracking_list", build_workflow_plan(name="tracking-audit", term=None, asin="B1", domain="US", goal="audit", hydrate_top=0)["artifacts"])
            self.assertIn("asin", build_workflow_plan(name="tracking-audit", term=None, asin="B1", domain="US", goal="audit", hydrate_top=0)["workflow_inputs"])
            self.assertIn("graph_inputs", build_workflow_plan(name="report-research", term=None, asin=None, domain="US", goal="report", hydrate_top=0)["workflow_inputs"])
            self.assertIn("merged_graph", build_workflow_plan(name="report-research", term=None, asin=None, domain="US", goal="report", hydrate_top=0)["artifacts"])

            out_graph = temp / "graph-out.json"
            graph_payload = {
                "research_graph": build_research_graph(
                    root="g",
                    nodes=[graph_node("g", "research_graph", "G"), graph_node("p", "product", "P")],
                    edges=[graph_edge("g", "p", "contains_product", evidence_path="unit.graph")],
                )
            }
            graph_input = temp / "graph-input.json"
            graph_input.write_text(json.dumps(graph_payload), encoding="utf-8")
            self.assertTrue(run_command("research_graph.merge", {"input": str(graph_input), "out": str(out_graph)})["ok"])
            self.assertTrue(run_command("research_graph.merge", {"graph": [graph_payload, "skip"]})["ok"])
            self.assertTrue(run_command("research_graph.merge", {"input": str(graph_input), "out": "graph-local.json"})["ok"])
            Path("graph-local.json").unlink(missing_ok=True)
            self.assertTrue(run_command("cassettes.promote-and-verify", {"input": str(graph_input), "name": "unit", "dry_run": True, "run_eval": True, "no_manifest": True})["ok"])
            self.assertTrue(run_command("cassettes.promote-and-verify", {"input": str(graph_input), "name": "unit", "dry_run": True, "no_manifest": True})["ok"])
            self.assertTrue(run_command("sellers.get", {"seller": "S1", "fixture": "seller_A2L77EE7U53NWQ.json"}, fixture_dir=FIXTURES)["ok"])
            self.assertTrue(run_command("bestsellers.get", {"category": "172282", "fixture": "bestsellers_home.json"}, fixture_dir=FIXTURES)["ok"])
            self.assertTrue(run_command("topsellers.list", {"fixture": "topsellers_US.json"}, fixture_dir=FIXTURES)["ok"])
            with mock.patch("keepa_cli.service._client") as service_client:
                service_client.return_value.request.return_value = {"ok": True, "data": "not-dict"}
                self.assertTrue(run_command("sellers.get", {"seller": "S1"}, fixture_dir=FIXTURES)["ok"])
                self.assertTrue(run_command("bestsellers.get", {"category": "172282", "yes": True}, fixture_dir=FIXTURES)["ok"])
                self.assertTrue(run_command("topsellers.list", {"yes": True}, fixture_dir=FIXTURES)["ok"])
            out_brief = temp / "brief-out.json"
            self.assertTrue(run_command("research_brief.export", {"payload": {"agent_brief": {"one_line": "x"}}, "out": str(out_brief)})["ok"])
            self.assertTrue(run_command("research_brief.export", {"payload": {"agent_brief": {"one_line": "x"}}, "out": "brief-local.json"})["ok"])
            Path("brief-local.json").unlink(missing_ok=True)

    def test_product_view_figure_and_graph_helper_branch_edges(self) -> None:
        merged_empty = _merge_research_graphs([{"research_graph": {"nodes": ["skip"], "edges": [{"source": "", "target": "b", "type": "rel"}]}}])
        self.assertEqual(merged_empty["node_count"], 0)
        self.assertEqual(_aplus({"aPlus": [{"module": [{"bad": True}]}]}, media_limit=2)["module_count"], 1)
        self.assertIsNone(_window_change([{"keepa_minute": 1, "value": 10}], days=7))
        self.assertIsNone(_window_change([{"keepa_minute": 1, "value": 10}, {"keepa_minute": 100000, "value": 12}], days=1))
        self.assertIsNotNone(_window_change([{"keepa_minute": 1, "value": 10}, {"keepa_minute": 100000, "value": 12}], days=999))
        self.assertIsNotNone(_window_change([{"keepa_minute": 100000, "value": 10}, {"keepa_minute": 100001, "value": 12}], days=-1))
        self.assertEqual(_aplus({"aPlus": [{"module": {"not": "list"}}]}, media_limit=2)["module_count"], 0)
        self.assertEqual(_video_samples(["skip", {"title": "T", "url": "u"}], 2)[0]["title"], "T")
        self.assertIn("offer detail", _data_quality_notes({}, {"history_summary": {"available": True}}, [])[0])

        quality_view = {
            "pricing": {"current": {"new": 1}},
            "demand": {"monthly_sold": 10},
            "rating": {"rating": 4.5},
            "offers": {"total_offer_count": 1},
            "aplus": {"available": True},
            "history_summary": {"available": True},
            "raw_field_presence": {"offers": True, "csv": True, "stats": True, "images": True},
        }
        quality = _data_quality({"csv": []}, quality_view)
        self.assertEqual(quality["confidence"], "high")
        self.assertEqual(_next_actions({"identity": {"asin": "B1"}, "data_quality": {"missing": []}}), [])
        self.assertIn("B1", _agent_brief({"identity": {"asin": "B1", "title": "Title"}})["one_line"])
        self.assertIn("Title", _agent_brief({"identity": {"title": "Title"}})["one_line"])
        self.assertEqual(_brief_line({"asin": "B1"}, {}), "B1")
        self.assertIn("history.csv", _risk_taxonomy({"data_quality": {"missing": ["history.csv"]}})["items"][0]["field"])
        no_risks = _risk_taxonomy({"data_quality": {"missing": []}, "pricing": {"buy_box": {"seller_id": "S"}}, "selection_signals": {"price_stability": {}}})
        self.assertEqual(no_risks["risk_count"], 0)

        graph = _research_graph(
            {
                "identity": {"asin": "B1", "title": "T", "brand": "M", "manufacturer": "M"},
                "variations": {},
                "category": {"category_tree": [{"id": "1", "name": "A"}]},
                "pricing": {"buy_box": {"seller_id": "S1"}},
            }
        )
        self.assertTrue(graph["nodes"])
        graph_without_brand_or_category = _research_graph({"identity": {"asin": "B3", "title": "T"}})
        self.assertEqual(graph_without_brand_or_category["entity_counts"]["product"], 1)
        self.assertEqual(_research_graph({"identity": {"asin": "B4"}, "category": {"category_tree": [{"id": "", "name": "skip"}]}})["entity_counts"]["product"], 1)
        self.assertEqual(_dedupe_graph_nodes([{"id": ""}, {"id": "a"}])[0]["id"], "a")
        self.assertEqual(_dedupe_graph_edges([{"source": "a", "target": "", "type": "x"}, {"source": "a", "target": "b", "type": "x"}])[0]["target"], "b")
        self.assertEqual(product_window_sort_key("recent_xd"), 10**9)

        self.assertEqual(_product_rows_for_figures("skip"), [])
        self.assertEqual(_product_rows_for_figures({"data": {"rows": ["skip"]}}), [])
        with mock.patch("keepa_cli.figures._raw_temporal_windows", return_value={"recent_7d": {"series": {"new": {"change_pct": 1}}}}):
            self.assertTrue(_window_heatmap_for_figures({"asin": "B1", "csv": []}))
        with mock.patch("keepa_cli.figures._raw_temporal_windows", return_value={}):
            self.assertEqual(_window_heatmap_for_figures({"asin": "B1", "csv": []}), [])
        self.assertIn("Multi-ASIN", _panel_metric_small_multiples([{"label": "One", "points": [{"normalized_score": 0.5, "label": "p"}]}], x=0, y=0, w=300, h=180))
        self.assertIn("No fallback signals", _temporal_signal_bars([{"name": "bad", "value": "x"}], x=0, y=0, w=100, h=80))
        self.assertEqual(figure_window_sort_key("recent_xd"), 10**9)
        self.assertIn("Price trend", mcp_module._json_text({"title": "Price trend"}))

        self.assertEqual(_asins_from_body({"products": ["B1", {"asin": "B2"}]})[:2], ["B1", "B2"])
        self.assertEqual(_asins_from_body({"products": [123]}), [])
        self.assertEqual(rg_dedupe_nodes([{"id": ""}, {"id": "a", "type": "product"}])[0]["id"], "a")
        self.assertEqual(rg_dedupe_edges([{"source": "a", "target": "", "type": "x"}, {"source": "a", "target": "b", "type": "x"}])[0]["target"], "b")
        self.assertEqual(_source_lookup([{"index": 0}, {"root": "r"}])["0"]["index"], 0)
        self.assertEqual(_choose_variant([{"id": "a", "source_weight": 2}], preferred_source={"matched": True})["id"], "a")
        self.assertFalse(_node_conflicts(["skip"]))
        self.assertEqual(graph_diff({"a": [{"id": "a", "label": "A"}]})["conflict_count"], 0)
        self.assertEqual(graph_diff({"a": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]}, prefer_source="missing")["resolved_conflict_count"], 1)
        self.assertEqual(graph_diff({"a": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]}, variant_sources={"a": []})["resolutions"][0]["strategy"], "highest_source_weight")
        self.assertEqual(graph_diff({"a": [{"id": "a"}, {"id": "a"}]}, variant_sources={"a": []}, prefer_source="missing")["resolved_conflict_count"], 0)
        with mock.patch("keepa_cli.research_graph._choose_variant", return_value=None):
            self.assertEqual(graph_diff({"a": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]})["resolved_conflict_count"], 0)
        merged_skipping_non_mapping_nodes = merge_research_graphs([{"root": "r", "nodes": ["skip"], "edges": []}])
        self.assertTrue(merged_skipping_non_mapping_nodes["nodes"])
        self.assertEqual(graph_diagnostics({"root": "r", "nodes": [graph_node("a", "product", "A")], "edges": [{"source": "", "target": "", "type": "rel"}]})["orphan_node_count"], 1)
        self.assertEqual(_selection_values({"brand": None, "brandName": ""}, prefixes=("brand",)), [])
        merged = merge_research_graphs(
            [
                "skip",
                build_research_graph(root="r1", nodes=[graph_node("a", "product", "A"), graph_node("b", "product", "B")], edges=[graph_edge("a", "b", "rel", evidence_path="unit.edge")]),
                build_research_graph(root="r2", nodes=[graph_node("a", "product", "A2"), graph_node("b", "product", "B")], edges=[graph_edge("a", "b", "rel", evidence_path="unit.edge")]),
            ],
            root="root",
        )
        self.assertTrue(merged["diagnostics"]["conflict_count"])
        self.assertTrue(merge_research_graphs([{"root": "r", "nodes": [graph_node("", "product", "No id"), graph_node("a", "product", "A")], "edges": [{"source": "a", "target": "", "type": "rel"}, "skip"]}])["nodes"])

    def test_misc_branch_edges(self) -> None:
        self.assertEqual(extract_history_rows({"asin": "B1", "csv": [[1, 1, 2, 2]]}, "new"), [])
        self.assertEqual(normalize_series_names(["new", "new"]), ["new"])
        self.assertEqual(redact_value("abc", secret_values=[""]), "abc")
        self.assertEqual(_unique(["a", "a", "b"]), ["a", "b"])
        self.assertEqual(_risk_summary([{"code": "", "severity": ""}])["by_code"], {})
        self.assertEqual(_risk_summary([{"severity": ""}, {"code": ""}])["risk_count"], 2)
        self.assertEqual(_risk_summary([{"code": ""}, {"code": ""}])["by_severity"]["unknown"], 2)
        self.assertEqual(_risk_summary([{"severity": ""}, {"severity": ""}])["by_code"], {})
        self.assertEqual(_risk_summary([])["by_severity"], {})
        self.assertEqual(_risk_summary([{"severity": " "}])["by_severity"], {})
        self.assertIsNone(_first_mapping(["skip"]))
        self.assertIsNone(_first_mapping([]))
        brief = build_research_brief(
            {
                "payload": {
                    "risk_taxonomy": {"items": ["skip"], "codes": ["data_missing"], "highest_severity": "medium"},
                    "next_actions": ["skip"],
                    "agent_brief": {"recommended_next_actions": ["skip"]},
                    "external_signal_stub": {"source": "web", "signal": "ad observed"},
                }
            }
        )
        self.assertEqual(brief["risk_summary"]["by_code"]["data_missing"], 1)
        self.assertEqual(brief["external_signal_stub"]["status"], "provided")
        self.assertIn("ip_risk_inputs", brief["data_quality"]["missing"])
        action_brief = build_research_brief({"payload": {"next_actions": [{"tool": "a"}, {"tool": "b"}], "agent_brief": {"recommended_next_actions": [{"tool": "c"}]}}})
        self.assertTrue(action_brief["follow_up_plan"]["next_actions"])
        self.assertTrue(_payload_for_prepared_spec({"kind": "mcp_session", "steps": [{"method": "notifications/initialized"}]}, FIXTURES)["ok"])
        with tempfile.TemporaryDirectory() as temp_dir:
            cassette = Path(temp_dir) / "cassette.json"
            cassette.write_text(json.dumps({"body": {"products": []}}), encoding="utf-8")
            promoted = promote_cassette_fixture(cassette, name="x", tests_dir=Path(temp_dir) / "tests", package_dir=Path(temp_dir) / "pkg", manifest_path=None)
            self.assertEqual(promoted["fixture_name"], "x.json")
        self.assertEqual(CassetteResponse({"a": 1}, headers={}).getheader("missing", "d"), "d")

    def test_workflow_resolution_branch_edges(self) -> None:
        params, resolution = resolve_workflow_arguments(
            "audit_cost",
            {"params": {}, "workflow_inputs": {"skip": {"value": "keepa://graphs/missing"}, "also_skip": "x"}, "workflow_context": ["plain-ref", 123]},
            session_cache={},
        )
        self.assertEqual(params["params"], {})
        self.assertTrue(resolution["resolved"])
        plain_value_params, plain_value_resolution = resolve_workflow_arguments(
            "products_get",
            {"artifact": "keepa://graphs/missing", "workflow_inputs": {"plain": {"value": "not-a-reference"}}},
            session_cache={},
        )
        self.assertTrue(plain_value_resolution["resolved"])
        self.assertNotIn("asin", plain_value_params)
        scalar_context_params, scalar_context_resolution = resolve_workflow_arguments(
            "products_get",
            {"artifact": "keepa://graphs/missing", "workflow_context": "not-a-reference"},
            session_cache={},
        )
        self.assertTrue(scalar_context_resolution["resolved"])
        self.assertNotIn("asin", scalar_context_params)
        unsupported_params, unsupported_resolution = resolve_workflow_arguments(
            "products_get",
            {"artifact": {"unknown": "shape"}, "resource_uri": "keepa://graphs/missing"},
            session_cache={},
        )
        self.assertTrue(unsupported_resolution["resolved"])
        self.assertNotIn("asin", unsupported_params)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "payload.json"
            path.write_text(json.dumps({"data": {"products": [{"asin": "B1"}, {"asin": "B2"}]}}), encoding="utf-8")
            report_params, report_resolution = resolve_workflow_arguments("reports_build", {"artifact": {"output": {"path": str(path)}}})
            self.assertEqual(report_params["input"], str(path))
            self.assertTrue(report_resolution["resolved"])

        no_asin_params, no_asin_resolution = resolve_workflow_arguments("audit_cost", {"params": {}, "artifact": {"payload": {"note": "no asin"}}})
        self.assertNotIn("asin", no_asin_params["params"])
        self.assertTrue(no_asin_resolution["resolved"])

        nested_params, nested_resolution = resolve_workflow_arguments(
            "tracking_get",
            {"workflow_context": {"steps": {"list": {"payload": {"trackings": [{"asin": None}, "skip"]}}}}},
        )
        self.assertNotIn("asin", nested_params)
        self.assertTrue(nested_resolution["resolved"])
        existing_params, existing_resolution = resolve_workflow_arguments(
            "products_get",
            {"asin": "B0", "artifact": {"payload": {"data": {"products": [{"asin": "B1"}]}}}},
        )
        self.assertEqual(existing_params["asin"], "B0")
        self.assertTrue(existing_resolution["resolved"])
        self.assertEqual(_collect_workflow_context_references("keepa://graphs/missing"), ["keepa://graphs/missing"])
        self.assertEqual(_collect_workflow_context_references("plain"), [])
        merged_values: dict[str, object] = {}
        _merge_values(merged_values, {"category_ids": "172282"})
        _merge_values(merged_values, {"category_ids": "999"})
        self.assertEqual(merged_values["category_ids"], "172282")
        self.assertEqual(_workflow_inputs(name="unknown", term=None, asin=None, domain="US", goal="x", hydrate_top=0)["domain"]["value"], "US")
        self.assertEqual(_workflow_artifacts("unknown"), {})
        self.assertNotIn("### Entities", _research_graph_markdown({"summary": {}, "nodes": [], "edges": []}))
        self.assertNotIn("### Relationships", _research_graph_markdown({"summary": {}, "nodes": [graph_node("a", "product", "A")], "edges": []}))
        with tempfile.TemporaryDirectory() as temp_dir:
            list_payload = Path(temp_dir) / "list.json"
            list_payload.write_text(json.dumps([{"cache_provenance": {"source": "list"}}]), encoding="utf-8")
            self.assertEqual(explain_cache(input_path=str(list_payload), command=None, endpoint=None)["source"], "unknown")
        self.assertEqual(explain_cache(input_path=None, command=None, endpoint=None)["source"], "unknown")


if __name__ == "__main__":
    unittest.main()
