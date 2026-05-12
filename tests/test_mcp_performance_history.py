"""
tests/test_mcp_performance_history.py
文件说明：验证 MCP 性能历史汇总与阈值建议脚本。
主要职责：确保 CI artifact 可被汇总为真实 p95 历史建议，支持后续收紧 performance gate。
依赖边界：只使用内联 JSON，不运行真实 MCP 基准，不访问网络。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_mcp_performance_history import summarize_history


REPO_ROOT = Path(__file__).resolve().parents[1]


def _report(p95_ms: float, json_bytes: int) -> dict:
    return {
        "ok": True,
        "benchmarks": [
            {
                "label": "initialize",
                "p95_ms": p95_ms,
                "json_bytes": json_bytes,
                "text_fallback_bytes": 0,
                "structured_content_bytes": 0,
                "cache_hit_p95_ms": None,
            },
            {
                "label": "products_get_fixture",
                "p95_ms": 50,
                "json_bytes": 10_000,
                "text_fallback_bytes": 5_000,
                "structured_content_bytes": 8_000,
                "cache_hit_p95_ms": 20,
            },
        ],
    }


class McpPerformanceHistoryTests(unittest.TestCase):
    def test_summarize_history_uses_real_p95_and_flags_tightening(self):
        payload = summarize_history([_report(2, 1_000), _report(3, 1_200), _report(4, 1_100)], min_samples=3)
        self.assertTrue(payload["ready_to_tighten"])
        initialize = payload["suggested_thresholds"]["initialize"]
        self.assertEqual(initialize["p95_ms"], 10.0)
        self.assertEqual(initialize["json_bytes"], 1440)
        changes = {(item["label"], item["metric"]): item["change"] for item in payload["decisions"]}
        self.assertEqual(changes[("initialize", "p95_ms")], "tighten")
        self.assertEqual(changes[("initialize", "json_bytes")], "tighten")

    def test_cli_reads_directory_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "one.json").write_text(json.dumps(_report(2, 1_000)), encoding="utf-8")
            (root / "two.json").write_text(json.dumps(_report(3, 1_200)), encoding="utf-8")
            (root / "notes.json").write_text(json.dumps({"ok": True, "kind": "not-a-performance-report"}), encoding="utf-8")
            (root / "partial.json").write_text("{", encoding="utf-8")
            out = root / "summary.json"
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "cp1252"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "summarize_mcp_performance_history.py"),
                    str(root),
                    "--json",
                    "--out",
                    str(out),
                    "--min-samples",
                    "3",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=REPO_ROOT,
                env=env,
                check=True,
            )
            stdout_payload = json.loads(result.stdout)
            file_payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertFalse(stdout_payload["ready_to_tighten"])
        self.assertEqual(file_payload["report_count"], 2)
        self.assertIn("one.json", "\n".join(file_payload["input_files"]))


if __name__ == "__main__":
    unittest.main()
