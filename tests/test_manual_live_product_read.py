"""
tests/test_manual_live_product_read.py
文件说明：验证手动产品 live read 流程默认不会访问真实 Keepa API。
主要职责：覆盖 dry-run token budget、cache provenance 与脱敏摘要。
依赖边界：不设置 --yes-live，不读取真实 token。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class ManualLiveProductReadTests(unittest.TestCase):
    def test_manual_live_product_read_defaults_to_dry_run(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/manual_live_product_read.py",
                "--asin",
                "B001GZ6QEC",
                "--json",
            ],
            check=True,
            cwd=Path.cwd(),
            encoding="utf-8",
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["live_executed"])
        self.assertEqual(payload["token_budget"]["worst_case_tokens"], 1)
        self.assertEqual(payload["dry_run"]["cache_provenance"]["source"], "dry-run")
        self.assertNotIn("KEEPA_API_KEY", completed.stdout)


if __name__ == "__main__":
    unittest.main()
