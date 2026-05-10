"""
tests/test_agent_eval_fixtures.py
文件说明：验证固定 Agent 评测任务的最终 JSON 质量。
主要职责：覆盖类目候选、三 ASIN deal 对比、offers 缺口判断和 Finder scaffold。
依赖边界：只使用离线 fixture，不访问真实 Keepa API。
"""

import json
import unittest
from pathlib import Path
from typing import Any

from keepa_cli.agent_eval import check_agent_eval_fixtures
from keepa_cli.service import run_command


EVAL_DIR = Path("tests/agent_eval_fixtures")
FIXTURE_DIR = Path("tests/fixtures")


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise AssertionError(f"cannot resolve {path!r}; stopped at {part!r}")
    return current


class AgentEvaluationFixtureTests(unittest.TestCase):
    def test_agent_evaluation_specs_have_stable_outcomes(self):
        checked = check_agent_eval_fixtures(EVAL_DIR, FIXTURE_DIR)
        self.assertGreaterEqual(len(checked), 4)

    def test_agent_evaluation_product_fixtures_are_synced(self):
        for name in ("product_B0D8W1YVBX_agent_eval.json", "products_compare_agent_eval.json"):
            with self.subTest(fixture=name):
                test_fixture = Path("tests/fixtures") / name
                package_fixture = Path("keepa_cli/fixtures") / name
                self.assertTrue(test_fixture.is_file())
                self.assertTrue(package_fixture.is_file())
                self.assertEqual(test_fixture.read_text(encoding="utf-8"), package_fixture.read_text(encoding="utf-8"))

    def _assert_spec(self, payload: dict[str, Any], spec: dict[str, Any]) -> None:
        for assertion in spec["assertions"]:
            value = _resolve_path(payload, assertion["path"])
            if "equals" in assertion:
                self.assertEqual(value, assertion["equals"], assertion["path"])
            if "min" in assertion:
                self.assertGreaterEqual(value, assertion["min"], assertion["path"])
            if "contains" in assertion:
                self.assertIn(assertion["contains"], value, assertion["path"])
            if "length" in assertion:
                self.assertEqual(len(value), assertion["length"], assertion["path"])
            if "length_min" in assertion:
                self.assertGreaterEqual(len(value), assertion["length_min"], assertion["path"])
            if "contains_any" in assertion:
                self.assertTrue(set(assertion["contains_any"]).intersection(value), assertion["path"])


if __name__ == "__main__":
    unittest.main()
