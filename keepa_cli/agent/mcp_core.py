"""
keepa_cli/agent/mcp_core.py
文件说明：共享 MCP JSON-RPC 协议核心。
主要职责：统一方法分发、分页 cursor、错误映射、资源/提示词读取和工具结果封装。
依赖边界：不负责 stdio、SDK 或 HTTP 传输生命周期；业务执行仍委托 AgentSession/service。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from keepa_cli import __version__
from keepa_cli.agent.prompts import get_mcp_prompt, list_mcp_prompts, prompt_names
from keepa_cli.agent.resources import compact_payload_for_mcp, list_mcp_resource_templates, list_mcp_resources, read_mcp_resource
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import (
    DEFAULT_TOOLSET,
    get_tool_definition,
    is_tool_active_for_profile,
    list_mcp_tools,
    profile_names,
    resolve_toolset_groups,
    tool_params_to_command_params,
    toolset_names,
    validate_tool_arguments,
)
from keepa_cli.agent.workflow_resolver import resolve_workflow_arguments
from keepa_cli.envelope import error_envelope


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-11-25"
DEFAULT_PAGED_LIST_LIMIT = 50
DEFAULT_ALL_TOOLSET_LIST_LIMIT = 8
MAX_PAGED_LIST_LIMIT = 100
CURSOR_SCHEMA_VERSION = "2026-05-12.1"
RAW_AGENT_START_TOOLS = (
    "context_policy",
    "docs_index",
    "workflow_plan",
    "agent_profile_generate",
    "products_get",
    "products_compare",
    "categories_search",
    "finder_query",
)


def _jsonrpc_result(message_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "result": dict(result)}


def _jsonrpc_error(message_id: Any, code: int, message: str, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = dict(data)
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "error": error}


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _resource_link_content_items(content_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest = content_payload.get("mcp_resource_manifest")
    if not isinstance(manifest, Mapping):
        return []
    items: list[dict[str, Any]] = []
    for resource in manifest.get("resources") or []:
        if not isinstance(resource, Mapping) or not resource.get("uri"):
            continue
        item: dict[str, Any] = {
            "type": "resource_link",
            "uri": str(resource["uri"]),
            "name": str(resource.get("name") or resource["uri"]),
        }
        if resource.get("mimeType"):
            item["mimeType"] = str(resource["mimeType"])
        if resource.get("size_bytes") is not None:
            item["size"] = resource["size_bytes"]
        description_parts = [str(resource.get("type") or "resource")]
        if resource.get("json_path"):
            description_parts.append(f"json_path={resource['json_path']}")
        item["description"] = "; ".join(description_parts)
        items.append(item)
    return items


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()[:16]


def _cursor_fingerprint(collection: str, params: Mapping[str, Any]) -> str:
    filter_params = {key: value for key, value in params.items() if key not in {"cursor", "limit"}}
    return _fingerprint({"collection": collection, "filters": filter_params})


def _encode_cursor(offset: int, *, collection: str, fingerprint: str) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "schema_version": CURSOR_SCHEMA_VERSION,
            "collection": collection,
            "offset": offset,
            "fingerprint": fingerprint,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: Any, *, collection: str, fingerprint: str) -> int:
    if cursor in (None, ""):
        return 0
    if not isinstance(cursor, str):
        raise ValueError("cursor must be a string")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("cursor is not a valid Keepa MCP pagination cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("cursor payload must be an object")
    if payload.get("schema_version") != CURSOR_SCHEMA_VERSION:
        raise ValueError("cursor schema_version does not match this server")
    if payload.get("collection") != collection:
        raise ValueError(f"cursor collection does not match {collection}")
    if payload.get("fingerprint") != fingerprint:
        raise ValueError("cursor filters do not match this request")
    offset = payload.get("offset") if isinstance(payload, dict) else None
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("cursor does not contain a valid offset")
    return offset


def _list_limit(params: Mapping[str, Any], *, default_limit: int | None = None) -> int | None:
    value = params.get("limit")
    if value in (None, ""):
        if params.get("cursor"):
            return DEFAULT_PAGED_LIST_LIMIT
        return default_limit
    if isinstance(value, bool):
        raise ValueError("limit must be an integer between 1 and 100")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if limit < 1 or limit > MAX_PAGED_LIST_LIMIT:
        raise ValueError("limit must be an integer between 1 and 100")
    return limit


def _paginated_result(
    items: Sequence[dict[str, Any]],
    *,
    result_key: str,
    params: Mapping[str, Any],
    collection: str,
    default_limit: int | None = None,
) -> dict[str, Any]:
    fingerprint = _cursor_fingerprint(collection, params)
    offset = _decode_cursor(params.get("cursor"), collection=collection, fingerprint=fingerprint)
    limit = _list_limit(params, default_limit=default_limit)
    page_limit = len(items) if limit is None else limit
    page = [dict(item) for item in items[offset : offset + page_limit]]
    next_offset = offset + len(page)
    result: dict[str, Any] = {
        result_key: page,
        "_meta": {
            "count": len(page),
            "total_count": len(items),
            "offset": offset,
            "limit": page_limit,
            "has_more": next_offset < len(items),
            "cursor_schema_version": CURSOR_SCHEMA_VERSION,
            "cursor_collection": collection,
            "cursor_fingerprint": fingerprint,
        },
    }
    if next_offset < len(items):
        result["nextCursor"] = _encode_cursor(next_offset, collection=collection, fingerprint=fingerprint)
    return result


def _priority_ordered_items(items: Sequence[dict[str, Any]], priority_names: Sequence[str], *, key: str) -> list[dict[str, Any]]:
    priority = {name: index for index, name in enumerate(priority_names)}
    return sorted(
        items,
        key=lambda item: (
            priority.get(str(item.get(key) or ""), len(priority)),
            str(item.get(key) or ""),
        ),
    )


def _tool_name_filter(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        names = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        names = [str(item).strip() for item in value]
    else:
        names = []
    return [name for name in names if name]


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    content_payload = compact_payload_for_mcp(payload)
    content = [{"type": "text", "text": _json_text(content_payload)}]
    content.extend(_resource_link_content_items(content_payload))
    return {
        "structuredContent": payload,
        "content": content,
        "isError": not bool(payload.get("ok")),
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {"name": "keepa_mcp", "title": "Keepa CLI MCP", "version": __version__},
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False, "templatesChanged": False},
            "prompts": {"listChanged": False},
        },
        "instructions": (
            "Use Keepa MCP tools with structured params. Prefer fixture or dry_run before live calls. "
            "High-cost requests return confirmation_required unless yes=true is supplied."
        ),
    }


@dataclass(frozen=True)
class MCPProtocolCore:
    """无状态 MCP 协议核心；各 transport 负责 session 生命周期和 I/O。"""

    def jsonrpc_result(self, message_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
        return _jsonrpc_result(message_id, result)

    def jsonrpc_error(self, message_id: Any, code: int, message: str, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return _jsonrpc_error(message_id, code, message, data)

    def tool_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _tool_result(payload)

    def tool_error_result(self, *, tool: Any, kind: str, message: str, details: Mapping[str, Any], session: AgentSession) -> dict[str, Any]:
        payload = error_envelope(command=tool.command, kind=kind, message=message, details=dict(details))
        payload["cache_key"] = ""
        payload["cache_hit"] = False
        payload["budget_ledger"] = session.ledger.to_dict()
        return self.tool_result(payload)

    def paginated_result(
        self,
        items: Sequence[dict[str, Any]],
        *,
        result_key: str,
        params: Mapping[str, Any],
        collection: str,
        default_limit: int | None = None,
    ) -> dict[str, Any]:
        return _paginated_result(items, result_key=result_key, params=params, collection=collection, default_limit=default_limit)

    def handle_message(
        self,
        raw_message: str,
        *,
        env: Mapping[str, str] | None = None,
        session: AgentSession | None = None,
    ) -> dict[str, Any] | None:
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            return self.jsonrpc_error(None, -32700, "Parse error", {"message": str(exc)})

        if not isinstance(message, dict):
            return self.jsonrpc_error(None, -32600, "Invalid Request", {"message": "JSON-RPC request must be an object"})
        return self.handle_request(message, env=env, session=session)

    def handle_request(
        self,
        message: Mapping[str, Any],
        *,
        env: Mapping[str, str] | None = None,
        session: AgentSession | None = None,
    ) -> dict[str, Any] | None:
        message_id = message.get("id")
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        if params is not None and not isinstance(params, dict):
            return self.jsonrpc_error(message_id, -32602, "Invalid params", {"message": "params must be an object"})

        if method == "initialize":
            return self.jsonrpc_result(message_id, _initialize_result())
        if method == "ping":
            return self.jsonrpc_result(message_id, {})
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self.handle_tools_list(message_id, params)
        if method == "tools/call":
            return self.handle_tools_call(message_id, params, env=env, session=session)
        if method == "resources/list":
            return self.handle_resources_list(message_id, params)
        if method == "resources/templates/list":
            return self.handle_resource_templates_list(message_id, params)
        if method == "resources/read":
            return self.handle_resources_read(message_id, params, env=env, session=session)
        if method == "prompts/list":
            return self.handle_prompts_list(message_id, params)
        if method == "prompts/get":
            return self.handle_prompts_get(message_id, params)

        return self.jsonrpc_error(message_id, -32601, "Method not found", {"method": method})

    def handle_tools_list(self, message_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        groups = params.get("groups")
        toolset = params.get("toolset")
        toolsets = params.get("toolsets")
        allow_tools = _tool_name_filter(params.get("allow_tools"))
        exclude_tools = _tool_name_filter(params.get("exclude_tools"))
        profile = str(params.get("profile") or "").strip()
        group_filter = set(groups) if isinstance(groups, list) else None
        use_all_toolsets = toolset == "all" or (isinstance(toolsets, list) and "all" in toolsets)
        if group_filter is None:
            toolset_filter = toolsets if toolsets is not None else toolset
            try:
                group_filter = resolve_toolset_groups(toolset_filter)
            except ValueError as exc:
                return self.jsonrpc_error(
                    message_id,
                    -32602,
                    "Invalid toolset",
                    {"message": str(exc), "available_toolsets": toolset_names()},
                )
        try:
            tools = list_mcp_tools(
                groups=group_filter,
                toolsets="all" if use_all_toolsets else None,
                allow_tools=allow_tools,
                exclude_tools=exclude_tools,
                profile=profile or None,
            )
        except ValueError as exc:
            return self.jsonrpc_error(message_id, -32602, "Invalid profile", {"message": str(exc), "available_profiles": profile_names()})
        if use_all_toolsets:
            tools = _priority_ordered_items(tools, RAW_AGENT_START_TOOLS, key="name")
        try:
            result = self.paginated_result(
                tools,
                result_key="tools",
                params=params,
                collection="tools",
                default_limit=DEFAULT_ALL_TOOLSET_LIST_LIMIT if use_all_toolsets else None,
            )
        except ValueError as exc:
            return self.jsonrpc_error(message_id, -32602, "Invalid pagination params", {"message": str(exc)})
        result.update(
            {
                "toolset": toolset or (toolsets if toolsets is not None else DEFAULT_TOOLSET),
                "available_toolsets": toolset_names(),
                "available_profiles": profile_names(),
                "profile": profile or None,
                "filters": {
                    "allow_tools": allow_tools,
                    "exclude_tools": exclude_tools,
                },
            },
        )
        return self.jsonrpc_result(message_id, result)

    def handle_tools_call(
        self,
        message_id: Any,
        params: Mapping[str, Any],
        *,
        env: Mapping[str, str] | None,
        session: AgentSession | None,
    ) -> dict[str, Any]:
        name = str(params.get("name", ""))
        tool = get_tool_definition(name)
        if tool is None:
            return self.jsonrpc_error(message_id, -32602, "Unknown tool", {"tool": name})

        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self.jsonrpc_error(message_id, -32602, "Invalid tool arguments", {"tool": name})
        active_session = session or AgentSession(env=env)
        workflow_resolution = None
        if tool.workflow_runtime:
            arguments, workflow_resolution = resolve_workflow_arguments(tool.name, arguments, session_cache=active_session.cache)
        validation_errors = validate_tool_arguments(tool, arguments)
        missing_inputs = workflow_resolution.get("missing_inputs") if isinstance(workflow_resolution, Mapping) else None
        if missing_inputs:
            return self.jsonrpc_result(
                message_id,
                self.tool_error_result(
                    tool=tool,
                    kind="missing_inputs",
                    message=f"tool {tool.name} is missing workflow inputs",
                    details={
                        "tool": tool.name,
                        "missing_inputs": missing_inputs,
                        "workflow_resolution": workflow_resolution,
                    },
                    session=active_session,
                ),
            )
        if validation_errors:
            return self.jsonrpc_result(
                message_id,
                self.tool_error_result(
                    tool=tool,
                    kind="invalid_arguments",
                    message=f"tool {tool.name} arguments did not pass validation",
                    details={
                        "tool": name,
                        "errors": validation_errors,
                        "next_action": "Call tools/list for this tool and retry with arguments that match inputSchema.",
                    },
                    session=active_session,
                ),
            )

        profile = str(arguments.get("profile") or "").strip()
        if profile and not is_tool_active_for_profile(tool.name, profile):
            return self.jsonrpc_result(
                message_id,
                self.tool_error_result(
                    tool=tool,
                    kind="inactive_tool",
                    message=f"tool {tool.name} is inactive for profile {profile}",
                    details={"tool": tool.name, "profile": profile, "available_profiles": profile_names()},
                    session=active_session,
                ),
            )

        command_params = tool_params_to_command_params(tool, arguments)
        payload = active_session.execute(tool.command, command_params, tool=tool.name)
        if isinstance(workflow_resolution, Mapping) and workflow_resolution.get("resolved"):
            data = payload.get("data")
            if isinstance(data, dict):
                data["workflow_resolution"] = workflow_resolution
        return self.jsonrpc_result(message_id, self.tool_result(payload))

    def handle_resources_list(self, message_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = self.paginated_result(list_mcp_resources(), result_key="resources", params=params, collection="resources")
        except ValueError as exc:
            return self.jsonrpc_error(message_id, -32602, "Invalid pagination params", {"message": str(exc)})
        return self.jsonrpc_result(message_id, result)

    def handle_resource_templates_list(self, message_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = self.paginated_result(
                list_mcp_resource_templates(),
                result_key="resourceTemplates",
                params=params,
                collection="resourceTemplates",
            )
        except ValueError as exc:
            return self.jsonrpc_error(message_id, -32602, "Invalid pagination params", {"message": str(exc)})
        return self.jsonrpc_result(message_id, result)

    def handle_resources_read(
        self,
        message_id: Any,
        params: Mapping[str, Any],
        *,
        env: Mapping[str, str] | None,
        session: AgentSession | None,
    ) -> dict[str, Any]:
        uri = str(params.get("uri", ""))
        try:
            active_session = session or AgentSession(env=env)
            content = read_mcp_resource(uri, session_cache=active_session.cache)
        except (OSError, ValueError) as exc:
            return self.jsonrpc_error(message_id, -32602, "Unknown resource", {"uri": uri, "message": str(exc)})
        return self.jsonrpc_result(message_id, {"contents": [content]})

    def handle_prompts_list(self, message_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = self.paginated_result(list_mcp_prompts(), result_key="prompts", params=params, collection="prompts")
        except ValueError as exc:
            return self.jsonrpc_error(message_id, -32602, "Invalid pagination params", {"message": str(exc)})
        return self.jsonrpc_result(message_id, result)

    def handle_prompts_get(self, message_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self.jsonrpc_error(message_id, -32602, "Invalid prompt arguments", {"prompt": name})
        try:
            prompt = get_mcp_prompt(name, arguments)
        except ValueError as exc:
            return self.jsonrpc_error(message_id, -32602, "Unknown prompt", {"prompt": name, "message": str(exc), "available_prompts": prompt_names()})
        return self.jsonrpc_result(message_id, prompt)


DEFAULT_MCP_PROTOCOL_CORE = MCPProtocolCore()
