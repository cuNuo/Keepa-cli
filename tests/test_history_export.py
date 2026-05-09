"""
tests/test_history_export.py
文件说明：验证 Keepa 历史 csv 展开、导出和趋势分析。
主要职责：覆盖 Keepa minute 转换、价格/排名序列展开、CSV/JSONL 输出和趋势摘要。
依赖边界：只读取本地 fixture，不访问真实 Keepa API。
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keepa_cli.analysis import analyze_history_rows
from keepa_cli.history_export import (
    extract_history_rows,
    history_rows_to_csv,
    history_rows_to_jsonl,
    write_history_export,
)
from keepa_cli.keepa_time import keepa_minutes_to_iso


FIXTURE = Path("tests/fixtures/product_history_B001GZ6QEC.json")


def _fixture_product():
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return body["products"][0]


class HistoryExportTests(unittest.TestCase):
    def test_keepa_minutes_convert_to_utc_iso(self):
        self.assertEqual(keepa_minutes_to_iso(0), "2011-01-01T00:00:00Z")

    def test_extract_history_rows_filters_missing_prices(self):
        rows = extract_history_rows(_fixture_product(), ["amazon"])

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["asin"], "B001GZ6QEC")
        self.assertEqual(rows[0]["series"], "amazon")
        self.assertEqual(rows[0]["raw_value"], 1299)
        self.assertEqual(rows[0]["value"], 12.99)
        self.assertEqual(rows[0]["unit"], "currency")

    def test_csv_and_jsonl_export_are_agent_readable(self):
        rows = extract_history_rows(_fixture_product(), ["amazon", "sales_rank"])

        csv_text = history_rows_to_csv(rows)
        jsonl_text = history_rows_to_jsonl(rows)

        self.assertIn("asin,series,timestamp,keepa_minute,value,raw_value,unit", csv_text)
        self.assertIn("B001GZ6QEC,amazon", csv_text)
        first_jsonl = json.loads(jsonl_text.splitlines()[0])
        self.assertEqual(first_jsonl["series"], "amazon")

    def test_write_history_export_returns_path_rows_and_fields(self):
        rows = extract_history_rows(_fixture_product(), ["new"])
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "history.jsonl"
            metadata = write_history_export(rows, output_path, "jsonl")

            self.assertTrue(output_path.is_file())
            self.assertEqual(metadata["path"], str(output_path))
            self.assertEqual(metadata["row_count"], 3)
            self.assertIn("timestamp", metadata["fields"])

    def test_analyze_history_rows_returns_trend_summary(self):
        rows = extract_history_rows(_fixture_product(), ["amazon"])

        analysis = analyze_history_rows(rows, window_days=[30, 90])
        amazon = analysis["series"]["amazon"]["all_time"]

        self.assertEqual(amazon["points"], 3)
        self.assertEqual(amazon["min"]["value"], 10.99)
        self.assertEqual(amazon["max"]["value"], 12.99)
        self.assertEqual(amazon["latest"]["value"], 10.99)
        self.assertEqual(amazon["change"]["absolute"], -2.0)
        self.assertIn("30", analysis["series"]["amazon"]["windows"])


if __name__ == "__main__":
    unittest.main()
