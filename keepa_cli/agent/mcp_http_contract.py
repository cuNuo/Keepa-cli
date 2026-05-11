"""
keepa_cli/agent/mcp_http_contract.py
文件说明：Streamable HTTP adapter 前置协议合约。
主要职责：在真正实现 HTTP transport 前固化 Origin、session id 与错误映射 fixture 的可验证规则。
依赖边界：不启动 HTTP server；只描述协议边界，业务仍由 AgentSession/service/session 层承担。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from keepa_cli.agent.mcp import MCP_PROTOCOL_VERSION


MCP_SESSION_HEADER = "MCP-Session-Id"
MCP_PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
MCP_ENDPOINT_PATH = "/mcp"
SESSION_ID_PATTERN = r"^[\x21-\x7e]{16,256}$"
VISIBLE_ASCII_SESSION_ID = re.compile(SESSION_ID_PATTERN)

ERROR_HTTP_STATUS: dict[str, int] = {
    "origin_rejected": 403,
    "missing_session_id": 400,
    "expired_session_id": 404,
    "invalid_protocol_version": 400,
    "parse_error": 400,
    "invalid_request": 400,
    "notification_accepted": 202,
    "application_jsonrpc_error": 200,
    "delete_not_allowed": 405,
}


def is_visible_ascii_session_id(value: str) -> bool:
    return bool(VISIBLE_ASCII_SESSION_ID.fullmatch(value))


def is_origin_allowed(origin: str | None, allowed_origins: Sequence[str]) -> bool:
    if origin in (None, ""):
        return True
    return origin in set(allowed_origins)


def expected_http_status_for_case(case: Mapping[str, Any]) -> int:
    category = str(case.get("category") or "")
    if category == "origin":
        return 200 if is_origin_allowed(case.get("origin"), case.get("allowed_origins") or []) else ERROR_HTTP_STATUS["origin_rejected"]
    if category == "session":
        state = str(case.get("session_state") or "")
        if state == "missing":
            return ERROR_HTTP_STATUS["missing_session_id"]
        if state == "expired":
            return ERROR_HTTP_STATUS["expired_session_id"]
        if state == "delete_not_allowed":
            return ERROR_HTTP_STATUS["delete_not_allowed"]
        return 200
    if category == "error_mapping":
        error_kind = str(case.get("error_kind") or "")
        if error_kind in ERROR_HTTP_STATUS:
            return ERROR_HTTP_STATUS[error_kind]
    raise ValueError(f"unsupported Streamable HTTP contract case: {case.get('id') or category}")


def evaluate_streamable_http_contract(spec: Mapping[str, Any]) -> dict[str, Any]:
    cases = spec.get("cases") or []
    if not isinstance(cases, list):
        raise ValueError("Streamable HTTP contract fixture requires a cases list")
    results: list[dict[str, Any]] = []
    categories: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("Streamable HTTP contract cases must be objects")
        category = str(case.get("category") or "")
        categories.add(category)
        expected = case.get("expected") or {}
        status = expected_http_status_for_case(case)
        result: dict[str, Any] = {
            "id": case.get("id"),
            "category": category,
            "expected_status": int(expected.get("http_status", status)),
            "contract_status": status,
            "ok": int(expected.get("http_status", status)) == status,
        }
        if category == "origin":
            result["origin_allowed"] = is_origin_allowed(case.get("origin"), case.get("allowed_origins") or [])
        if category == "session":
            session_id = str(case.get("session_id") or "")
            result["session_id_visible_ascii"] = bool(session_id and is_visible_ascii_session_id(session_id))
            result["session_header"] = MCP_SESSION_HEADER
        if category == "error_mapping":
            result["error_kind"] = case.get("error_kind")
            result["jsonrpc_error_code"] = expected.get("jsonrpc_error_code")
        results.append(result)

    missing_categories = sorted({"origin", "session", "error_mapping"} - categories)
    return {
        "ok": not missing_categories and all(result["ok"] for result in results),
        "kind": "mcp_streamable_http_contract",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "endpoint_path": MCP_ENDPOINT_PATH,
        "session_header": MCP_SESSION_HEADER,
        "protocol_version_header": MCP_PROTOCOL_VERSION_HEADER,
        "session_id_pattern": SESSION_ID_PATTERN,
        "required_categories": ["origin", "session", "error_mapping"],
        "missing_categories": missing_categories,
        "case_count": len(results),
        "results": results,
    }
