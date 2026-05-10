"""
keepa_cli/research_graph.py
文件说明：构建 Agent 友好的轻量实体关系图。
主要职责：为非产品命令生成统一 research_graph，便于 Agent 跨类目、商品、卖家与报告串联实体。
依赖边界：纯本地 JSON 转换，不访问 Keepa API。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RESEARCH_GRAPH_SCHEMA_VERSION = "2026-05-10.2"


def graph_node(node_id: str, node_type: str, label: Any, **attributes: Any) -> dict[str, Any]:
    return _compact(
        {
            "id": node_id,
            "type": node_type,
            "label": _truncate_text(label, 120),
            "attributes": _compact(dict(attributes)),
        }
    )


def graph_edge(source: str, target: str, relation: str, *, evidence_path: str) -> dict[str, Any]:
    return {"source": source, "target": target, "type": relation, "evidence_path": evidence_path}


def build_research_graph(
    *,
    root: str | None = None,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ordered_nodes = _dedupe_graph_nodes(nodes or [])
    ordered_edges = _dedupe_graph_edges(edges or [])
    return _compact(
        {
            "schema_version": RESEARCH_GRAPH_SCHEMA_VERSION,
            "root": root,
            "node_count": len(ordered_nodes),
            "edge_count": len(ordered_edges),
            "entity_counts": entity_counts(ordered_nodes),
            "nodes": ordered_nodes,
            "edges": ordered_edges,
        }
    )


def merge_research_graphs(
    graphs: list[Mapping[str, Any]],
    *,
    root: str = "merged_research_graph",
    label: str = "merged research graph",
) -> dict[str, Any]:
    nodes = [graph_node(root, "research_graph", label, graph_count=len(graphs))]
    edges: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen_node_ids: set[str] = {root}
    duplicate_node_ids: dict[str, int] = {}
    node_variants: dict[str, list[Mapping[str, Any]]] = {}
    root_ids: list[str] = []
    for index, graph in enumerate(graphs):
        if not isinstance(graph, Mapping):
            continue
        graph_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        graph_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        source_root = str(graph.get("root") or f"graph:{index + 1}")
        root_ids.append(source_root)
        source_weight = _source_weight(graph, index=index)
        sources.append(
            _compact(
                {
                    "index": index,
                    "root": source_root,
                    "node_count": graph.get("node_count"),
                    "edge_count": graph.get("edge_count"),
                    "entity_counts": graph.get("entity_counts"),
                    "source_weight": source_weight,
                    "confidence": _source_confidence(source_weight),
                }
            )
        )
        for node in graph_nodes:
            if isinstance(node, Mapping):
                node_id = str(node.get("id") or "")
                if node_id:
                    node_variants.setdefault(node_id, []).append(node)
                if node_id in seen_node_ids:
                    duplicate_node_ids[node_id] = duplicate_node_ids.get(node_id, 1) + 1
                elif node_id:
                    seen_node_ids.add(node_id)
                item = dict(node)
                attributes = item.get("attributes")
                if isinstance(attributes, Mapping):
                    item["attributes"] = _compact({**dict(attributes), "source_weight": source_weight})
                nodes.append(item)
        for edge in graph_edges:
            if isinstance(edge, Mapping):
                edges.append(dict(edge))
        if source_root and any(isinstance(node, Mapping) and node.get("id") == source_root for node in graph_nodes):
            edges.append(graph_edge(root, source_root, "includes_graph", evidence_path=f"graphs.{index}.root"))

    merged = build_research_graph(root=root, nodes=nodes, edges=edges)
    merged["sources"] = sources
    merged["diagnostics"] = graph_diagnostics(
        merged,
        duplicate_node_ids=duplicate_node_ids,
        root_ids=root_ids,
        conflicts=_node_conflicts_from_variants(node_variants),
    )
    return merged


def extract_research_graphs(value: Any) -> list[dict[str, Any]]:
    graphs: list[dict[str, Any]] = []
    _collect_research_graphs(value, graphs)
    return graphs


def graph_summary(graph: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "schema_version": graph.get("schema_version"),
        "root": graph.get("root"),
        "node_count": graph.get("node_count", 0),
        "edge_count": graph.get("edge_count", 0),
        "entity_counts": graph.get("entity_counts", {}),
        "source_count": len(graph.get("sources") if isinstance(graph.get("sources"), list) else []),
    }
    diagnostics = graph.get("diagnostics")
    if isinstance(diagnostics, Mapping):
        summary["diagnostics"] = {
            "duplicate_node_count": diagnostics.get("duplicate_node_count", 0),
            "orphan_node_count": diagnostics.get("orphan_node_count", 0),
            "conflict_count": diagnostics.get("conflict_count", 0),
            "highest_source_weight": diagnostics.get("highest_source_weight", 0),
        }
    return summary


def graph_diagnostics(
    graph: Mapping[str, Any],
    *,
    duplicate_node_ids: Mapping[str, int] | None = None,
    root_ids: list[str] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    node_ids = {str(node.get("id") or "") for node in nodes if isinstance(node, Mapping) and node.get("id")}
    connected_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source:
            connected_ids.add(source)
        if target:
            connected_ids.add(target)
    root_id = str(graph.get("root") or "")
    source_roots = set(root_ids or [])
    orphan_ids = sorted(node_id for node_id in node_ids - connected_ids if node_id and node_id not in {root_id, *source_roots})
    duplicates = [
        {"id": node_id, "seen": count}
        for node_id, count in sorted((duplicate_node_ids or {}).items())
        if count > 1
    ]
    conflict_items = conflicts if conflicts is not None else _node_conflicts(nodes)
    source_weights = [_node_source_weight(node) for node in nodes if isinstance(node, Mapping)]
    return _compact(
        {
            "duplicate_node_count": len(duplicates),
            "duplicate_nodes": duplicates[:20],
            "orphan_node_count": len(orphan_ids),
            "orphan_nodes": orphan_ids[:20],
            "conflict_count": len(conflict_items),
            "conflicts": conflict_items[:20],
            "highest_source_weight": max(source_weights) if source_weights else 0,
            "lowest_source_weight": min(source_weights) if source_weights else 0,
        }
    )


def build_category_graph(
    *,
    category_id: str,
    name: Any = None,
    parent: Any = None,
    children: list[Any] | None = None,
    evidence_path: str = "category",
) -> dict[str, Any]:
    root = f"category:{category_id}"
    nodes = [graph_node(root, "category", name or category_id, category_id=category_id)]
    edges: list[dict[str, Any]] = []
    if parent not in (None, "", 0, "0"):
        parent_id = f"category:{parent}"
        nodes.append(graph_node(parent_id, "category", parent, category_id=str(parent), role="parent"))
        edges.append(graph_edge(parent_id, root, "parent_of", evidence_path=f"{evidence_path}.parent"))
    for child in children or []:
        child_id = f"category:{child}"
        nodes.append(graph_node(child_id, "category", child, category_id=str(child), role="child"))
        edges.append(graph_edge(root, child_id, "parent_of", evidence_path=f"{evidence_path}.children"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def build_category_candidates_graph(candidates: list[Mapping[str, Any]], *, term: str) -> dict[str, Any]:
    root = f"search:{_graph_id_part(term)}"
    nodes = [graph_node(root, "search_term", term, term=term)]
    edges: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        category_id = str(candidate.get("category_id") or candidate.get("catId") or "")
        if not category_id:
            continue
        node_id = f"category:{category_id}"
        nodes.append(graph_node(node_id, "category", candidate.get("name") or category_id, category_id=category_id, matched=candidate.get("matched")))
        edges.append(graph_edge(root, node_id, "matched_category", evidence_path=f"category_candidates.{index}"))
        parent = candidate.get("parent")
        if parent not in (None, "", 0, "0"):
            parent_id = f"category:{parent}"
            nodes.append(graph_node(parent_id, "category", parent, category_id=str(parent), role="parent"))
            edges.append(graph_edge(parent_id, node_id, "parent_of", evidence_path=f"category_candidates.{index}.parent"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def build_category_products_graph(*, category_id: str, candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    root = f"category:{category_id}"
    nodes = [graph_node(root, "category", category_id, category_id=category_id)]
    edges: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        asin = str(candidate.get("asin") or "")
        if not asin:
            continue
        product_id = f"product:{asin}"
        nodes.append(graph_node(product_id, "product", asin, asin=asin, rank=candidate.get("rank")))
        edges.append(graph_edge(root, product_id, "has_candidate", evidence_path=f"candidates.{index}"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def build_selection_graph(*, command: str, selection: Mapping[str, Any], body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = f"selection:{command}"
    nodes = [graph_node(root, "selection", command, command=command, selection_keys=sorted(str(key) for key in selection))]
    edges: list[dict[str, Any]] = []
    category_values = _selection_values(selection, prefixes=("categories", "category"))
    for index, category in enumerate(category_values):
        category_id = str(category)
        node_id = f"category:{category_id}"
        nodes.append(graph_node(node_id, "category", category_id, category_id=category_id))
        edges.append(graph_edge(root, node_id, "filters_category", evidence_path=f"selection.categories.{index}"))
    for index, asin in enumerate(_asins_from_body(body or {})):
        product_id = f"product:{asin}"
        nodes.append(graph_node(product_id, "product", asin, asin=asin))
        edges.append(graph_edge(root, product_id, "returns_product", evidence_path=f"body.{index}"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def build_seller_graph(*, sellers: list[str], body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = "seller_request"
    nodes = [graph_node(root, "seller_request", "seller request", seller_count=len(sellers))]
    edges: list[dict[str, Any]] = []
    seller_map = body.get("sellers") if isinstance(body, Mapping) and isinstance(body.get("sellers"), Mapping) else {}
    for seller_id in sellers:
        raw = seller_map.get(seller_id) if isinstance(seller_map.get(seller_id), Mapping) else {}
        node_id = f"seller:{seller_id}"
        nodes.append(
            graph_node(
                node_id,
                "seller",
                raw.get("sellerName") or seller_id,
                seller_id=seller_id,
                rating=raw.get("rating"),
                rating_count=raw.get("ratingCount"),
                has_storefront=raw.get("hasStorefront"),
            )
        )
        edges.append(graph_edge(root, node_id, "requests_seller", evidence_path="request.params_redacted.seller"))
        for index, asin in enumerate(raw.get("asinList") if isinstance(raw.get("asinList"), list) else []):
            product_id = f"product:{asin}"
            nodes.append(graph_node(product_id, "product", asin, asin=asin))
            edges.append(graph_edge(node_id, product_id, "sells_product", evidence_path=f"body.sellers.{seller_id}.asinList.{index}"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def build_deals_graph(*, deals: list[Mapping[str, Any]], command: str = "deals.query") -> dict[str, Any]:
    root = f"deal_set:{command}"
    nodes = [graph_node(root, "deal_set", command, deal_count=len(deals))]
    edges: list[dict[str, Any]] = []
    for index, deal in enumerate(deals):
        asin = str(deal.get("asin") or "")
        if not asin:
            continue
        product_id = f"product:{asin}"
        deal_id = f"deal:{asin}:{index + 1}"
        nodes.append(graph_node(product_id, "product", deal.get("title") or asin, asin=asin))
        nodes.append(graph_node(deal_id, "deal", deal.get("title") or asin, asin=asin, current=deal.get("current"), delta_percent=deal.get("deltaPercent")))
        edges.append(graph_edge(root, deal_id, "contains_deal", evidence_path=f"body.deals.{index}"))
        edges.append(graph_edge(deal_id, product_id, "for_product", evidence_path=f"body.deals.{index}.asin"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def build_topsellers_graph(*, sellers: list[Mapping[str, Any]], category_id: str | None = None) -> dict[str, Any]:
    root = f"top_sellers:{category_id or 'all'}"
    nodes = [graph_node(root, "seller_ranking", "top sellers", category_id=category_id, seller_count=len(sellers))]
    edges: list[dict[str, Any]] = []
    if category_id:
        category_node = f"category:{category_id}"
        nodes.append(graph_node(category_node, "category", category_id, category_id=category_id))
        edges.append(graph_edge(root, category_node, "ranked_in_category", evidence_path="request.params_redacted.category"))
    for index, seller in enumerate(sellers):
        seller_id = str(seller.get("sellerId") or seller.get("seller_id") or "")
        if not seller_id:
            continue
        node_id = f"seller:{seller_id}"
        raw_category = seller.get("categoryId") or category_id
        nodes.append(
            graph_node(
                node_id,
                "seller",
                seller.get("sellerName") or seller_id,
                seller_id=seller_id,
                rating_count=seller.get("ratingCount"),
                category_id=str(raw_category) if raw_category not in (None, "") else None,
            )
        )
        edges.append(graph_edge(root, node_id, "contains_seller", evidence_path=f"body.topSellers.{index}"))
        if raw_category not in (None, ""):
            category_node = f"category:{raw_category}"
            nodes.append(graph_node(category_node, "category", raw_category, category_id=str(raw_category)))
            edges.append(graph_edge(node_id, category_node, "ranked_in_category", evidence_path=f"body.topSellers.{index}.categoryId"))
    return build_research_graph(root=root, nodes=nodes, edges=edges)


def entity_counts(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        node_type = str(node.get("type") or "unknown")
        counts[node_type] = counts.get(node_type, 0) + 1
    return dict(sorted(counts.items()))


def _is_research_graph(value: Mapping[str, Any]) -> bool:
    return isinstance(value.get("nodes"), list) and isinstance(value.get("edges"), list) and "entity_counts" in value


def _collect_research_graphs(value: Any, graphs: list[dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        if _is_research_graph(value):
            graphs.append(dict(value))
            return
        for item in value.values():
            _collect_research_graphs(item, graphs)
    elif isinstance(value, list):
        for item in value:
            _collect_research_graphs(item, graphs)


def _selection_values(selection: Mapping[str, Any], *, prefixes: tuple[str, ...]) -> list[Any]:
    values: list[Any] = []
    for key, value in selection.items():
        key_text = str(key).lower()
        if not any(key_text.startswith(prefix) for prefix in prefixes):
            continue
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    return values


def _asins_from_body(body: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("deals", "products", "asinList", "asins"):
        raw = body.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping) and item.get("asin"):
                    values.append(str(item["asin"]))
                elif isinstance(item, str):
                    values.append(item)
    return values


def _dedupe_graph_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        if node_id:
            deduped[node_id] = node
    return sorted(deduped.values(), key=lambda item: (str(item.get("type") or ""), str(item.get("id") or "")))


def _dedupe_graph_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (str(edge.get("source") or ""), str(edge.get("target") or ""), str(edge.get("type") or ""))
        if all(key):
            deduped[key] = edge
    return sorted(deduped.values(), key=lambda item: (str(item.get("source") or ""), str(item.get("type") or ""), str(item.get("target") or "")))


def _source_weight(graph: Mapping[str, Any], *, index: int) -> int:
    node_count = graph.get("node_count")
    edge_count = graph.get("edge_count")
    if not isinstance(node_count, int):
        node_count = len(graph.get("nodes")) if isinstance(graph.get("nodes"), list) else 0
    if not isinstance(edge_count, int):
        edge_count = len(graph.get("edges")) if isinstance(graph.get("edges"), list) else 0
    entity_count = len(graph.get("entity_counts") or {}) if isinstance(graph.get("entity_counts"), Mapping) else 0
    return max(1, int(node_count) + int(edge_count) + entity_count - index)


def _source_confidence(source_weight: int) -> str:
    if source_weight >= 12:
        return "high"
    if source_weight >= 5:
        return "medium"
    return "low"


def _node_source_weight(node: Mapping[str, Any]) -> int:
    attributes = node.get("attributes")
    if isinstance(attributes, Mapping):
        value = attributes.get("source_weight")
        if isinstance(value, int):
            return value
    return 0


def _node_conflicts(nodes: list[Any]) -> list[dict[str, Any]]:
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for node in nodes:
        if isinstance(node, Mapping) and node.get("id"):
            by_id.setdefault(str(node["id"]), []).append(node)
    return _node_conflicts_from_variants(by_id)


def _node_conflicts_from_variants(by_id: Mapping[str, list[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for node_id, items in sorted(by_id.items()):
        labels = sorted({str(item.get("label")) for item in items if item.get("label") not in (None, "")})
        types = sorted({str(item.get("type")) for item in items if item.get("type") not in (None, "")})
        if len(labels) > 1 or len(types) > 1:
            conflicts.append(_compact({"id": node_id, "labels": labels, "types": types, "seen": len(items)}))
    return conflicts


def _graph_id_part(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_")[:80]


def _truncate_text(value: Any, limit: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, {}, [])}
