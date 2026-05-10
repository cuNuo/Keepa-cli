"""
scripts/generate_agent_schema.py
文件说明：生成 Agent schema 文档。
主要职责：把测试 snapshot 中的产品 Agent 视图形状导出为 docs/schema JSON。
依赖边界：纯本地文件转换，不访问网络。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from keepa_cli.schema_docs import generate_product_agent_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Keepa CLI Agent schema 文档。")
    parser.add_argument("--snapshot", default="tests/snapshots/agent_schema_snapshot.json", help="输入 snapshot 路径。")
    parser.add_argument("--out", default="docs/schema/products.agent-view.schema.json", help="输出 schema 文档路径。")
    args = parser.parse_args()
    metadata = generate_product_agent_schema(Path(args.snapshot), Path(args.out))
    print(f"wrote agent schema: {metadata['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
