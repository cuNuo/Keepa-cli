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
        specs = sorted(EVAL_DIR.glob("*.json"))
        self.assertGreaterEqual(len(specs), 4)
        for path in specs:
            with self.subTest(spec=path.name):
                spec = json.loads(path.read_text(encoding="utf-8"))
                payload = run_command(spec["command"], spec.get("params") or {}, fixture_dir=FIXTURE_DIR, env={})
                self._assert_spec(payload, spec)

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


if __name__ == "__main__":
    unittest.main()
