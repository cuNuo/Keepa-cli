"""
keepa_cli/schema_docs.py
文件说明：从测试 snapshot 生成 Agent schema 文档。
主要职责：导出产品 Agent 视图的可校验 JSON 形状说明。
依赖边界：只读取本地 snapshot，不访问网络或 Keepa API。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def generate_product_agent_schema(snapshot_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source = Path(snapshot_path)
    target = Path(output_path)
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    shape = snapshot.get("products_get_agent_view")
    if not isinstance(shape, dict):
        raise ValueError("snapshot does not contain products_get_agent_view")
    document = {
        "title": "Keepa CLI products.get agent view schema",
        "schema_kind": "shape-snapshot",
        "source_snapshot": str(source),
        "command": "products.get",
        "view": "agent_product",
        "shape": shape,
        "notes": [
            "This file is generated from tests/snapshots/agent_schema_snapshot.json.",
            "Values are type names, not example payload values.",
            "Use the CLI envelope ok/error fields before consuming data.",
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "path": str(target),
        "source_snapshot": str(source),
        "format": "json",
        "size_bytes": target.stat().st_size,
    }
