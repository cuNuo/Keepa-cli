"""
tests/test_backend_transform_coverage.py
文件说明：补齐后端数据转换、工作流解析和资源读取的边界覆盖。
主要职责：验证 Agent 视图、研究图谱、图表、MCP 资源和本地工作流的多场景分支。
依赖边界：仅使用合成 payload、fixture、临时目录和 session_cache，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from keepa_cli.agent.resources import path_to_resource_uri, read_mcp_resource, text_to_resource_token
from keepa_cli.agent.workflow_resolver import resolve_workflow_arguments
from keepa_cli.figures import build_research_figures_from_payload
from keepa_cli.high_value import attach_output_if_requested, load_selection, write_body_output
from keepa_cli.history_export import build_history_export_data, extract_history_rows, normalize_series_names, write_history_export
from keepa_cli.product_view import build_agent_product_view, build_product_compare_view
from keepa_cli.research_context import query_research_context, resolve_research_target
from keepa_cli.research_graph import (
    build_category_candidates_graph,
    build_category_graph,
    build_selection_graph,
    build_topsellers_graph,
    merge_research_graphs,
)
from keepa_cli.service import run_command
from keepa_cli.workflows import build_report, build_workflow_plan, explain_cache, show_template


FIXTURES = Path("tests/fixtures")


def _points(values: list[float], *, start: int = 6_000_000, step: int = 1440) -> list[dict[str, object]]:
    return [
        {"timestamp": f"2026-01-{index + 1:02d}T00:00:00Z", "keepa_minute": start + index * step, "value": value}
        for index, value in enumerate(values)
    ]


def _figure_payload() -> dict[str, object]:
    graph = build_selection_graph(
        command="finder.query",
        selection={"categories_include": ["172282"], "brand": "Acme"},
        body={"products": [{"asin": "B000000001"}, "B000000002"], "asinList": ["B000000003"]},
    )
    return {
        "data": {
            "rows": [
                {"asin": "B000000001", "title": "Metric Product", "monthly_sold": 250, "review_count": 12},
                {"identity": {"asin": "B000000002", "title": "Identity Product"}, "rating": {"review_count": 44}},
            ],
            "products": [
                {
                    "asin": "B000000003",
                    "title": "History Product",
                    "stats": {"current": [1299]},
                    "risk_taxonomy": {"codes": ["data_missing", "price_unstable"]},
                    "history_summary": {
                        "series": {
                            "new": {"unit": "currency", "point_count": 3, "last_points": _points([10, 12, 11])},
                            "sales_rank": {"unit": "rank", "point_count": 3, "last_points": _points([1000, 800, 900])},
                        }
                    },
                    "temporal_by_window": {
                        "recent_30d": {
                            "series": {
                                "new": {"change_pct": -8.5, "direction": "down", "observed_days": 30},
                                "bad": "skip",
                            }
                        },
                        "bad_window": "skip",
                    },
                    "agent_brief": {
                        "temporal_by_window": {
                            "recent_90d": {"new": {"change_pct": 15, "direction": "up", "observed_days": 90}}
                        }
                    },
                    "temporal_features": {
                        "series": {
                            "sales_rank": {
                                "windows": {
                                    "recent_30d": {"change_pct": 22, "trend_direction": "up", "observed_days": 30},
                                    "bad": "skip",
                                }
                            }
                        }
                    },
                },
                {
                    "identity": {"asin": "B000000004", "title": "Bounded Product"},
                    "bounded_history_points": {
                        "series": {
                            "new": {"unit": "currency", "point_count": 2, "last_points": _points([0, 5])},
                            "buy_box_shipping": {"unit": "currency", "point_count": 2, "last_points": _points([15, 12])},
                            "review_count": {"unit": "count", "point_count": 2, "last_points": _points([20, 25])},
                        }
                    },
                },
            ],
            "research_graph": graph,
        }
    }


def _rich_product() -> dict[str, object]:
    csv = [[] for _ in range(18)]
    csv[1] = [6_000_000, 1299, 6_001_440, 1899, 6_002_880, 999, 6_004_320, 2200]
    csv[3] = [6_000_000, 20_000, 6_001_440, 26_000, 6_002_880, 35_000, 6_004_320, 44_000]
    csv[16] = [6_000_000, 42, 6_001_440, 38]
    csv[17] = [6_000_000, 12, 6_001_440, 13]
    csv.append("not-list")
    return {
        "asin": "B000000010",
        "title": "Risky product",
        "brand": "Brand A",
        "manufacturer": "Maker B",
        "domainId": 1,
        "productGroup": "Kitchen",
        "itemTypeKeyword": "coffee-grinder",
        "parentAsin": "B000PARENT1",
        "categories": [172282],
        "categoryTree": [{"catId": 1, "name": "Root"}, "skip", {"catId": 172282, "name": "Kitchen"}],
        "salesRanks": {"172282": [6_000_000, 1000, 6_001_440, 900], "bad": [1]},
        "images": [{"l": "large.jpg", "m": "medium.jpg", "lW": 100, "lH": 200}, "plain.jpg"],
        "videos": [{"url": "video.mp4", "title": "Demo"}, "clip.mp4"],
        "aPlus": [{"module": [{"image": ("aplus.jpg",), "video": "aplus.mp4", "imageAltText": "alt", "text": ("long copy",)}]}, "skip"],
        "features": ["feature"],
        "description": "description",
        "packageLength": 10,
        "variations": [{"asin": "B000VAR001", "attributes": {"Color": "Red"}}, {"missing": True}],
        "buyBoxEligibleOfferCounts": [1, -1, 2],
        "liveOffersOrder": ["seller"],
        "monthlySoldHistory": [6_000_000, 20, 6_001_440, 30],
        "couponHistory": [6_000_000, 100, 6_001_440, -1],
        "csv": csv,
        "stats": {
            "current": [-1, 1299, -1, 44_000, -1, -1, -1, -1, -1, -1, -1, -1, 1499, -1, -1, -1, 38, 13],
            "avg30": [-1, 1599],
            "avg90": [-1, 1499],
            "min": [[6_000_000, 999]],
            "max": [[6_004_320, 2200]],
            "buyBoxPrice": 1299,
            "buyBoxShipping": 0,
            "buyBoxSellerId": "SELLER123",
            "buyBoxIsFBA": True,
            "totalOfferCount": 25,
            "retrievedOfferCount": 2,
            "offerCountFBA": 3,
            "offerCountFBM": 22,
            "salesRankDrops30": 1,
            "salesRankDrops90": 2,
        },
    }


class BackendTransformCoverageTests(unittest.TestCase):
    def test_figures_cover_nested_history_heatmap_and_empty_panels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = build_research_figures_from_payload(_figure_payload(), out_dir=temp_dir, title="覆盖图表", source_label="unit")
            empty = build_research_figures_from_payload({"data": {}}, out_dir=str(Path(temp_dir) / "empty"), title="空图表", source_label="empty")

            source = json.loads(Path(result["figures"][0]["source_data_path"]).read_text(encoding="utf-8"))
            self.assertGreaterEqual(result["data_summary"]["product_count"], 4)
            self.assertGreaterEqual(result["data_summary"]["window_heatmap_cell_count"], 3)
            self.assertEqual(source["small_multiples"][-1]["data_basis"], "bounded_history_points")
            self.assertIn("price_unstable", {item["code"] for item in source["risk_codes"]})
            history_svg = Path(next(item["path"] for item in result["figures"] if item["name"] == "history-lines")).read_text(encoding="utf-8")
            empty_svg = Path(next(item["path"] for item in empty["figures"] if item["name"] == "product-metric-comparison")).read_text(encoding="utf-8")
            self.assertIn("B000000003", history_svg)
            self.assertIn("New price", history_svg)
            self.assertIn("No product metric rows found", empty_svg)

    def test_agent_product_view_covers_risk_graph_profiles_and_helpers(self) -> None:
        product_payload = _rich_product()
        product_payload["videos"] = []
        view = build_agent_product_view(
            {"body": {"products": [product_payload, {"title": "missing asin"}]}, "offline": True, "fixture": "unit.json"},
            history_limit=2,
            temporal_windows=["1,30", "bad", 90],
            media_limit=2,
            view_profile="agent",
            fields=("identity,selection_signals", 123, "risk_taxonomy,research_graph,data_quality,next_actions,history_summary,temporal_features"),
        )
        product = view["products"][0]
        missing_graph = view["products"][1]["research_graph"]

        self.assertEqual(view["profile"], "research")
        self.assertEqual(view["raw"]["fixture"], "unit.json")
        self.assertIn("rank_declining", product["risk_taxonomy"]["codes"])
        self.assertIn("offer_competition_high", product["risk_taxonomy"]["codes"])
        self.assertIn("B000VAR001", json.dumps(product["research_graph"]))
        self.assertEqual(missing_graph["nodes"], [])
        self.assertIn("csv[18] is not a list", product["history_summary"]["warnings"])
        self.assertIn("recent_1d", product["temporal_features"]["series"]["new"]["windows"])
        self.assertIn("missing_video", product["selection_signals"]["risk_flags"])

        compare = build_product_compare_view(view, include_history_points=True)
        self.assertEqual(compare["product_count"], 2)
        self.assertIn("bounded_history_points", compare["rows"][0])
        self.assertGreaterEqual(len(compare["risk_summary"]["by_code"]), 1)

    def test_workflow_resolver_derives_inputs_from_resources_and_artifacts(self) -> None:
        graph = build_selection_graph(command="finder.query", selection={"category": "172282"}, body={"asins": ["B000000001", "B000000002"]})
        cached = {
            "ok": True,
            "command": "products.compare",
            "data": {
                "research_graph": graph,
                "products": [{"asin": "B000000001"}, {"asin": "B000000002"}],
                "rows": [{"asin": "B000000001"}, {"asin": "B000000002"}],
            },
        }
        cache = {"compare:key": cached}

        params, resolution = resolve_workflow_arguments(
            "keepa.products_compare",
            {"resource_uri": "keepa://research/b64:" + text_to_resource_token("compare:key")},
            session_cache=cache,
        )
        self.assertEqual(params["asin"], ["B000000001", "B000000002"])
        self.assertEqual(resolution["graph_count"], 1)

        graph_params, graph_resolution = resolve_workflow_arguments(
            "keepa.research_graph_merge",
            {"resource_uri": "keepa://research/b64:" + text_to_resource_token("compare:key") + "/graph"},
            session_cache=cache,
        )
        self.assertIn("graph", graph_params)
        self.assertEqual(graph_resolution["resolved"][0]["graph_count"], 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.json"
            path.write_text(json.dumps(cached), encoding="utf-8")
            output_uri = path_to_resource_uri(path, kind="output")
            report_params, report_resolution = resolve_workflow_arguments(
                "keepa.reports_build",
                {
                    "workflow_inputs": {"graph_inputs": {"value": output_uri}},
                    "workflow_context": {
                        "steps": {
                            "inline": {"payload": {"data": {"products": [{"asin": "B000000003"}]}}},
                            "artifact": {"artifact": {"data": {"output": {"path": str(path)}}}},
                        },
                        "outputs": [{"graph": graph}],
                    },
                },
                session_cache=cache,
            )
            self.assertEqual(Path(report_params["input"]).resolve(), path.resolve())
            self.assertGreaterEqual(report_resolution["payload_count"], 2)

        missing, missing_resolution = resolve_workflow_arguments("keepa.tracking_get", {}, session_cache={})
        self.assertNotIn("asin", missing)
        self.assertEqual(missing_resolution["missing_inputs"][0]["field"], "asin")

    def test_mcp_resources_cover_templates_errors_and_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs/schema").mkdir(parents=True)
            (root / "evidence/tasks").mkdir(parents=True)
            (root / "tests/fixtures").mkdir(parents=True)
            (root / ".zread/wiki/versions/v1").mkdir(parents=True)
            (root / ".zread/wiki/current").write_text("versions/v1", encoding="utf-8")
            (root / ".zread/wiki/versions/v1/wiki.json").write_text(
                json.dumps({"id": "v1", "language": "zh", "pages": [{"slug": "overview", "file": "overview.md", "title": "Overview"}]}),
                encoding="utf-8",
            )
            (root / ".zread/wiki/versions/v1/overview.md").write_text("# products.agent-view\n", encoding="utf-8")
            (root / "docs/schema/products.agent-view.schema.json").write_text("{}", encoding="utf-8")
            (root / "docs/schema/workflow-runtime-contract.schema.json").write_text("{}", encoding="utf-8")
            (root / "docs/schema/risk-taxonomy.schema.json").write_text("{}", encoding="utf-8")
            (root / "evidence/manifest.csv").write_text("logical_path,kind\n", encoding="utf-8")
            (root / "tests/fixtures/unit.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

            self.assertEqual(read_mcp_resource("keepa://schema/products.agent-view.schema.json", root=root)["mimeType"], "application/json")
            self.assertEqual(read_mcp_resource("keepa://fixtures/unit.json", root=root)["mimeType"], "application/json")
            self.assertEqual(json.loads(read_mcp_resource("keepa://evidence/recent", root=root)["text"])["items"], [])
            self.assertIn("products.agent-view", read_mcp_resource("keepa://zread/wiki/page/overview", root=root)["text"])

            with self.assertRaises(ValueError) as ctx:
                read_mcp_resource("keepa://schema/missing", root=root)
            self.assertIn("unknown schema", str(ctx.exception))
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://fixtures/../bad.json", root=root)
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://cache-key/products.get/not-json")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://workflow/bad/policy")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://toolsets/")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://tools/missing")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://prompts/")
            with self.assertRaises(ValueError):
                read_mcp_resource("keepa://asin//fixture", root=root)

        cache_key = "compare:key"
        session_cache = {
            cache_key: {
                "ok": True,
                "command": "products.compare",
                "data": {
                    "rows": [
                        {
                            "identity": {"asin": "B000000001"},
                            "pricing": {"current": {"new": {"amount": 12.99}}},
                            "risk_taxonomy": {"codes": ["data_missing"]},
                            "research_graph": build_category_graph(category_id="172282", name="Kitchen"),
                        }
                    ],
                    "raw": {"output": {"path": "raw.json"}},
                },
            }
        }
        cached = json.loads(read_mcp_resource("keepa://research/b64:" + text_to_resource_token(cache_key), session_cache=session_cache)["text"])
        missing = json.loads(read_mcp_resource("keepa://research/missing", session_cache=session_cache)["text"])
        self.assertTrue(cached["found"])
        self.assertEqual(cached["command"], "products.compare")
        self.assertEqual(cached["research_graph_count"], 0)
        self.assertEqual(missing["available_cache_keys"], [cache_key])

    def test_research_graph_workflow_and_high_value_edge_cases(self) -> None:
        category = build_category_graph(category_id="172282", name="Kitchen", parent="1", children=["2", "3"])
        candidates = build_category_candidates_graph([{"category_id": "172282", "name": "Kitchen", "parent": "1"}, {"name": "skip"}], term="home")
        sellers = build_topsellers_graph(sellers=[{"sellerId": "SELLER1", "sellerName": "A", "categoryId": "172282"}, {"sellerName": "skip"}])
        duplicate_a = build_selection_graph(command="finder.query", selection={"category": "172282"}, body={"products": [{"asin": "B000000001"}]})
        duplicate_b = build_selection_graph(command="finder.query", selection={"categories": ["172282"]}, body={"deals": [{"asin": "B000000001"}]})
        merged = merge_research_graphs([category, candidates, sellers, duplicate_a, duplicate_b], root="merged", prefer_source=0)

        self.assertGreaterEqual(category["edge_count"], 3)
        self.assertGreaterEqual(candidates["entity_counts"]["category"], 2)
        self.assertGreaterEqual(sellers["entity_counts"]["seller"], 1)
        self.assertGreaterEqual(merged["diagnostics"]["duplicate_node_count"], 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selection_file = root / "selection.json"
            selection_file.write_text(json.dumps({"category": 172282}), encoding="utf-8")
            self.assertEqual(load_selection('{"category": 172282}')["category"], 172282)
            self.assertEqual(load_selection(selection_file=selection_file)["category"], 172282)
            for bad in ("[]", "{"):
                with self.subTest(selection=bad):
                    with self.assertRaises(ValueError):
                        load_selection(bad)
            with self.assertRaises(ValueError):
                load_selection(selection_file=root / "missing.json")

            output = write_body_output({"body": {"bestSellersList": {"asinList": ["B000000001", "B000000002"]}}}, root / "body.json")
            self.assertEqual(output["result_count"], 2)
            payload = {"ok": True, "data": {"body": {"sellers": {"SELLER1": {}}}}}
            self.assertEqual(attach_output_if_requested(payload, root / "attached.json")["data"]["output"]["result_count"], 1)

            template_out = root / "template.json"
            self.assertTrue(show_template("finder-basic", out=str(template_out))["output"]["path"])
            with self.assertRaises(ValueError):
                show_template("missing")

    def test_reports_history_context_and_cache_fallbacks(self) -> None:
        rows_payload = {"rows": [{"asin": "B000000001", "estimated_tokens": 1}, {"asin": "B000000002"}]}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "rows.json"
            input_path.write_text(json.dumps(rows_payload), encoding="utf-8")
            figure = root / "figure.svg"
            figure.write_text("<svg></svg>", encoding="utf-8")

            csv_report = build_report(input_path=str(input_path), output_format="csv", out=None, title="CSV")
            json_report = build_report(input_path=str(input_path), output_format="json", out=str(root / "report.json"), title="JSON", figure=str(figure))
            markdown = build_report(input_path=str(input_path), output_format="markdown", out=None, title="MD", embed_figures=False)
            self.assertIn("asin", csv_report["content"])
            self.assertEqual(json_report["figures"]["mode"], "provided")
            self.assertNotIn("## Figures", markdown["content"])
            with self.assertRaises(ValueError):
                build_report(input_path=str(input_path), output_format="xml", out=None, title="bad")
            with self.assertRaises(ValueError):
                build_report(input_path=str(input_path), output_format="json", out=None, title="bad", figure=str(root / "missing.svg"))

            provenance_path = root / "provenance.json"
            provenance_path.write_text(json.dumps({"data": {"provenance": {"endpoint": "local://x", "source": "fixture", "cache_hit": True}}}), encoding="utf-8")
            self.assertEqual(explain_cache(input_path=str(provenance_path), command="products.get", endpoint=None)["source"], "fixture")

            product = json.loads(Path("tests/fixtures/product_history_B001GZ6QEC.json").read_text(encoding="utf-8"))["products"][0]
            history_rows = extract_history_rows(product, normalize_series_names("amazon,sales_rank"))
            self.assertIn("amazon", normalize_series_names(["amazon,sales_rank", "new"]))
            with self.assertRaises(ValueError):
                normalize_series_names("unsupported")
            self.assertEqual(write_history_export(history_rows, root / "history.csv", "csv")["format"], "csv")
            self.assertIn("content", build_history_export_data(asin="B001", domain="US", rows=history_rows, output_format="jsonl"))
            self.assertIn("rows", build_history_export_data(asin="B001", domain="US", rows=history_rows, output_format="json"))
            with self.assertRaises(ValueError):
                write_history_export(history_rows, root / "history.txt", "txt")
            with self.assertRaises(ValueError):
                build_history_export_data(asin="B001", domain="US", rows=history_rows, output_format="bad")

        target = resolve_research_target({"query": "category 172282 and seller A2L77EE7U53NWQ", "hint_type": "seller"}, repo_root=Path("."))
        self.assertEqual(target["primary"]["type"], "seller")
        self.assertTrue(query_research_context({"target": target["primary"], "question": "schema risk workflow tool prompt evidence"}, repo_root=Path("."))["resources"])

        with self.assertRaises(ValueError) as ctx:
            build_workflow_plan(name="category-research", term=None, asin=None, domain="US", goal="research", hydrate_top=1)
        self.assertIn("requires --term", str(ctx.exception))
        with self.assertRaises(ValueError):
            build_workflow_plan(name="unknown", term=None, asin=None, domain="US", goal="research", hydrate_top=1)


if __name__ == "__main__":
    unittest.main()
