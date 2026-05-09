"""
tests/test_schema_snapshot.py
文件说明：验证 Agent 输出 schema snapshot。
主要职责：冻结 JSON envelope 与 stdio event 的字段结构，避免 Agent 契约漂移。
依赖边界：只比较字段与类型形状，不锁定完整业务数据。
"""

import json
import unittest
from pathlib import Path

from keepa_cli.agent.stdio import handle_stdio_message
from keepa_cli.schema_snapshot import build_agent_schema_snapshot
from keepa_cli.service import run_command


SNAPSHOT = Path("tests/snapshots/agent_schema_snapshot.json")


class SchemaSnapshotTests(unittest.TestCase):
    def test_agent_schema_snapshot_matches_committed_contract(self):
        payloads = {
            "doctor": run_command("doctor", env={}),
            "products_get": run_command(
                "products.get",
                {
                    "asin": ["B001GZ6QEC"],
                    "domain": "US",
                    "history": "0",
                    "fixture": "product_B001GZ6QEC.json",
                },
                env={},
            ),
            "categories_search": run_command(
                "categories.search",
                {"term": "home kitchen", "domain": "US", "fixture": "category_search_home.json"},
                env={},
            ),
            "history_trend": run_command(
                "history.trend",
                {
                    "asin": "B001GZ6QEC",
                    "domain": "US",
                    "series": "amazon",
                    "window_days": [30],
                    "fixture": "product_history_B001GZ6QEC.json",
                },
                env={},
            ),
            "finder_query": run_command(
                "finder.query",
                {
                    "selection_file": "tests/fixtures/finder_selection.json",
                    "domain": "US",
                    "dry_run": True,
                    "max_tokens": 25,
                },
                env={},
            ),
            "bestsellers_get": run_command(
                "bestsellers.get",
                {"category": "172282", "domain": "US", "dry_run": True},
                env={},
            ),
            "sellers_get": run_command(
                "sellers.get",
                {
                    "seller": ["A2L77EE7U53NWQ"],
                    "domain": "US",
                    "storefront": True,
                    "fixture": "seller_A2L77EE7U53NWQ.json",
                },
                env={},
            ),
            "stdio_products_get": handle_stdio_message(
                json.dumps(
                    {
                        "id": "snap-1",
                        "method": "products.get",
                        "params": {
                            "asin": ["B001GZ6QEC"],
                            "domain": "US",
                            "history": "0",
                            "fixture": "product_B001GZ6QEC.json",
                        },
                    }
                ),
                env={},
            ),
        }

        actual = build_agent_schema_snapshot(payloads)
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
