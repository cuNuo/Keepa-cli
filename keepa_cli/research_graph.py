"""
keepa_cli/research_graph.py
文件说明：构建 Agent 友好的轻量实体关系图。
主要职责：为非产品命令生成统一 research_graph，便于 Agent 跨类目、商品、卖家与报告串联实体。
依赖边界：纯本地 JSON 转换，不访问 Keepa API。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RESEARCH_GRAPH_SCHEMA_VERSION = "2026-05-10.3"


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
    prefer_source: str | int | None = None,
) -> dict[str, Any]:
    nodes = [graph_node(root, "research_graph", label, graph_count=len(graphs))]
    edges: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen_node_ids: set[str] = {root}
    duplicate_node_ids: dict[str, int] = {}
    node_variants: dict[str, list[Mapping[str, Any]]] = {}
    variant_sources: dict[str, list[dict[str, Any]]] = {}
    root_ids: list[str] = []
    source_infos: list[dict[str, Any]] = []
    for index, graph in enumerate(graphs):
        if not isinstance(graph, Mapping):
            continue
        graph_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        graph_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        source_root = str(graph.get("root") or f"graph:{index + 1}")
        root_ids.append(source_root)
        source_weight = _source_weight(graph, index=index)
        source_info = _compact(
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
        source_infos.append(source_info)
        sources.append(source_info)
        for node in graph_nodes:
            if isinstance(node, Mapping):
                node_id = str(node.get("id") or "")
                item = dict(node)
                attributes = item.get("attributes")
                if isinstance(attributes, Mapping):
                    item["attributes"] = _compact({**dict(attributes), "source_weight": source_weight})
                if node_id:
                    node_variants.setdefault(node_id, []).append(item)
                    variant_sources.setdefault(node_id, []).append(source_info)
                if node_id in seen_node_ids:
                    duplicate_node_ids[node_id] = duplicate_node_ids.get(node_id, 1) + 1
                elif node_id:
                    seen_node_ids.add(node_id)
                nodes.append(item)
        for edge in graph_edges:
            if isinstance(edge, Mapping):
                edges.append(dict(edge))
        if source_root and any(isinstance(node, Mapping) and node.get("id") == source_root for node in graph_nodes):
            edges.append(graph_edge(root, source_root, "includes_graph", evidence_path=f"graphs.{index}.root"))

    merged = build_research_graph(root=root, nodes=nodes, edges=edges)
    merged["sources"] = sources
    diff = graph_diff(
        node_variants,
        variant_sources=variant_sources,
        prefer_source=prefer_source,
        sources=source_infos,
    )
    _apply_diff_resolutions(merged, node_variants=node_variants, variant_sources=variant_sources, diff=diff)
    merged["diagnostics"] = graph_diagnostics(
        merged,
        duplicate_node_ids=duplicate_node_ids,
        root_ids=root_ids,
        conflicts=diff.get("conflicts", []),
    )
    merged["diff"] = diff
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
    diff = graph.get("diff")
    if isinstance(diff, Mapping):
        summary["diff"] = {
            "changed_node_count": diff.get("changed_node_count", 0),
            "resolved_conflict_count": diff.get("resolved_conflict_count", 0),
            "preferred_source": diff.get("preferred_source"),
        }
    return summary


def graph_diff(
    node_variants: Mapping[str, list[Mapping[str, Any]]],
    *,
    variant_sources: Mapping[str, list[Mapping[str, Any]]] | None = None,
    prefer_source: str | int | None = None,
    sources: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    conflicts = _node_conflicts_from_variants(node_variants)
    source_lookup = _source_lookup(sources or [])
    preferred = _resolve_preferred_source(prefer_source, source_lookup)
    changes: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    source_variants = variant_sources or {}
    for conflict in conflicts:
        node_id = str(conflict.get("id") or "")
        variants = node_variants.get(node_id) or []
        variant_items = _variant_items(variants, source_variants.get(node_id) or [])
        changes.append(
            _compact(
                {
                    "id": node_id,
                    "labels": conflict.get("labels"),
                    "types": conflict.get("types"),
                    "seen": conflict.get("seen"),
                    "variants": variant_items,
                }
            )
        )
        winner = _choose_variant(variant_items, preferred_source=preferred)
        if winner:
            resolutions.append(
                _compact(
                    {
                        "id": node_id,
                        "selected_label": winner.get("label"),
                        "selected_type": winner.get("type"),
                        "source_index": winner.get("source_index"),
                        "source_root": winner.get("source_root"),
                        "source_weight": winner.get("source_weight"),
                        "strategy": "preferred_source" if preferred is not None and _variant_matches_source(winner, preferred) else "highest_source_weight",
                    }
                )
            )
    return _compact(
        {
            "changed_node_count": len(changes),
            "conflict_count": len(conflicts),
            "resolved_conflict_count": len(resolutions),
            "preferred_source": preferred,
            "conflicts": conflicts[:20],
            "changes": changes[:20],
            "resolutions": resolutions[:20],
        }
    )


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


def _apply_diff_resolutions(
    graph: dict[str, Any],
    *,
    node_variants: Mapping[str, list[Mapping[str, Any]]],
    variant_sources: Mapping[str, list[dict[str, Any]]],
    diff: Mapping[str, Any],
) -> None:
    resolutions = diff.get("resolutions")
    if not isinstance(resolutions, list):
        return
    selected_by_id = {str(item.get("id")): item for item in resolutions if isinstance(item, Mapping) and item.get("id")}
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not selected_by_id:
        return
    replaced: dict[str, dict[str, Any]] = {}
    for node_id, resolution in selected_by_id.items():
        variants = node_variants.get(node_id) or []
        sources = variant_sources.get(node_id) or []
        selected = _select_node_variant_for_resolution(variants, sources, resolution)
        if selected is not None:
            replaced[node_id] = dict(selected)
    if not replaced:
        return
    graph["nodes"] = [replaced.get(str(node.get("id") or ""), node) if isinstance(node, Mapping) else node for node in nodes]
    graph["entity_counts"] = entity_counts([dict(node) for node in graph["nodes"] if isinstance(node, Mapping)])


def _select_node_variant_for_resolution(
    variants: list[Mapping[str, Any]],
    sources: list[Mapping[str, Any]],
    resolution: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for index, variant in enumerate(variants):
        source = sources[index] if index < len(sources) else {}
        if resolution.get("source_index") is not None:
            if source.get("index") == resolution.get("source_index"):
                return variant
            continue
        if resolution.get("source_root") not in (None, "") and source.get("root") == resolution.get("source_root"):
            return variant
    return variants[-1] if variants else None


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


def _source_lookup(sources: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    lookup: dict[str, Mapping[str, Any]] = {}
    for source in sources:
        index = source.get("index")
        root = source.get("root")
        if index is not None:
            lookup[str(index)] = source
        if root not in (None, ""):
            lookup[str(root)] = source
    return lookup


def _resolve_preferred_source(prefer_source: str | int | None, lookup: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    if prefer_source in (None, ""):
        return None
    key = str(prefer_source)
    source = lookup.get(key)
    if source is None and key.isdigit():
        source = lookup.get(str(int(key)))
    if source is None:
        return {"requested": key, "matched": False}
    return _compact(
        {
            "requested": key,
            "matched": True,
            "index": source.get("index"),
            "root": source.get("root"),
            "source_weight": source.get("source_weight"),
            "confidence": source.get("confidence"),
        }
    )


def _variant_items(variants: list[Mapping[str, Any]], sources: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, variant in enumerate(variants):
        source = sources[index] if index < len(sources) else {}
        items.append(
            _compact(
                {
                    "label": variant.get("label"),
                    "type": variant.get("type"),
                    "source_index": source.get("index"),
                    "source_root": source.get("root"),
                    "source_weight": source.get("source_weight"),
                    "confidence": source.get("confidence"),
                }
            )
        )
    return items


def _choose_variant(variants: list[Mapping[str, Any]], *, preferred_source: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not variants:
        return None
    if preferred_source and preferred_source.get("matched"):
        for variant in variants:
            if _variant_matches_source(variant, preferred_source):
                return variant
    return max(variants, key=lambda item: int(item.get("source_weight") or 0))


def _variant_matches_source(variant: Mapping[str, Any], preferred_source: Mapping[str, Any]) -> bool:
    preferred_index = preferred_source.get("index")
    preferred_root = preferred_source.get("root")
    if preferred_index is not None:
        return variant.get("source_index") == preferred_index
    return preferred_root not in (None, "") and variant.get("source_root") == preferred_root


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
