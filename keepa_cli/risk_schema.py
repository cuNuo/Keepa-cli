"""
keepa_cli/risk_schema.py
文件说明：提供 Agent risk_taxonomy schema 的轻量校验辅助函数。
主要职责：让 MCP examples、Agent eval 与后续集成测试共用同一套风险枚举校验逻辑。
依赖边界：只读取仓库内 schema 文件，不访问网络或真实 Keepa API。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


RISK_SCHEMA_URI = "keepa://schema/risk-taxonomy"
DEFAULT_RISK_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "schema" / "risk-taxonomy.schema.json"


def load_risk_taxonomy_schema(path: str | Path | None = None) -> dict[str, Any]:
    """读取本地 risk taxonomy JSON schema。"""

    schema_path = Path(path) if path else DEFAULT_RISK_SCHEMA_PATH
    return json.loads(schema_path.read_text(encoding="utf-8"))


def risk_schema_summary(schema: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uri": RISK_SCHEMA_URI,
        "schema_version": schema.get("properties", {}).get("schema_version", {}).get("description", ""),
        "known_codes": schema.get("$defs", {}).get("risk_code", {}).get("enum", []),
    }


def validate_risk_taxonomy(payloads: Sequence[Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    known_codes, severities, required_item_fields = _risk_schema_enums(schema)
    errors: list[dict[str, Any]] = []
    checked = 0
    present_codes: set[str] = set()
    highest_seen: set[str] = set()
    for payload in payloads:
        for path, risk in iter_risk_taxonomies(payload):
            checked += 1
            codes = risk.get("codes") if isinstance(risk.get("codes"), list) else []
            for code in codes:
                present_codes.add(str(code))
                if code not in known_codes:
                    errors.append({"path": f"{path}.codes", "message": f"unknown risk code {code}"})
            highest = risk.get("highest_severity")
            if highest is not None:
                highest_seen.add(str(highest))
                if highest not in severities:
                    errors.append({"path": f"{path}.highest_severity", "message": f"unknown severity {highest}"})
            items = risk.get("items") if isinstance(risk.get("items"), list) else []
            for index, item in enumerate(items):
                if not isinstance(item, Mapping):
                    errors.append({"path": f"{path}.items[{index}]", "message": "risk item is not an object"})
                    continue
                missing = sorted(field for field in required_item_fields if not item.get(field))
                if missing:
                    errors.append({"path": f"{path}.items[{index}]", "message": f"missing required fields: {','.join(missing)}"})
                if item.get("code") not in known_codes:
                    errors.append({"path": f"{path}.items[{index}].code", "message": f"unknown risk code {item.get('code')}"})
                if item.get("severity") not in severities:
                    errors.append({"path": f"{path}.items[{index}].severity", "message": f"unknown severity {item.get('severity')}"})
    return {
        "ok": not errors and checked > 0,
        "checked_objects": checked,
        "present_codes": sorted(present_codes),
        "highest_severity_values": sorted(highest_seen),
        "errors": errors,
    }


def iter_risk_taxonomies(payload: Any) -> list[tuple[str, Mapping[str, Any]]]:
    found: list[tuple[str, Mapping[str, Any]]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            risk = value.get("risk_taxonomy")
            if isinstance(risk, Mapping):
                found.append((f"{path}.risk_taxonomy", risk))
            for key, child in value.items():
                if key != "risk_taxonomy":
                    visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload, "$")
    return found


def _risk_schema_enums(schema: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    defs = schema.get("$defs") if isinstance(schema.get("$defs"), Mapping) else {}
    code_def = defs.get("risk_code") if isinstance(defs.get("risk_code"), Mapping) else {}
    severity_def = defs.get("severity") if isinstance(defs.get("severity"), Mapping) else {}
    item_def = defs.get("risk_item") if isinstance(defs.get("risk_item"), Mapping) else {}
    required = {str(item) for item in item_def.get("required", [])} if isinstance(item_def.get("required"), list) else set()
    return set(code_def.get("enum") or []), set(severity_def.get("enum") or []), required
