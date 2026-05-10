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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from keepa_cli.agent_contract import build_action, build_evidence_index
from keepa_cli.cache import SQLiteResponseCache, build_cache_provenance, default_cache_path, explain_response_cache_key
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
    return []


def build_browse_snapshot(*, input_path: str | None, out_dir: str, title: str) -> dict[str, Any]:
    payload = load_json_file(input_path) if input_path else {}
    rows = _product_rows(payload)
    generated_at = utc_now_iso()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "index.html"
    data_path = out / "data.json"
    write_json(data_path, {"generated_at": generated_at, "source": input_path, "rows": rows})

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
    return {
        "id": step_id,
        "title": title,
        "tool": action["tool"],
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
                params={"category": "<CATEGORY_ID>", "domain": domain, "limit": 25, "hydrate_top": hydrate_top, "yes": True},
                cli=f"categories products <CATEGORY_ID> --domain {domain} --limit 25"
                + (f" --hydrate-top {hydrate_top}" if hydrate_top else "")
                + " --yes",
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


def build_workflow_plan(*, name: str, term: str | None, asin: str | None, domain: str, goal: str, hydrate_top: int) -> dict[str, Any]:
    if name == "category-research":
        if not term:
            raise ValueError("workflow plan category-research requires --term")
        steps = _category_research_plan(term=term, domain=domain, hydrate_top=hydrate_top)
    elif name == "product-research":
        if not asin:
            raise ValueError("workflow plan product-research requires --asin")
        steps = _product_research_plan(asin=asin, domain=domain, goal=goal)
    else:
        raise ValueError("workflow plan supports category-research and product-research")

    totals = {
        "estimated_tokens": sum(int(step["estimated_tokens"]) for step in steps),
        "worst_case_tokens": sum(int(step["worst_case_tokens"]) for step in steps),
        "requires_confirmation": any(bool(step["requires_confirmation"]) for step in steps),
    }
    return {
        "view": "workflow_plan",
        "name": name,
        "domain": domain,
        "goal": goal,
        "steps": steps,
        "totals": totals,
        "parallel_groups": sorted({str(step["parallel_group"]) for step in steps if step.get("parallel_group")}),
        "agent_brief": {
            "view": "workflow_plan",
            "one_line": f"{name} plan with {len(steps)} steps; estimated {totals['estimated_tokens']} tokens",
            "key_facts": {"name": name, "step_count": len(steps), **totals},
            "read_order": ["agent_brief", "steps", "totals", "evidence_index"],
        },
        "data_quality": {
            "present": ["steps", "totals", "next_actions"],
            "missing": [],
            "confidence": "high",
            "notes": ["workflow plan is local-only and does not consume Keepa tokens"],
        },
        "selection_signals": {"step_count": len(steps), "parallel_group_count": len({step["parallel_group"] for step in steps if step.get("parallel_group")})},
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
                "totals": ("totals", "summary", "Total estimated and worst-case token budget."),
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


def _report_markdown(title: str, rows: list[dict[str, Any]], source: str) -> str:
    lines = [
        f"# {title}",
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


def build_report(*, input_path: str, output_format: str, out: str | None, title: str) -> dict[str, Any]:
    payload = load_json_file(input_path)
    rows = _report_rows_from_input(payload)
    graph_report = _research_graph_report_from_payload(payload)
    fmt = output_format.lower()
    if fmt == "markdown":
        content: Any = _report_markdown(title, rows, input_path)
        if graph_report is not None:
            content = str(content).rstrip() + "\n" + _research_graph_markdown(graph_report) + "\n"
    elif fmt == "csv":
        content = _report_csv(rows)
    elif fmt == "json":
        content = {"title": title, "source": input_path, "generated_at": utc_now_iso(), "rows": rows}
        if graph_report is not None:
            content["research_graph_report"] = graph_report
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
    estimated = estimate_request_budget(command or str(payload.get("command", ""))).to_dict()
    return {
        "input": input_path,
        "command": command or payload.get("command"),
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
