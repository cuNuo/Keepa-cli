"""
keepa_cli/workflows.py
文件说明：提供 v1.0/v1.5 的离线优先本地工作流。
主要职责：生成本地浏览快照、批处理计划、报告、模板、缓存解释和成本审计。
依赖边界：不访问真实 Keepa API；调用方负责 envelope 与命令行解析。
"""

from __future__ import annotations

import csv
import html
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from keepa_cli.agent_contract import build_action, build_evidence_index
from keepa_cli.agent.resources import path_to_resource_uri
from keepa_cli.agent.tools import is_tool_active_for_profile, profile_allowed_tools, profile_names
from keepa_cli.cache import SQLiteResponseCache, build_cache_provenance, default_cache_path, explain_response_cache_key
from keepa_cli.figures import build_research_figures
from keepa_cli.research_graph import extract_research_graphs, graph_summary
from keepa_cli.token_budget import estimate_request_budget


TEMPLATES: dict[str, dict[str, Any]] = {
    "finder-basic": {
        "kind": "finder.selection",
        "description": "Basic Product Finder selection scaffold.",
        "selection": {"page": 0, "perPage": 50, "sort": [["current_SALES", "asc"]]},
        "commands": [
            "kc --json finder query --selection-file finder-basic.json --domain US --dry-run",
        ],
    },
    "deals-basic": {
        "kind": "deals.selection",
        "description": "Basic deals selection scaffold.",
        "selection": {"page": 0, "perPage": 50, "domainId": 1},
        "commands": [
            "kc --json deals query --selection-file deals-basic.json --domain US --dry-run",
        ],
    },
    "tracking-add": {
        "kind": "tracking.batch",
        "description": "Tracking payload scaffold; live add requires --yes.",
        "tracking": [{"asin": "B09YNQCQKR", "domain": 1, "desiredPrices": [[1, 1999]]}],
        "commands": [
            "kc --json tracking add --tracking-file tracking-add.json --dry-run",
        ],
    },
    "batch-report": {
        "kind": "batch.report",
        "description": "Batch ASIN inspection followed by markdown report.",
        "commands": [
            "kc --json batch asins asins.txt --domain US --dry-run --out batch.json",
            "kc --json reports build --input batch.json --format markdown --out report.md",
        ],
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_asins(path: str | Path) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        asin = line.split(",", 1)[0].strip().upper()
        if asin and asin not in seen:
            seen.add(asin)
            result.append(asin)
    return result


def write_json(path: str | Path, data: Any) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(output), "bytes_written": output.stat().st_size}


def write_text(path: str | Path, content: str) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return {"path": str(output), "bytes_written": output.stat().st_size}


def _product_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    body = data.get("body") if isinstance(data, Mapping) else payload.get("body")
    if isinstance(body, Mapping) and isinstance(body.get("products"), list):
        rows: list[dict[str, Any]] = []
        for product in body["products"]:
            if isinstance(product, Mapping):
                rows.append(
                    {
                        "asin": str(product.get("asin", "")),
                        "title": str(product.get("title", "")),
                        "brand": str(product.get("brand", "")),
                        "categoryTree": product.get("categoryTree", []),
                    }
                )
        return rows
    graphs = extract_research_graphs(payload)
    graph_rows: list[dict[str, Any]] = []
    for graph in graphs:
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        for node in nodes:
            if not isinstance(node, Mapping) or node.get("type") != "product":
                continue
            attributes = node.get("attributes") if isinstance(node.get("attributes"), Mapping) else {}
            graph_rows.append(
                {
                    "asin": str(attributes.get("asin") or str(node.get("id") or "").removeprefix("product:")),
                    "title": str(node.get("label") or ""),
                    "brand": str(attributes.get("brand") or ""),
                    "categoryTree": [],
                    "source": "research_graph",
                }
            )
    if graph_rows:
        return graph_rows
    return []


def build_browse_snapshot(*, input_path: str | None, out_dir: str, title: str) -> dict[str, Any]:
    payload = load_json_file(input_path) if input_path else {}
    rows = _product_rows(payload)
    generated_at = utc_now_iso()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "index.html"
    data_path = out / "data.json"
    graphs = extract_research_graphs(payload)
    graph_summary_data = graph_summary(graphs[0]) if graphs else {}
    write_json(data_path, {"generated_at": generated_at, "source": input_path, "rows": rows, "research_graph": graph_summary_data})

    max_bar = max((len(row.get("title", "")) for row in rows), default=1)
    cards = []
    bars = []
    for index, row in enumerate(rows, start=1):
        asin = html.escape(row.get("asin", ""))
        item_title = html.escape(row.get("title", "") or "(untitled)")
        brand = html.escape(row.get("brand", "") or "unknown brand")
        width = max(8, int((len(row.get("title", "")) / max_bar) * 100))
        cards.append(
            f'<article class="item"><strong>{asin}</strong><span>{brand}</span><p>{item_title}</p></article>'
        )
        bars.append(
            f'<div class="bar"><span>{index}</span><i style="width:{width}%"></i><em>{asin}</em></div>'
        )
    if not cards:
        cards.append('<article class="item empty"><strong>No product rows</strong><p>Provide a fixture or report JSON.</p></article>')

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; color: #17202a; background: #f6f7f9; }}
    header {{ padding: 28px 32px 18px; background: #ffffff; border-bottom: 1px solid #d8dde6; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; font-weight: 720; }}
    main {{ display: grid; grid-template-columns: minmax(240px, 360px) 1fr; gap: 24px; padding: 24px 32px; }}
    .panel {{ background: #fff; border: 1px solid #d8dde6; border-radius: 8px; padding: 18px; }}
    .metric {{ display: flex; justify-content: space-between; margin: 10px 0; }}
    .item {{ border-top: 1px solid #e5e8ee; padding: 14px 0; }}
    .item:first-child {{ border-top: 0; }}
    .item span {{ display: block; color: #687386; font-size: 13px; margin-top: 2px; }}
    .item p {{ margin: 8px 0 0; line-height: 1.45; }}
    .bar {{ display: grid; grid-template-columns: 28px 1fr 110px; align-items: center; gap: 10px; margin: 12px 0; }}
    .bar i {{ display: block; height: 10px; background: #2f6fed; border-radius: 6px; }}
    .bar em {{ font-style: normal; color: #536173; font-size: 12px; }}
    @media (max-width: 760px) {{ main {{ grid-template-columns: 1fr; padding: 18px; }} header {{ padding: 22px 18px 14px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <div>Generated {generated_at} from {html.escape(str(input_path or "empty input"))}</div>
  </header>
  <main>
    <section class="panel">
      <div class="metric"><span>Products</span><strong>{len(rows)}</strong></div>
      <div class="metric"><span>Graph nodes</span><strong>{html.escape(str(graph_summary_data.get("node_count", 0)))}</strong></div>
      <div class="metric"><span>Graph edges</span><strong>{html.escape(str(graph_summary_data.get("edge_count", 0)))}</strong></div>
      <div class="metric"><span>Data file</span><strong>data.json</strong></div>
      {''.join(bars)}
    </section>
    <section class="panel">{''.join(cards)}</section>
  </main>
</body>
</html>
"""
    write_text(index_path, document)
    return {
        "out_dir": str(out),
        "index": str(index_path),
        "data": str(data_path),
        "row_count": len(rows),
        "research_graph": graph_summary_data,
        "provenance": build_cache_provenance(
            endpoint="local://browse.snapshot",
            params={"input": input_path or "", "out_dir": out_dir, "title": title},
            source="local",
            out=str(index_path),
        ),
    }


def build_batch_asins(*, asin_file: str, domain: str, dry_run: bool, fixture: str | None, out: str | None) -> dict[str, Any]:
    asins = read_asins(asin_file)
    tasks = []
    for asin in asins:
        budget = estimate_request_budget("products.get", {"asin": [asin]}).to_dict()
        tasks.append(
            {
                "command": "products.get",
                "params": {"asin": [asin], "domain": domain, "fixture": fixture, "dry_run": dry_run},
                "estimated_tokens": budget["estimated_tokens"],
                "worst_case_tokens": budget["worst_case_tokens"],
            }
        )
    total = sum(int(item["estimated_tokens"]) for item in tasks)
    data: dict[str, Any] = {
        "asin_file": asin_file,
        "domain": domain,
        "dry_run": dry_run,
        "task_count": len(tasks),
        "estimated_tokens": total,
        "tasks": tasks,
        "provenance": build_cache_provenance(
            endpoint="local://batch.asins",
            params={"asin_file": asin_file, "domain": domain, "dry_run": dry_run, "fixture": fixture or ""},
            source="local",
        ),
    }
    if out:
        data["output"] = write_json(out, data)
    return data


def list_templates() -> dict[str, Any]:
    return {
        "templates": [
            {"name": name, "kind": item["kind"], "description": item["description"]}
            for name, item in sorted(TEMPLATES.items())
        ]
    }


def show_template(name: str, out: str | None = None) -> dict[str, Any]:
    if name not in TEMPLATES:
        supported = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"unknown template: {name}; supported: {supported}")
    template = {"name": name, **TEMPLATES[name]}
    if out:
        template["output"] = write_json(out, template)
    return template


def _mcp_tool_name(tool: str) -> str:
    business_aliases = {
        "business.find-fast-movers": "keepa.find_fast_movers",
        "business.inventory-audit": "keepa.inventory_audit",
        "business.market-opportunity": "keepa.market_opportunity",
    }
    if tool in business_aliases:
        return business_aliases[tool]
    return "keepa." + tool.replace(".", "_").replace("-", "_")


def _step_profile(tool: str, *, requires_confirmation: bool) -> str:
    if tool in {"categories.search", "categories.products", "categories.finder-selection", "finder.query", "deals.query", "bestsellers.get", "topsellers.list"}:
        return "dry_run_default"
    if tool in {"products.get", "products.compare", "sellers.get"}:
        return "live_read_allowed"
    if tool in {"reports.build", "browse.snapshot", "research_graph.merge", "research_brief.export"}:
        return "offline_fixture_only"
    if tool in {"tracking.list", "tracking.list-names", "tracking.get", "tracking.notifications"}:
        return "tracking_readonly"
    if requires_confirmation:
        return "live_read_allowed"
    return "offline_fixture_only"


def _execution_mode(*, estimated_tokens: int, requires_confirmation: bool, fixture_replay: str | None) -> str:
    if estimated_tokens == 0:
        return "local_only"
    if fixture_replay:
        return "fixture_replay_preferred"
    if requires_confirmation:
        return "confirmation_required"
    return "live_read_or_fixture"


def _step_io_metadata(step_id: str) -> dict[str, Any]:
    metadata: dict[str, dict[str, Any]] = {
        "search-categories": {
            "input_refs": ["workflow_inputs.term", "workflow_inputs.domain"],
            "artifact_refs": ["artifacts.category_candidates"],
        },
        "scaffold-finder": {
            "input_refs": ["artifacts.category_candidates.selected_category_id"],
            "artifact_refs": ["artifacts.finder_selection"],
        },
        "fetch-category-products": {
            "input_refs": ["artifacts.category_candidates.selected_category_id"],
            "artifact_refs": ["artifacts.category_products", "artifacts.category_products.cache_key"],
        },
        "compare-candidates": {
            "input_refs": ["artifacts.category_products.asins"],
            "artifact_refs": ["artifacts.product_comparison", "artifacts.product_comparison.cache_key"],
        },
        "get-product-summary": {
            "input_refs": ["workflow_inputs.asin", "workflow_inputs.domain", "workflow_inputs.goal"],
            "artifact_refs": ["artifacts.product_summary", "artifacts.product_summary.cache_key"],
        },
        "optional-offers": {
            "input_refs": ["artifacts.product_summary.data_quality", "workflow_inputs.asin"],
            "artifact_refs": ["artifacts.offer_detail", "artifacts.offer_detail.cache_key"],
        },
        "merge-research-graph": {
            "input_refs": ["workflow_inputs.graph_inputs", "resource_templates.research_cache", "resource_templates.graph_root"],
            "artifact_refs": ["artifacts.merged_graph", "artifacts.merged_graph.path"],
        },
        "build-graph-report": {
            "input_refs": ["artifacts.merged_graph.path"],
            "artifact_refs": ["artifacts.markdown_report"],
        },
        "export-agent-brief": {
            "input_refs": ["artifacts.merged_graph.path"],
            "artifact_refs": ["artifacts.agent_brief"],
        },
        "build-browse-snapshot": {
            "input_refs": ["artifacts.merged_graph.path"],
            "artifact_refs": ["artifacts.browse_snapshot"],
        },
        "list-tracking": {
            "input_refs": ["workflow_inputs.domain"],
            "artifact_refs": ["artifacts.tracking_list"],
        },
        "read-notifications": {
            "input_refs": ["artifacts.tracking_list"],
            "artifact_refs": ["artifacts.tracking_notifications"],
        },
        "get-tracking-detail": {
            "input_refs": ["workflow_inputs.asin", "artifacts.tracking_list"],
            "artifact_refs": ["artifacts.tracking_detail"],
        },
        "audit-tracking-cost": {
            "input_refs": ["workflow_inputs.asin", "workflow_inputs.domain"],
            "artifact_refs": ["artifacts.tracking_cost_estimate"],
        },
    }
    return metadata.get(step_id, {"input_refs": [], "artifact_refs": []})


def _plan_step(
    *,
    step_id: str,
    title: str,
    action: dict[str, Any],
    depends_on: list[str] | None = None,
    parallel_group: str | None = None,
    fixture_replay: str | None = None,
) -> dict[str, Any]:
    budget = estimate_request_budget(action["tool"], dict(action.get("params") or {})).to_dict()
    mcp_tool = _mcp_tool_name(action["tool"])
    step_profile = _step_profile(action["tool"], requires_confirmation=bool(action["requires_confirmation"]))
    execution: dict[str, Any] = {
        "mode": _execution_mode(
            estimated_tokens=int(action["estimated_tokens"]),
            requires_confirmation=bool(action["requires_confirmation"]),
            fixture_replay=fixture_replay,
        ),
        "safe_default": not bool(action["requires_confirmation"]),
        "cache_strategy": "reuse cache_key or from_cache before repeating the same step",
        "fixture_replay": fixture_replay,
    }
    if action["requires_confirmation"]:
        execution["confirmation_params"] = {"yes": True}
        execution["confirmation_reason"] = "requires explicit user approval before a live call"
    io_metadata = _step_io_metadata(step_id)
    return {
        "id": step_id,
        "title": title,
        "tool": action["tool"],
        "mcp_tool": mcp_tool,
        "params": action["params"],
        "cli": action["cli"],
        "command": action["command"],
        "reason": action["reason"],
        "depends_on": depends_on or [],
        "parallel_group": parallel_group,
        "estimated_tokens": action["estimated_tokens"],
        "worst_case_tokens": budget["worst_case_tokens"],
        "requires_confirmation": action["requires_confirmation"],
        "fixture_replay": fixture_replay,
        "input_refs": io_metadata["input_refs"],
        "artifact_refs": io_metadata["artifact_refs"],
        "mcp": {
            "tool": mcp_tool,
            "toolset": "research",
            "profile": step_profile,
            "active_in_profile": is_tool_active_for_profile(mcp_tool, step_profile),
            "call": {"name": mcp_tool, "arguments": {**dict(action["params"]), "profile": step_profile}},
        },
        "execution": execution,
    }


def _category_research_plan(*, term: str, domain: str, hydrate_top: int) -> list[dict[str, Any]]:
    return [
        _plan_step(
            step_id="search-categories",
            title="Find candidate categories",
            action=build_action(
                tool="categories.search",
                params={"term": term, "domain": domain},
                cli=f"categories search {json.dumps(term)} --domain {domain}",
                reason="discover candidate Keepa category ids for the search term",
            ),
            fixture_replay="category_search_home.json",
        ),
        _plan_step(
            step_id="scaffold-finder",
            title="Generate local Finder scaffold",
            action=build_action(
                tool="categories.finder-selection",
                params={"category": "<CATEGORY_ID>", "domain": domain, "out": "finder-category-<CATEGORY_ID>.json"},
                cli=f"categories finder-selection <CATEGORY_ID> --domain {domain} --out finder-category-<CATEGORY_ID>.json",
                reason="create a local Product Finder selection scaffold from the chosen category",
            ),
            depends_on=["search-categories"],
            parallel_group="category-followups",
        ),
        _plan_step(
            step_id="fetch-category-products",
            title="Fetch category ASIN candidates",
            action=build_action(
                tool="categories.products",
                params={"category": "<CATEGORY_ID>", "domain": domain, "limit": 25, "hydrate_top": hydrate_top},
                cli=f"categories products <CATEGORY_ID> --domain {domain} --limit 25"
                + (f" --hydrate-top {hydrate_top}" if hydrate_top else ""),
                reason="fetch Best Sellers ASIN candidates for the chosen category",
            ),
            depends_on=["search-categories"],
            parallel_group="category-followups",
            fixture_replay="bestsellers_home.json",
        ),
        _plan_step(
            step_id="compare-candidates",
            title="Compare candidate products",
            action=build_action(
                tool="products.compare",
                params={"asin": ["<ASIN_1>", "<ASIN_2>"], "domain": domain, "full": True, "view": "deal"},
                cli=f"products compare <ASIN_1> <ASIN_2> --domain {domain} --full --view deal",
                reason="compare top candidates using deal-oriented Agent fields",
            ),
            depends_on=["fetch-category-products"],
            fixture_replay="product_agent_view_B0TEST.json",
        ),
    ]


def _product_research_plan(*, asin: str, domain: str, goal: str) -> list[dict[str, Any]]:
    view = "deal" if goal == "deal" else "research"
    return [
        _plan_step(
            step_id="get-product-summary",
            title="Fetch Agent product view",
            action=build_action(
                tool="products.get",
                params={"asin": asin, "domain": domain, "full": True, "agent_view": True, "view": view},
                cli=f"products get {asin} --domain {domain} --full --agent-view --view {view}",
                reason="fetch the core Agent product view for the requested goal",
            ),
            fixture_replay="product_agent_view_B0TEST.json",
        ),
        _plan_step(
            step_id="optional-offers",
            title="Optionally fetch offer detail",
            action=build_action(
                tool="products.get",
                params={"asin": asin, "domain": domain, "full": True, "offers": "20", "agent_view": True, "view": "deal"},
                cli=f"products get {asin} --domain {domain} --full --offers 20 --agent-view --view deal",
                reason="only run if data_quality shows offers.offers missing and seller-level competition matters",
                estimated_tokens=13,
            ),
            depends_on=["get-product-summary"],
        ),
    ]


def _report_research_plan(*, domain: str, goal: str) -> list[dict[str, Any]]:
    graph_path = "<MERGED_GRAPH_JSON>"
    report_path = "<REPORT_MARKDOWN>"
    browse_dir = "<BROWSE_DIR>"
    return [
        _plan_step(
            step_id="merge-research-graph",
            title="Merge research graph inputs",
            action=build_action(
                tool="research_graph.merge",
                params={"input": ["<CATEGORY_JSON>", "<COMPARE_JSON>", "<SELLER_JSON>"], "root": f"{goal}-research", "out": graph_path},
                cli=f"research-graph merge <CATEGORY_JSON> <COMPARE_JSON> <SELLER_JSON> --root {goal}-research --out {graph_path}",
                reason="combine category, product, deal, and seller evidence into one auditable entity graph",
                estimated_tokens=0,
            ),
        ),
        _plan_step(
            step_id="build-graph-report",
            title="Build graph-backed report",
            action=build_action(
                tool="reports.build",
                params={"input": graph_path, "format": "markdown", "out": report_path, "title": f"Keepa {goal.title()} Research"},
                cli=f"reports build --input {graph_path} --format markdown --out {report_path} --title \"Keepa {goal.title()} Research\"",
                reason="turn the merged graph into a human-readable report with entity and relationship sections",
                estimated_tokens=0,
            ),
            depends_on=["merge-research-graph"],
        ),
        _plan_step(
            step_id="export-agent-brief",
            title="Export Agent research brief",
            action=build_action(
                tool="research_brief.export",
                params={"input": [graph_path], "title": f"Keepa {goal.title()} Research Brief"},
                cli=f"research-brief export --input {graph_path} --title \"Keepa {goal.title()} Research Brief\"",
                reason="produce a compact machine-readable handoff from the same evidence graph",
                estimated_tokens=0,
            ),
            depends_on=["merge-research-graph"],
            parallel_group="report-outputs",
        ),
        _plan_step(
            step_id="build-browse-snapshot",
            title="Build local browse snapshot",
            action=build_action(
                tool="browse.snapshot",
                params={"input": graph_path, "out_dir": browse_dir, "title": f"Keepa {goal.title()} Browse"},
                cli=f"browse snapshot --input {graph_path} --out-dir {browse_dir} --title \"Keepa {goal.title()} Browse\"",
                reason="create a local static HTML view for manual inspection of the research evidence",
                estimated_tokens=0,
            ),
            depends_on=["merge-research-graph"],
            parallel_group="report-outputs",
        ),
    ]


def _tracking_audit_plan(*, asin: str | None, domain: str) -> list[dict[str, Any]]:
    target_asin = asin or "<ASIN>"
    return [
        _plan_step(
            step_id="list-tracking",
            title="List tracked ASINs",
            action=build_action(
                tool="tracking.list",
                params={"domain": domain, "asins_only": True, "dry_run": True},
                cli=f"tracking list --domain {domain} --asins-only --dry-run",
                reason="read the current tracking list shape without exposing tracking write tools",
            ),
            fixture_replay="tracking_list.json",
        ),
        _plan_step(
            step_id="read-notifications",
            title="Read tracking notifications",
            action=build_action(
                tool="tracking.notifications",
                params={"domain": domain, "dry_run": True},
                cli=f"tracking notifications --domain {domain} --dry-run",
                reason="inspect notification payload shape before deciding whether alert data is useful",
            ),
            depends_on=["list-tracking"],
            parallel_group="tracking-readonly",
        ),
        _plan_step(
            step_id="get-tracking-detail",
            title="Read one tracking detail",
            action=build_action(
                tool="tracking.get",
                params={"asin": target_asin, "domain": domain, "dry_run": True},
                cli=f"tracking get {target_asin} --domain {domain} --dry-run",
                reason="inspect read-only tracking detail for a selected ASIN from the tracking list",
            ),
            depends_on=["list-tracking"],
            parallel_group="tracking-readonly",
        ),
        _plan_step(
            step_id="audit-tracking-cost",
            title="Estimate tracking read cost",
            action=build_action(
                tool="audit.cost",
                params={"target_command": "tracking.get", "params": {"asin": target_asin, "domain": domain}},
                cli=f"audit cost tracking.get --param asin={target_asin} --param domain={domain}",
                reason="record expected token budget for the read-only tracking detail step",
                estimated_tokens=0,
            ),
            depends_on=["list-tracking"],
            parallel_group="tracking-readonly",
        ),
    ]


def _business_alias_plan(*, name: str, domain: str) -> list[dict[str, Any]]:
    command_by_name = {
        "velocity-research": "business.find-fast-movers",
        "inventory-audit": "business.inventory-audit",
        "market-opportunity": "business.market-opportunity",
    }
    cli_by_name = {
        "velocity-research": "business find-fast-movers --input <PRODUCTS_JSON>",
        "inventory-audit": "business inventory-audit --input <PRODUCTS_JSON>",
        "market-opportunity": "business market-opportunity --input <PRODUCTS_JSON>",
    }
    reason_by_name = {
        "velocity-research": "turn existing product evidence into monthlySold and velocity metrics with formula confidence",
        "inventory-audit": "turn existing product evidence into stockout, seller count, and replenishment risk signals",
        "market-opportunity": "combine velocity, competition, inventory, and cashflow proxy into a conclusion-first shortlist",
    }
    command = command_by_name[name]
    return [
        _plan_step(
            step_id=name,
            title=name.replace("-", " ").title(),
            action=build_action(
                tool=command,
                params={"input": "<PRODUCTS_JSON>", "domain": domain},
                cli=cli_by_name[name],
                reason=reason_by_name[name],
                estimated_tokens=0,
                requires_confirmation=False,
            ),
            fixture_replay="product_agent_view_B0TEST.json",
        ),
    ]


def _workflow_resource_templates(name: str) -> list[dict[str, str]]:
    templates = [
        {
            "name": "workflow_policy",
            "uri_template": "keepa://workflow/{encoded_params}/policy",
            "use": "reload compact execution policy for the same workflow params",
        },
        {
            "name": "fixture",
            "uri_template": "keepa://fixtures/{name}",
            "use": "load offline replay fixture referenced by a step",
        },
    ]
    if name in {"category-research", "product-research", "report-research", "velocity-research", "inventory-audit", "market-opportunity"}:
        templates.extend(
            [
                {
                    "name": "research_cache",
                    "uri_template": "keepa://research/{cache_key}",
                    "use": "audit a same-session cached research result before repeating a call",
                },
                {
                    "name": "research_graph",
                    "uri_template": "keepa://research/{cache_key}/graph",
                    "use": "load only the cached research graph chunk for graph merge inputs",
                },
                {
                    "name": "research_brief",
                    "uri_template": "keepa://research/{cache_key}/brief",
                    "use": "load a compact handoff generated from a cached research payload",
                },
                {
                    "name": "graph_root",
                    "uri_template": "keepa://graphs/{root}",
                    "use": "audit a merged research graph and its sources by logical root",
                },
            ]
        )
    if name == "report-research":
        templates.append(
            {
                "name": "output",
                "uri_template": "keepa://output/{encoded_path}",
                "use": "read generated report, brief, or browse output by encoded local path",
            }
        )
    return templates


def _workflow_inputs(*, name: str, term: str | None, asin: str | None, domain: str, goal: str, hydrate_top: int) -> dict[str, Any]:
    common = {
        "domain": {"required": True, "value": domain, "source": "params.domain", "description": "Keepa domain code, id, or host suffix."},
        "goal": {"required": False, "value": goal, "source": "params.goal", "description": "Agent research goal used to pick views and labels."},
    }
    if name == "category-research":
        common.update(
            {
                "term": {"required": True, "value": term or "", "source": "params.term", "description": "Keyword used to discover candidate categories."},
                "hydrate_top": {
                    "required": False,
                    "value": hydrate_top,
                    "source": "params.hydrate_top",
                    "description": "Optional explicit hydration count for category products.",
                },
                "selected_category_id": {
                    "required": "after_step:search-categories",
                    "value": "<CATEGORY_ID>",
                    "source": "artifacts.category_candidates",
                    "description": "Chosen category id from category candidate output.",
                },
            }
        )
    elif name == "product-research":
        common["asin"] = {"required": True, "value": asin or "", "source": "params.asin", "description": "Primary ASIN to research."}
    elif name == "report-research":
        common["graph_inputs"] = {
            "required": True,
            "value": ["<CATEGORY_JSON>", "<COMPARE_JSON>", "<SELLER_JSON>"],
            "source": "paths or resource_templates.research_graph",
            "description": "Prior graph-bearing envelopes or graph resources to merge into one report graph.",
        }
    elif name == "tracking-audit":
        common["asin"] = {
            "required": False,
            "value": asin or "<ASIN>",
            "source": "params.asin or artifacts.tracking_list",
            "description": "Tracked ASIN to inspect; can be chosen after list-tracking.",
        }
    elif name in {"velocity-research", "inventory-audit", "market-opportunity"}:
        common["business_input"] = {
            "required": True,
            "value": "<PRODUCTS_JSON>",
            "source": "local file, resource_uri, artifact, or inline payload",
            "description": "Existing Keepa CLI JSON containing raw products, Agent view products, or compare rows.",
        }
    return common


def _workflow_artifacts(name: str) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    if name == "category-research":
        artifacts = {
            "category_candidates": {"kind": "category_candidates", "produced_by": "search-categories", "resource_templates": ["keepa://fixtures/{name}"]},
            "finder_selection": {"kind": "finder_selection", "produced_by": "scaffold-finder", "path": "finder-category-<CATEGORY_ID>.json"},
            "category_products": {"kind": "asin_candidates", "produced_by": "fetch-category-products", "resource_templates": ["keepa://research/{cache_key}"]},
            "product_comparison": {"kind": "product_compare", "produced_by": "compare-candidates", "resource_templates": ["keepa://research/{cache_key}"]},
        }
    elif name == "product-research":
        artifacts = {
            "product_summary": {"kind": "product_agent_view", "produced_by": "get-product-summary", "resource_templates": ["keepa://research/{cache_key}"]},
            "offer_detail": {"kind": "product_offer_detail", "produced_by": "optional-offers", "resource_templates": ["keepa://research/{cache_key}"]},
        }
    elif name == "report-research":
        artifacts = {
            "merged_graph": {
                "kind": "research_graph",
                "produced_by": "merge-research-graph",
                "path": "<MERGED_GRAPH_JSON>",
                "resource_templates": ["keepa://graphs/{root}", "keepa://research/{cache_key}/graph"],
            },
            "markdown_report": {"kind": "markdown_report", "produced_by": "build-graph-report", "path": "<REPORT_MARKDOWN>", "resource_templates": ["keepa://output/{encoded_path}"]},
            "agent_brief": {"kind": "agent_research_brief", "produced_by": "export-agent-brief", "resource_templates": ["keepa://output/{encoded_path}"]},
            "browse_snapshot": {"kind": "local_html_snapshot", "produced_by": "build-browse-snapshot", "path": "<BROWSE_DIR>", "resource_templates": ["keepa://output/{encoded_path}"]},
        }
    elif name == "tracking-audit":
        artifacts = {
            "tracking_list": {"kind": "tracking_list", "produced_by": "list-tracking", "resource_templates": ["keepa://fixtures/{name}"]},
            "tracking_notifications": {"kind": "tracking_notifications", "produced_by": "read-notifications"},
            "tracking_detail": {"kind": "tracking_detail", "produced_by": "get-tracking-detail"},
            "tracking_cost_estimate": {"kind": "budget_estimate", "produced_by": "audit-tracking-cost"},
        }
    elif name in {"velocity-research", "inventory-audit", "market-opportunity"}:
        artifacts = {
            "business_metrics": {
                "kind": "business_metrics",
                "produced_by": name,
                "resource_templates": ["keepa://research/{cache_key}", "keepa://output/{encoded_path}"],
            }
        }
    return artifacts


def _workflow_policy(name: str, steps: list[dict[str, Any]], totals: Mapping[str, Any]) -> dict[str, Any]:
    if name == "category-research":
        recommended_toolset = "research"
        recommended_profile = "dry_run_default"
    elif name == "report-research":
        recommended_toolset = "reports"
        recommended_profile = "offline_fixture_only"
    elif name == "tracking-audit":
        recommended_toolset = "tracking-readonly"
        recommended_profile = "tracking_readonly"
    elif name in {"velocity-research", "inventory-audit", "market-opportunity"}:
        recommended_toolset = "business"
        recommended_profile = "offline_fixture_only"
    else:
        recommended_toolset = "research"
        recommended_profile = "live_read_allowed"
    allowed = profile_allowed_tools(recommended_profile)
    workflow_tools = [str(step["mcp"]["tool"]) for step in steps]
    active_tools = [tool for tool in workflow_tools if allowed is None or tool in allowed]
    inactive_tools = []
    switch_points = [
        {
            "before_step": steps[0]["id"] if steps else None,
            "profile": recommended_profile,
            "reason": "start workflow execution with the smallest profile that covers the first safe steps",
        }
    ]
    for step in steps:
        mcp_tool = str(step["mcp"]["tool"])
        active_in_recommended = allowed is None or mcp_tool in allowed
        step["mcp"]["toolset"] = recommended_toolset
        step["mcp"]["recommended_profile"] = recommended_profile
        step["mcp"]["active_in_recommended_profile"] = active_in_recommended
        if not active_in_recommended:
            inactive_tools.append(
                {
                    "step_id": step["id"],
                    "tool": mcp_tool,
                    "profile": recommended_profile,
                    "recommended_profile": step["mcp"]["profile"],
                    "reason": f"profile {recommended_profile} does not allow {mcp_tool}; switch only when dependencies and budget are satisfied",
                }
            )
            switch_points.append(
                {
                    "before_step": step["id"],
                    "profile": step["mcp"]["profile"],
                    "reason": f"enable {mcp_tool} after dependencies are complete",
                }
            )
        if step["requires_confirmation"]:
            switch_points.append(
                {
                    "before_step": step["id"],
                    "profile": step["mcp"]["profile"],
                    "requires_confirmation": True,
                    "confirmation_params": {"yes": True},
                    "reason": "pause for user approval before adding confirmation params",
                }
            )

    return {
        "recommended_toolset": recommended_toolset,
        "planning_profile": "offline_fixture_only",
        "recommended_profile": recommended_profile,
        "available_profiles": profile_names(),
        "workflow_tools": workflow_tools,
        "allowed_tools": active_tools,
        "inactive_tools": inactive_tools,
        "profile_switch_points": switch_points,
        "confirmation_policy": {
            "requires_confirmation": bool(totals.get("requires_confirmation")),
            "step_ids": [str(step["id"]) for step in steps if step["requires_confirmation"]],
            "resume_param": "yes",
            "default": "do not execute live high-cost steps until the user confirms the exact step",
        },
        "budget_ledger_seed": {
            "session_estimated": 0,
            "planned_estimated": int(totals.get("estimated_tokens") or 0),
            "planned_worst_case": int(totals.get("worst_case_tokens") or 0),
            "blocked_actions": [
                {
                    "step_id": step["id"],
                    "tool": step["mcp"]["tool"],
                    "estimated_tokens": step["estimated_tokens"],
                    "worst_case_tokens": step["worst_case_tokens"],
                    "reason": "confirmation_required",
                }
                for step in steps
                if step["requires_confirmation"]
            ],
        },
        "tool_discovery": {
            "method": "tools/list",
            "params": {
                "toolset": recommended_toolset,
                "profile": recommended_profile,
                "allow_tools": workflow_tools,
            },
        },
        "cache_policy": {
            "reuse": "prefer from_cache with a prior cache_key before repeating a step",
            "audit_resource": "keepa://research/{cache_key}",
        },
        "resource_templates": _workflow_resource_templates(name),
    }


def build_workflow_plan(*, name: str, term: str | None, asin: str | None, domain: str, goal: str, hydrate_top: int) -> dict[str, Any]:
    if name == "category-research":
        if not term:
            raise ValueError("workflow plan category-research requires --term")
        steps = _category_research_plan(term=term, domain=domain, hydrate_top=hydrate_top)
    elif name == "product-research":
        if not asin:
            raise ValueError("workflow plan product-research requires --asin")
        steps = _product_research_plan(asin=asin, domain=domain, goal=goal)
    elif name == "report-research":
        steps = _report_research_plan(domain=domain, goal=goal)
    elif name == "tracking-audit":
        steps = _tracking_audit_plan(asin=asin, domain=domain)
    elif name in {"velocity-research", "inventory-audit", "market-opportunity"}:
        steps = _business_alias_plan(name=name, domain=domain)
    else:
        raise ValueError(
            "workflow plan supports category-research, product-research, report-research, tracking-audit, "
            "velocity-research, inventory-audit, and market-opportunity"
        )

    totals = {
        "estimated_tokens": sum(int(step["estimated_tokens"]) for step in steps),
        "worst_case_tokens": sum(int(step["worst_case_tokens"]) for step in steps),
        "requires_confirmation": any(bool(step["requires_confirmation"]) for step in steps),
    }
    workflow_policy = _workflow_policy(name, steps, totals)
    workflow_inputs = _workflow_inputs(name=name, term=term, asin=asin, domain=domain, goal=goal, hydrate_top=hydrate_top)
    artifacts = _workflow_artifacts(name)
    return {
        "view": "workflow_plan",
        "name": name,
        "domain": domain,
        "goal": goal,
        "workflow_inputs": workflow_inputs,
        "artifacts": artifacts,
        "resource_templates": workflow_policy["resource_templates"],
        "steps": steps,
        "totals": totals,
        "parallel_groups": sorted({str(step["parallel_group"]) for step in steps if step.get("parallel_group")}),
        "workflow_policy": workflow_policy,
        "agent_brief": {
            "view": "workflow_plan",
            "one_line": f"{name} plan with {len(steps)} steps; estimated {totals['estimated_tokens']} tokens",
            "key_facts": {"name": name, "step_count": len(steps), "recommended_profile": workflow_policy["recommended_profile"], **totals},
            "read_order": ["agent_brief", "workflow_policy", "steps", "totals", "evidence_index"],
        },
        "data_quality": {
            "present": ["workflow_inputs", "artifacts", "resource_templates", "steps", "totals", "workflow_policy", "next_actions"],
            "missing": [],
            "confidence": "high",
            "notes": ["workflow plan is local-only and does not consume Keepa tokens"],
        },
        "selection_signals": {
            "step_count": len(steps),
            "parallel_group_count": len({step["parallel_group"] for step in steps if step.get("parallel_group")}),
            "confirmation_step_count": len(workflow_policy["confirmation_policy"]["step_ids"]),
            "inactive_tool_count": len(workflow_policy["inactive_tools"]),
            "artifact_count": len(artifacts),
            "resource_template_count": len(workflow_policy["resource_templates"]),
        },
        "next_actions": [
            build_action(
                tool=step["tool"],
                params=step["params"],
                cli=step["cli"],
                reason=f"execute workflow step {step['id']}: {step['reason']}",
                estimated_tokens=step["estimated_tokens"],
                requires_confirmation=step["requires_confirmation"],
            )
            for step in steps
            if not step["depends_on"]
        ],
        "evidence_index": build_evidence_index(
            {
                "steps": ("steps", "summary", "Ordered execution graph with dependencies and budgets."),
                "workflow_inputs": ("workflow_inputs", "summary", "Explicit input contract and late-bound values for workflow execution."),
                "artifacts": ("artifacts", "summary", "Named intermediate and final artifacts produced by the workflow."),
                "resource_templates": ("resource_templates", "summary", "MCP resource templates that can satisfy inputs or reload outputs."),
                "totals": ("totals", "summary", "Total estimated and worst-case token budget."),
                "workflow_policy": ("workflow_policy", "summary", "MCP profile, toolset, confirmation, cache, and budget policy for the plan."),
                "next_actions": ("next_actions", "summary", "Root actions safe for an Agent to start from."),
                "fixture_replay": ("steps[].fixture_replay", "audit", "Suggested fixture names for offline replay."),
            }
        ),
        "provenance": build_cache_provenance(
            endpoint="local://workflow.plan",
            params={"name": name, "term": term or "", "asin": asin or "", "domain": domain, "goal": goal, "hydrate_top": hydrate_top},
            source="local",
        ),
    }


def _report_rows_from_input(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping) and isinstance(payload.get("tasks"), list):
        return [dict(item) for item in payload["tasks"] if isinstance(item, Mapping)]
    if isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
        return [dict(item) for item in payload["rows"] if isinstance(item, Mapping)]
    return _product_rows(payload if isinstance(payload, Mapping) else {})


def _report_markdown(title: str, rows: list[dict[str, Any]], source: str, graph_report: Mapping[str, Any] | None = None) -> str:
    diagnostics = graph_report.get("diagnostics") if isinstance(graph_report, Mapping) and isinstance(graph_report.get("diagnostics"), Mapping) else {}
    graph_summary = graph_report.get("summary") if isinstance(graph_report, Mapping) and isinstance(graph_report.get("summary"), Mapping) else {}
    risk_notes = []
    if diagnostics:
        risk_notes.append(f"{diagnostics.get('conflict_count', 0)} graph conflicts")
        risk_notes.append(f"{diagnostics.get('orphan_node_count', 0)} orphan nodes")
    if not rows and graph_report is None:
        risk_notes.append("no report rows or graph evidence")
    lines = [
        f"# {title}",
        "",
        "## Brief",
        "",
        f"- Decision: {'review graph-backed evidence before acting' if graph_report is not None else 'review generated rows before acting'}",
        f"- Risk: {', '.join(risk_notes) if risk_notes else 'no report-level blocker detected'}",
        f"- Next action: read the evidence table, then inspect graph/entity sections only where the brief flags risk.",
        f"- Graph root: `{graph_summary.get('root', '')}`" if graph_summary else "- Graph root: not available",
        "",
        "## Evidence Table",
        "",
        f"- Generated: {utc_now_iso()}",
        f"- Source: `{source}`",
        f"- Rows: {len(rows)}",
        "",
        "| # | Command / ASIN | Estimate | Notes |",
        "|---:|---|---:|---|",
    ]
    for index, row in enumerate(rows, start=1):
        label = row.get("command") or row.get("asin") or row.get("title") or "row"
        estimate = row.get("estimated_tokens", "")
        notes = row.get("domain") or row.get("brand") or ""
        lines.append(f"| {index} | `{label}` | {estimate} | {notes} |")
    return "\n".join(lines) + "\n"


def _report_csv(rows: list[dict[str, Any]]) -> str:
    fields = sorted({key for row in rows for key in row.keys()}) or ["row"]
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue()


def _research_graph_report_from_payload(payload: Any) -> dict[str, Any] | None:
    graphs = extract_research_graphs(payload)
    if not graphs:
        return None
    graph = max(
        graphs,
        key=lambda item: int(item.get("node_count") or len(item.get("nodes") if isinstance(item.get("nodes"), list) else [])),
    )
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    node_rows = [
        {
            "id": node.get("id"),
            "type": node.get("type"),
            "label": node.get("label"),
        }
        for node in nodes
        if isinstance(node, Mapping)
    ]
    edge_rows = [
        {
            "source": edge.get("source"),
            "type": edge.get("type"),
            "target": edge.get("target"),
            "evidence_path": edge.get("evidence_path"),
        }
        for edge in edges
        if isinstance(edge, Mapping)
    ]
    return {
        "summary": graph_summary(graph),
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
        "entity_counts": dict(graph.get("entity_counts") or {}),
        "nodes": node_rows,
        "edges": edge_rows,
        "sources": list(graph.get("sources") or []) if isinstance(graph.get("sources"), list) else [],
        "diagnostics": dict(graph.get("diagnostics") or {}) if isinstance(graph.get("diagnostics"), Mapping) else {},
        "diff": dict(graph.get("diff") or {}) if isinstance(graph.get("diff"), Mapping) else {},
    }


def _research_graph_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    entity_counts = report.get("entity_counts") if isinstance(report.get("entity_counts"), Mapping) else {}
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), Mapping) else {}
    lines = [
        "",
        "## Research Graph",
        "",
        f"- Root: `{summary.get('root', '')}`",
        f"- Nodes: {report.get('node_count', 0)}",
        f"- Edges: {report.get('edge_count', 0)}",
        f"- Entity counts: `{json.dumps(entity_counts, ensure_ascii=False, sort_keys=True)}`",
    ]
    if diagnostics:
        lines.extend(
            [
                f"- Duplicate nodes: {diagnostics.get('duplicate_node_count', 0)}",
                f"- Orphan nodes: {diagnostics.get('orphan_node_count', 0)}",
                f"- Conflicts: {diagnostics.get('conflict_count', 0)}",
            ]
        )

    nodes = [node for node in report.get("nodes", []) if isinstance(node, Mapping)]
    if nodes:
        lines.extend(["", "### Entities", "", "| Type | ID | Label |", "|---|---|---|"])
        for node in nodes[:40]:
            lines.append(f"| {node.get('type', '')} | `{node.get('id', '')}` | {node.get('label', '')} |")
        if len(nodes) > 40:
            lines.append(f"| ... | ... | {len(nodes) - 40} more entities |")

    edges = [edge for edge in report.get("edges", []) if isinstance(edge, Mapping)]
    if edges:
        lines.extend(["", "### Relationships", "", "| Source | Type | Target | Evidence |", "|---|---|---|---|"])
        for edge in edges[:60]:
            lines.append(
                f"| `{edge.get('source', '')}` | {edge.get('type', '')} | `{edge.get('target', '')}` | `{edge.get('evidence_path', '')}` |"
            )
        if len(edges) > 60:
            lines.append(f"| ... | ... | ... | {len(edges) - 60} more relationships |")
    return "\n".join(lines)


def _report_figure_info(
    *,
    input_path: str,
    out: str | None,
    title: str,
    figure: str | None,
    figures_dir: str | None,
    figure_set: str,
    enabled: bool,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    if figure:
        path = Path(figure)
        if not path.is_file():
            raise ValueError(f"figure path does not exist: {figure}")
        return {
            "mode": "provided",
            "figures": [
                {
                    "name": path.stem,
                    "kind": "markdown_image",
                    "path": str(path),
                    "format": path.suffix.lower().lstrip(".") or "file",
                    "size_bytes": path.stat().st_size,
                    "markdown": _markdown_image_path(path),
                    "resource_uri": path_to_resource_uri(path, kind="output"),
                }
            ],
        }

    target_dir = Path(figures_dir) if figures_dir else _default_report_figures_dir(input_path=input_path, out=out)
    built = build_research_figures(input_path=input_path, out_dir=str(target_dir), title=f"{title} Figures", figure_set=figure_set)
    figures = []
    for item in built.get("figures", []):
        if not isinstance(item, Mapping):
            continue
        entry = dict(item)
        entry["markdown"] = _markdown_image_path(Path(str(item.get("path") or "")))
        entry["resource_uri"] = path_to_resource_uri(Path(str(item.get("path") or "")), kind="output")
        figures.append(entry)
    return {
        "mode": "generated",
        "schema_version": built.get("schema_version"),
        "figure_set": built.get("figure_set"),
        "available_figure_sets": built.get("available_figure_sets"),
        "data_summary": built.get("data_summary"),
        "provenance": built.get("provenance"),
        "figures": figures,
    }


def _default_report_figures_dir(*, input_path: str, out: str | None) -> Path:
    if out:
        return Path(out).with_suffix("").parent / f"{Path(out).stem}-figures"
    return Path(tempfile.gettempdir()) / "keepa-report-figures" / Path(input_path).with_suffix("").name


def _markdown_image_path(path: Path) -> str:
    return path.resolve().as_posix()


def _figures_markdown(figure_info: Mapping[str, Any]) -> str:
    lines = ["", "## Figures", ""]
    figures = [item for item in figure_info.get("figures", []) if isinstance(item, Mapping)]
    if not figures:
        lines.append("_No report figures available._")
        return "\n".join(lines)
    display_figures = [item for item in figures if item.get("name") != "agent-research-summary"] or figures
    for item in display_figures:
        image = item.get("markdown") or item.get("path")
        title = item.get("name") or "Keepa research figure"
        lines.append(f"![{title}]({image})")
        resource_uri = item.get("resource_uri")
        if resource_uri:
            lines.append("")
            lines.append(f"- MCP resource: `{resource_uri}`")
        source = item.get("source_data_path")
        if source:
            lines.append("")
            lines.append(f"- Source data: `{source}`")
    return "\n".join(lines)


def build_report(
    *,
    input_path: str,
    output_format: str,
    out: str | None,
    title: str,
    figure: str | None = None,
    figures_dir: str | None = None,
    figure_set: str = "all",
    embed_figures: bool = True,
) -> dict[str, Any]:
    payload = load_json_file(input_path)
    rows = _report_rows_from_input(payload)
    graph_report = _research_graph_report_from_payload(payload)
    fmt = output_format.lower()
    figure_info = _report_figure_info(
        input_path=input_path,
        out=out,
        title=title,
        figure=figure,
        figures_dir=figures_dir,
        figure_set=figure_set,
        enabled=embed_figures and fmt in {"markdown", "json"},
    )
    if fmt == "markdown":
        content: Any = _report_markdown(title, rows, input_path, graph_report)
        if figure_info is not None:
            content = str(content).rstrip() + "\n" + _figures_markdown(figure_info) + "\n"
        if graph_report is not None:
            content = str(content).rstrip() + "\n" + _research_graph_markdown(graph_report) + "\n"
    elif fmt == "csv":
        content = _report_csv(rows)
    elif fmt == "json":
        content = {"title": title, "source": input_path, "generated_at": utc_now_iso(), "rows": rows}
        if graph_report is not None:
            content["research_graph_report"] = graph_report
        if figure_info is not None:
            content["figures"] = figure_info
    else:
        raise ValueError("reports.build format must be markdown, json, or csv")

    data: dict[str, Any] = {
        "format": fmt,
        "row_count": len(rows),
        "research_graph": graph_report["summary"] if graph_report is not None else None,
        "source": input_path,
        "title": title,
        "provenance": build_cache_provenance(
            endpoint="local://reports.build",
            params={"input": input_path, "format": fmt, "title": title},
            source="local",
            out=out,
        ),
    }
    if figure_info is not None:
        data["figures"] = figure_info
    if out:
        if fmt == "json":
            data["output"] = write_json(out, content)
        else:
            data["output"] = write_text(out, str(content))
    else:
        data["content"] = content
    return data


def explain_cache(*, input_path: str | None, command: str | None, endpoint: str | None) -> dict[str, Any]:
    payload = load_json_file(input_path) if input_path else {}
    provenance = {}
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("cache_provenance"), Mapping):
            provenance = dict(data["cache_provenance"])
        elif isinstance(payload.get("cache_provenance"), Mapping):
            provenance = dict(payload["cache_provenance"])
        elif isinstance(data, Mapping) and isinstance(data.get("provenance"), Mapping):
            provenance = dict(data["provenance"])
        elif isinstance(payload.get("provenance"), Mapping):
            provenance = dict(payload["provenance"])
    payload_command = payload.get("command", "") if isinstance(payload, Mapping) else ""
    estimated = estimate_request_budget(command or str(payload_command)).to_dict()
    return {
        "input": input_path,
        "command": command or payload_command,
        "endpoint": endpoint or provenance.get("endpoint"),
        "source": provenance.get("source", "unknown"),
        "cache_hit": bool(provenance.get("cache_hit", False)),
        "params_hash": provenance.get("params_hash"),
        "fixture": provenance.get("fixture"),
        "out": provenance.get("out"),
        "estimated_tokens_saved": estimated["estimated_tokens"] if provenance.get("cache_hit") else 0,
        "estimated_tokens_if_live": estimated["estimated_tokens"],
        "worst_case_tokens_if_live": estimated["worst_case_tokens"],
    }


def explain_cache_key(*, method: str, endpoint: str, params: Mapping[str, Any], json_body: Any = None) -> dict[str, Any]:
    return explain_response_cache_key(method=method, endpoint=endpoint, params=params, json_body=json_body)


def cache_stats(*, cache_path: str | None = None) -> dict[str, Any]:
    cache = SQLiteResponseCache(cache_path or default_cache_path())
    stats = cache.stats()
    stats["notes"] = [
        "SQLite response cache stores successful live GET JSON responses only.",
        "dry-run, fixture, binary, POST, and disabled-cache requests are not persisted.",
    ]
    return stats


def inspect_cache(*, cache_key: str, cache_path: str | None = None) -> dict[str, Any]:
    cache = SQLiteResponseCache(cache_path or default_cache_path())
    result = cache.inspect(cache_key)
    result["notes"] = [
        "cache inspect returns metadata only and never includes cached response body.",
        "Use the cache_key from data.cache_provenance.cache_key for single-entry audits.",
    ]
    return result


def prune_expired_cache(*, dry_run: bool, cache_path: str | None = None) -> dict[str, Any]:
    cache = SQLiteResponseCache(cache_path or default_cache_path())
    result = cache.prune_expired(dry_run=dry_run)
    result["notes"] = [
        "Only expired SQLite response cache entries are removed.",
        "Use --dry-run to count expired entries before cleanup.",
    ]
    return result


def clear_cache(*, dry_run: bool, cache_path: str | None = None) -> dict[str, Any]:
    cache = SQLiteResponseCache(cache_path or default_cache_path())
    result = cache.clear(dry_run=dry_run)
    result["notes"] = [
        "SQLite response cache clear does not affect tests/fixtures or in-process Agent session cache.",
        "Use --dry-run before destructive cache cleanup when auditing release artifacts.",
    ]
    return result


def audit_cost(command_specs: list[Mapping[str, Any]]) -> dict[str, Any]:
    items = []
    totals = {"estimated_tokens": 0, "worst_case_tokens": 0}
    for spec in command_specs:
        command = str(spec.get("command", ""))
        params = dict(spec.get("params") or {})
        budget = estimate_request_budget(command, params).to_dict()
        item = {"command": command, "params": params, **budget}
        items.append(item)
        totals["estimated_tokens"] += int(budget["estimated_tokens"])
        totals["worst_case_tokens"] += int(budget["worst_case_tokens"])
    return {
        "items": items,
        "totals": totals,
        "requires_confirmation": any(bool(item["requires_confirmation"]) for item in items),
        "provenance": build_cache_provenance(
            endpoint="local://audit.cost",
            params={"commands": [item["command"] for item in items]},
            source="local",
        ),
    }
