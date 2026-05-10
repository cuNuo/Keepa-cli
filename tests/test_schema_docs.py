"""
tests/test_schema_docs.py
文件说明：验证 Agent schema 文档生成。
主要职责：确保产品 Agent 视图 schema 能从 snapshot 稳定导出。
依赖边界：只使用本地 snapshot 与临时目录，不访问网络。
"""

import json
import tempfile
import unittest
from pathlib import Path

from keepa_cli.schema_docs import generate_product_agent_schema
from keepa_cli.service import run_command


class SchemaDocsTests(unittest.TestCase):
    def test_generate_product_agent_schema_writes_shape_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "products.agent-view.schema.json"
            metadata = generate_product_agent_schema("tests/snapshots/agent_schema_snapshot.json", output_path)
            document = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["path"], str(output_path))
        self.assertEqual(document["command"], "products.get")
        self.assertEqual(document["view"], "agent_product")
        self.assertEqual(document["shape"]["data"]["products"][0]["identity"]["asin"], "str")

    def test_schema_generate_command_writes_schema_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "schema.json"
            payload = run_command(
                "schema.generate",
                {"snapshot": "tests/snapshots/agent_schema_snapshot.json", "out": str(output_path)},
                env={},
            )

            self.assertTrue(payload["ok"])
            self.assertTrue(output_path.is_file())


if __name__ == "__main__":
    unittest.main()
