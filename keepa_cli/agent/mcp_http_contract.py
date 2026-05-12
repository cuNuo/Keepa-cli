"""
keepa_cli/agent/mcp_http_contract.py
文件说明：Streamable HTTP adapter 协议核心。
主要职责：固化并执行 Origin、session id、timeout 与 JSON-RPC/HTTP 错误映射规则。
依赖边界：不直接启动 HTTP server；JSON-RPC 业务委托共享 MCPProtocolCore。
"""

from __future__ import annotations

import json
import queue
import re
import secrets
import threading
import time
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from keepa_cli.agent.mcp_core import DEFAULT_MCP_PROTOCOL_CORE, JSONRPC_VERSION, MCP_PROTOCOL_VERSION
from keepa_cli.agent.session import AgentSession


MCP_SESSION_HEADER = "MCP-Session-Id"
MCP_SESSION_HEADER_ALIASES = ("Mcp-Session-Id", MCP_SESSION_HEADER)
MCP_PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
MCP_REQUEST_TIMEOUT_HEADER = "Keepa-MCP-Timeout-Ms"
HTTP_ACCEPT_HEADER = "Accept"
HTTP_CONTENT_TYPE_HEADER = "Content-Type"
MCP_ENDPOINT_PATH = "/mcp"
SESSION_ID_PATTERN = r"^[\x21-\x7e]{16,256}$"
VISIBLE_ASCII_SESSION_ID = re.compile(SESSION_ID_PATTERN)
DEFAULT_REQUEST_TIMEOUT_MS = 30_000
MIN_REQUEST_TIMEOUT_MS = 1_000
MAX_REQUEST_TIMEOUT_MS = 300_000
DEFAULT_SESSION_IDLE_TTL_SECONDS = 3_600
DEFAULT_MAX_HTTP_SESSIONS = 128

ERROR_HTTP_STATUS: dict[str, int] = {
    "origin_rejected": 403,
    "missing_session_id": 400,
    "expired_session_id": 404,
    "invalid_protocol_version": 400,
    "invalid_timeout": 400,
    "request_timeout": 504,
    "parse_error": 400,
    "invalid_request": 400,
    "notification_accepted": 202,
    "application_jsonrpc_error": 200,
    "not_acceptable": 406,
    "unsupported_media_type": 415,
    "session_capacity_exceeded": 503,
    "method_not_allowed": 405,
    "sse_not_supported": 405,
}

ADAPTER_JSONRPC_ERRORS: dict[str, tuple[int, str]] = {
    "origin_rejected": (-32000, "Origin rejected"),
    "missing_session_id": (-32001, "Missing MCP session id"),
    "expired_session_id": (-32002, "Expired MCP session id"),
    "invalid_protocol_version": (-32004, "Invalid MCP protocol version"),
    "invalid_timeout": (-32602, "Invalid request timeout"),
    "request_timeout": (-32003, "Request timeout"),
    "method_not_allowed": (-32005, "Method not allowed"),
    "sse_not_supported": (-32006, "SSE stream is not supported"),
    "not_acceptable": (-32007, "Not acceptable"),
    "unsupported_media_type": (-32008, "Unsupported media type"),
    "session_capacity_exceeded": (-32009, "MCP HTTP session capacity exceeded"),
}

_TIMEOUT = object()


def handle_mcp_message(raw_message: str, *, env: Mapping[str, str] | None = None, session: AgentSession | None = None) -> dict[str, Any] | None:
    """HTTP adapter 本地兼容钩子；默认直接委托共享 MCPProtocolCore。"""

    return DEFAULT_MCP_PROTOCOL_CORE.handle_message(raw_message, env=env, session=session)


def is_visible_ascii_session_id(value: str) -> bool:
    return bool(VISIBLE_ASCII_SESSION_ID.fullmatch(value))


def is_origin_allowed(origin: str | None, allowed_origins: Sequence[str]) -> bool:
    if origin in (None, ""):
        return True
    return origin in set(allowed_origins)


def normalize_request_timeout_ms(value: Any | None) -> int:
    if value in (None, ""):
        return DEFAULT_REQUEST_TIMEOUT_MS
    if isinstance(value, bool):
        raise ValueError("request timeout must be an integer millisecond value")
    try:
        timeout_ms = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("request timeout must be an integer millisecond value") from exc
    if timeout_ms < MIN_REQUEST_TIMEOUT_MS or timeout_ms > MAX_REQUEST_TIMEOUT_MS:
        raise ValueError(f"request timeout must be between {MIN_REQUEST_TIMEOUT_MS} and {MAX_REQUEST_TIMEOUT_MS} ms")
    return timeout_ms


def _header_value(headers: Mapping[str, Any], name: str) -> str | None:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def _media_types(value: str | None) -> set[str]:
    if value in (None, ""):
        return set()
    media_types: set[str] = set()
    for item in str(value).split(","):
        parts = item.split(";")
        media_type = parts[0].strip().lower()
        quality = 1.0
        for param in parts[1:]:
            name, _, raw_value = param.strip().partition("=")
            if name.lower() != "q":
                continue
            try:
                quality = float(raw_value)
            except ValueError:
                quality = 0.0
        if media_type and quality > 0:
            media_types.add(media_type)
    return media_types


def is_accept_compatible(value: str | None) -> bool:
    media_types = _media_types(value)
    if not media_types:
        return True
    return bool({"application/json", "application/*", "*/*"} & media_types)


def is_json_content_type(value: str | None) -> bool:
    media_types = _media_types(value)
    if not media_types:
        return True
    return "application/json" in media_types


def _jsonrpc_error_payload(message_id: Any, kind: str, *, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    code, message = ADAPTER_JSONRPC_ERRORS[kind]
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = dict(data)
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "error": error}


def _response(status: int, body: Any | None, *, headers: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "http_status": status,
        "headers": dict(headers or {}),
        "body": body,
        "content_type": "application/json" if body is not None else None,
    }


def _jsonrpc_method(body: Any) -> str:
    if isinstance(body, Mapping):
        return str(body.get("method") or "")
    return ""


def _is_jsonrpc_response(body: Any) -> bool:
    return isinstance(body, Mapping) and "method" not in body and ("result" in body or "error" in body)


@dataclass
class StreamableHttpAdapterContract:
    """Streamable HTTP 协议 adapter 核心，所有 JSON-RPC 业务委托共享 core。"""

    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:3000", "http://localhost:3000")
    env: Mapping[str, str] | None = None
    sessions: MutableMapping[str, AgentSession] = field(default_factory=dict)
    session_last_seen: MutableMapping[str, float] = field(default_factory=dict)
    expired_session_ids: set[str] = field(default_factory=set)
    session_idle_ttl_seconds: int = DEFAULT_SESSION_IDLE_TTL_SECONDS
    max_sessions: int = DEFAULT_MAX_HTTP_SESSIONS
    _session_counter: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def _new_session_id(self) -> str:
        self._session_counter += 1
        return f"keepa-session-{self._session_counter:08d}-{secrets.token_urlsafe(24)}"

    def register_session(self, session_id: str, *, expired: bool = False) -> None:
        with self._lock:
            if expired:
                self.expired_session_ids.add(session_id)
                return
            self.sessions[session_id] = AgentSession(env=self.env or {})
            self._touch_session(session_id)

    def _touch_session(self, session_id: str) -> None:
        with self._lock:
            self.session_last_seen[session_id] = time.monotonic()

    def _prune_idle_sessions(self) -> None:
        if self.session_idle_ttl_seconds <= 0:
            return
        cutoff = time.monotonic() - self.session_idle_ttl_seconds
        with self._lock:
            for session_id, last_seen in list(self.session_last_seen.items()):
                if last_seen >= cutoff:
                    continue
                self.sessions.pop(session_id, None)
                self.session_last_seen.pop(session_id, None)

    def _dispatch(self, raw_message: str, *, session: AgentSession, timeout_ms: int) -> dict[str, Any] | None | object:
        results: queue.Queue[dict[str, Any] | None | BaseException] = queue.Queue(maxsize=1)

        def target() -> None:
            try:
                results.put(handle_mcp_message(raw_message, env=self.env or {}, session=session))
            except BaseException as exc:  # pragma: no cover - defensive adapter boundary
                results.put(exc)

        worker = threading.Thread(target=target, name="keepa-mcp-http-request", daemon=True)
        worker.start()
        try:
            result = results.get(timeout=timeout_ms / 1000)
        except queue.Empty:
            return _TIMEOUT
        if isinstance(result, BaseException):
            raise result
        return result

    def handle(
        self,
        *,
        method: str = "POST",
        headers: Mapping[str, Any] | None = None,
        body: str | bytes | Mapping[str, Any] | None = None,
        timeout_state: str | None = None,
    ) -> dict[str, Any]:
        self._prune_idle_sessions()
        request_headers = dict(headers or {})
        origin = _header_value(request_headers, "Origin")
        if not is_origin_allowed(origin, self.allowed_origins):
            return _response(ERROR_HTTP_STATUS["origin_rejected"], _jsonrpc_error_payload(None, "origin_rejected"))

        requested_protocol = _header_value(request_headers, MCP_PROTOCOL_VERSION_HEADER)
        if requested_protocol and requested_protocol != MCP_PROTOCOL_VERSION:
            return _response(
                ERROR_HTTP_STATUS["invalid_protocol_version"],
                _jsonrpc_error_payload(None, "invalid_protocol_version", data={"expected": MCP_PROTOCOL_VERSION, "actual": requested_protocol}),
            )

        http_method = method.upper()
        if http_method == "GET":
            return _response(ERROR_HTTP_STATUS["sse_not_supported"], _jsonrpc_error_payload(None, "sse_not_supported"))
        if http_method == "DELETE":
            session_id = _header_value(request_headers, MCP_SESSION_HEADER)
            if not session_id:
                return _response(ERROR_HTTP_STATUS["missing_session_id"], _jsonrpc_error_payload(None, "missing_session_id"))
            with self._lock:
                if session_id in self.expired_session_ids or session_id not in self.sessions:
                    return _response(ERROR_HTTP_STATUS["expired_session_id"], _jsonrpc_error_payload(None, "expired_session_id"))
                del self.sessions[session_id]
                self.session_last_seen.pop(session_id, None)
            return _response(ERROR_HTTP_STATUS["notification_accepted"], None)
        if http_method != "POST":
            return _response(ERROR_HTTP_STATUS["method_not_allowed"], _jsonrpc_error_payload(None, "method_not_allowed"))

        if not is_accept_compatible(_header_value(request_headers, HTTP_ACCEPT_HEADER)):
            return _response(
                ERROR_HTTP_STATUS["not_acceptable"],
                _jsonrpc_error_payload(None, "not_acceptable", data={"expected": "application/json"}),
            )
        if not is_json_content_type(_header_value(request_headers, HTTP_CONTENT_TYPE_HEADER)):
            return _response(
                ERROR_HTTP_STATUS["unsupported_media_type"],
                _jsonrpc_error_payload(None, "unsupported_media_type", data={"expected": "application/json"}),
            )

        try:
            timeout_ms = normalize_request_timeout_ms(_header_value(request_headers, MCP_REQUEST_TIMEOUT_HEADER))
        except ValueError as exc:
            return _response(ERROR_HTTP_STATUS["invalid_timeout"], _jsonrpc_error_payload(None, "invalid_timeout", data={"message": str(exc)}))
        if timeout_state == "expired":
            return _response(ERROR_HTTP_STATUS["request_timeout"], _jsonrpc_error_payload(None, "request_timeout", data={"timeout_ms": timeout_ms}))

        raw_body = body
        if isinstance(raw_body, bytes):
            raw_message = raw_body.decode("utf-8", errors="replace")
        elif isinstance(raw_body, str):
            raw_message = raw_body
        elif raw_body is None:
            raw_message = "{}"
        else:
            raw_message = json.dumps(raw_body, ensure_ascii=False)

        try:
            parsed = json.loads(raw_message)
        except json.JSONDecodeError:
            payload = handle_mcp_message(raw_message, env={}, session=None)
            return _response(ERROR_HTTP_STATUS["parse_error"], payload)

        if not isinstance(parsed, Mapping):
            payload = handle_mcp_message(raw_message, env={}, session=None)
            return _response(ERROR_HTTP_STATUS["invalid_request"], payload)

        message_id = parsed.get("id")
        rpc_method = _jsonrpc_method(parsed)
        session_id = _header_value(request_headers, MCP_SESSION_HEADER)
        if rpc_method == "initialize":
            session_id = session_id or self._new_session_id()
            with self._lock:
                if self.max_sessions <= 0 or (session_id not in self.sessions and len(self.sessions) >= self.max_sessions):
                    return _response(
                        ERROR_HTTP_STATUS["session_capacity_exceeded"],
                        _jsonrpc_error_payload(message_id, "session_capacity_exceeded", data={"max_sessions": self.max_sessions}),
                    )
                session = AgentSession(env=self.env or {})
                self.sessions[session_id] = session
                self.session_last_seen[session_id] = time.monotonic()
            payload = self._dispatch(raw_message, session=session, timeout_ms=timeout_ms)
            if payload is _TIMEOUT:
                with self._lock:
                    self.sessions.pop(session_id, None)
                    self.session_last_seen.pop(session_id, None)
                return _response(ERROR_HTTP_STATUS["request_timeout"], _jsonrpc_error_payload(message_id, "request_timeout", data={"timeout_ms": timeout_ms}))
            return _response(200, payload, headers={MCP_SESSION_HEADER: session_id})

        if not session_id:
            return _response(ERROR_HTTP_STATUS["missing_session_id"], _jsonrpc_error_payload(message_id, "missing_session_id"))
        with self._lock:
            if session_id in self.expired_session_ids or session_id not in self.sessions:
                return _response(ERROR_HTTP_STATUS["expired_session_id"], _jsonrpc_error_payload(message_id, "expired_session_id"))
            session = self.sessions[session_id]

        if _is_jsonrpc_response(parsed):
            return _response(ERROR_HTTP_STATUS["notification_accepted"], None)
        self._touch_session(session_id)
        payload = self._dispatch(raw_message, session=session, timeout_ms=timeout_ms)
        if payload is _TIMEOUT:
            return _response(ERROR_HTTP_STATUS["request_timeout"], _jsonrpc_error_payload(message_id, "request_timeout", data={"timeout_ms": timeout_ms}))
        if rpc_method.startswith("notifications/") and payload is None:
            return _response(ERROR_HTTP_STATUS["notification_accepted"], None)
        status = ERROR_HTTP_STATUS["application_jsonrpc_error"] if isinstance(payload, Mapping) and payload.get("error") else 200
        return _response(status, payload)


def _case_body(case: Mapping[str, Any]) -> str:
    if "body" in case:
        value = case["body"]
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    error_kind = str(case.get("error_kind") or "")
    if error_kind == "parse_error":
        return '{"jsonrpc": "2.0", "id": 1, "method":'
    if error_kind == "invalid_request":
        return "[]"
    if error_kind == "application_jsonrpc_error":
        return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": "app-error", "method": "tools/call", "params": {"name": "unknown_tool", "arguments": {}}})
    method = str(case.get("jsonrpc_method") or "initialize")
    params: dict[str, Any] = {}
    if method == "tools/call":
        params = {"name": "context_policy", "arguments": {}}
    return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": case.get("id"), "method": method, "params": params})


def adapter_response_for_case(case: Mapping[str, Any]) -> dict[str, Any]:
    adapter = StreamableHttpAdapterContract(allowed_origins=tuple(case.get("allowed_origins") or ("http://127.0.0.1:3000", "http://localhost:3000")))
    session_id = str(case.get("session_id") or "active-visible-ascii-session")
    category = str(case.get("category") or "")
    if category in {"timeout", "error_mapping"} or str(case.get("session_state") or "") in {"active", "expired", "terminated"}:
        adapter.register_session(session_id, expired=str(case.get("session_state") or "") == "expired")
    headers: dict[str, str] = {}
    if case.get("origin") is not None:
        headers["Origin"] = str(case["origin"])
    if category in {"timeout", "error_mapping"} or case.get("session_id"):
        headers[MCP_SESSION_HEADER] = session_id
    if case.get("timeout_ms") is not None:
        headers[MCP_REQUEST_TIMEOUT_HEADER] = str(case["timeout_ms"])
    case_headers = case.get("headers") or {}
    if isinstance(case_headers, Mapping):
        headers.update({str(key): str(value) for key, value in case_headers.items()})
    return adapter.handle(
        method=str(case.get("method") or "POST"),
        headers=headers,
        body=_case_body(case),
        timeout_state=str(case.get("timeout_state") or "") or None,
    )


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
        if state == "terminated":
            return ERROR_HTTP_STATUS["notification_accepted"]
        return 200
    if category == "timeout":
        if str(case.get("timeout_state") or "") == "expired":
            return ERROR_HTTP_STATUS["request_timeout"]
        try:
            normalize_request_timeout_ms(case.get("timeout_ms"))
        except ValueError:
            return ERROR_HTTP_STATUS["invalid_timeout"]
        return 200
    if category == "headers":
        headers = case.get("headers") or {}
        accept = headers.get(HTTP_ACCEPT_HEADER) if isinstance(headers, Mapping) else None
        content_type = headers.get(HTTP_CONTENT_TYPE_HEADER) if isinstance(headers, Mapping) else None
        if not is_accept_compatible(str(accept) if accept is not None else None):
            return ERROR_HTTP_STATUS["not_acceptable"]
        if not is_json_content_type(str(content_type) if content_type is not None else None):
            return ERROR_HTTP_STATUS["unsupported_media_type"]
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
        adapter_response = adapter_response_for_case(case)
        result["adapter_status"] = adapter_response["http_status"]
        result["adapter_ok"] = int(expected.get("http_status", status)) == adapter_response["http_status"]
        result["ok"] = bool(result["ok"] and result["adapter_ok"])
        if isinstance(adapter_response.get("body"), Mapping):
            error = adapter_response["body"].get("error")
            if isinstance(error, Mapping):
                result["adapter_jsonrpc_error_code"] = error.get("code")
        if category == "origin":
            result["origin_allowed"] = is_origin_allowed(case.get("origin"), case.get("allowed_origins") or [])
        if category == "session":
            session_id = str(case.get("session_id") or "")
            result["session_id_visible_ascii"] = bool(session_id and is_visible_ascii_session_id(session_id))
            result["session_header"] = MCP_SESSION_HEADER
            result["session_header_aliases"] = list(MCP_SESSION_HEADER_ALIASES)
        if category == "timeout":
            try:
                result["normalized_timeout_ms"] = normalize_request_timeout_ms(case.get("timeout_ms"))
                result["timeout_valid"] = True
            except ValueError as exc:
                result["normalized_timeout_ms"] = None
                result["timeout_valid"] = False
                result["timeout_error"] = str(exc)
            result["timeout_header"] = MCP_REQUEST_TIMEOUT_HEADER
        if category == "headers":
            headers = case.get("headers") or {}
            result["accept_compatible"] = is_accept_compatible(str(headers.get(HTTP_ACCEPT_HEADER)) if isinstance(headers, Mapping) and headers.get(HTTP_ACCEPT_HEADER) is not None else None)
            result["json_content_type"] = is_json_content_type(str(headers.get(HTTP_CONTENT_TYPE_HEADER)) if isinstance(headers, Mapping) and headers.get(HTTP_CONTENT_TYPE_HEADER) is not None else None)
        if category == "error_mapping":
            result["error_kind"] = case.get("error_kind")
            result["jsonrpc_error_code"] = expected.get("jsonrpc_error_code")
        results.append(result)

    required_categories = ["origin", "session", "timeout", "headers", "error_mapping"]
    missing_categories = sorted(set(required_categories) - categories)
    return {
        "ok": not missing_categories and all(result["ok"] for result in results),
        "kind": "mcp_streamable_http_contract",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "endpoint_path": MCP_ENDPOINT_PATH,
        "session_header": MCP_SESSION_HEADER,
        "session_header_aliases": list(MCP_SESSION_HEADER_ALIASES),
        "protocol_version_header": MCP_PROTOCOL_VERSION_HEADER,
        "request_timeout_header": MCP_REQUEST_TIMEOUT_HEADER,
        "default_request_timeout_ms": DEFAULT_REQUEST_TIMEOUT_MS,
        "min_request_timeout_ms": MIN_REQUEST_TIMEOUT_MS,
        "max_request_timeout_ms": MAX_REQUEST_TIMEOUT_MS,
        "session_id_pattern": SESSION_ID_PATTERN,
        "required_categories": required_categories,
        "missing_categories": missing_categories,
        "case_count": len(results),
        "results": results,
    }
