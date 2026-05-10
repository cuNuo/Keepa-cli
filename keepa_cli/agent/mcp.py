"""
keepa_cli/agent/mcp.py
文件说明：实现最小 MCP JSON-RPC stdio server。
主要职责：处理 initialize、tools/list、tools/call，并复用 AgentSession 执行业务工具。
依赖边界：不直接访问 Keepa API，不解析 CLI 字符串。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from keepa_cli import __version__
from keepa_cli.agent.prompts import get_mcp_prompt, list_mcp_prompts, prompt_names
from keepa_cli.agent.resources import compact_payload_for_mcp, list_mcp_resource_templates, list_mcp_resources, read_mcp_resource
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import (
    DEFAULT_TOOLSET,
    get_tool_definition,
    list_mcp_tools,
    resolve_toolset_groups,
    tool_params_to_command_params,
    toolset_names,
    validate_tool_arguments,
)


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-06-18"


def _jsonrpc_result(message_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "result": dict(result)}


def _jsonrpc_error(message_id: Any, code: int, message: str, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = dict(data)
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "error": error}


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


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
    return {
        "structuredContent": payload,
        "content": [{"type": "text", "text": _json_text(content_payload)}],
        "isError": not bool(payload.get("ok")),
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {"name": "keepa", "version": __version__},
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


def handle_mcp_message(
    raw_message: str,
    *,
    env: Mapping[str, str] | None = None,
    session: AgentSession | None = None,
) -> dict[str, Any] | None:
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        return _jsonrpc_error(None, -32700, "Parse error", {"message": str(exc)})

    if not isinstance(message, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request", {"message": "JSON-RPC request must be an object"})

    message_id = message.get("id")
    method = str(message.get("method", ""))
    params = message.get("params") or {}
    if params is not None and not isinstance(params, dict):
        return _jsonrpc_error(message_id, -32602, "Invalid params", {"message": "params must be an object"})

    if method == "initialize":
        return _jsonrpc_result(message_id, _initialize_result())
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        groups = params.get("groups") if isinstance(params, dict) else None
        toolset = params.get("toolset") if isinstance(params, dict) else None
        toolsets = params.get("toolsets") if isinstance(params, dict) else None
        allow_tools = _tool_name_filter(params.get("allow_tools") if isinstance(params, dict) else None)
        exclude_tools = _tool_name_filter(params.get("exclude_tools") if isinstance(params, dict) else None)
        group_filter = set(groups) if isinstance(groups, list) else None
        use_all_toolsets = toolset == "all" or (isinstance(toolsets, list) and "all" in toolsets)
        if group_filter is None:
            toolset_filter = toolsets if toolsets is not None else toolset
            try:
                group_filter = resolve_toolset_groups(toolset_filter)
            except ValueError as exc:
                return _jsonrpc_error(
                    message_id,
                    -32602,
                    "Invalid toolset",
                    {"message": str(exc), "available_toolsets": toolset_names()},
                )
        return _jsonrpc_result(
            message_id,
            {
                "tools": list_mcp_tools(
                    groups=group_filter,
                    toolsets="all" if use_all_toolsets else None,
                    allow_tools=allow_tools,
                    exclude_tools=exclude_tools,
                ),
                "toolset": toolset or (toolsets if toolsets is not None else DEFAULT_TOOLSET),
                "available_toolsets": toolset_names(),
                "filters": {
                    "allow_tools": allow_tools,
                    "exclude_tools": exclude_tools,
                },
            },
        )
    if method == "tools/call":
        return _handle_tools_call(message_id, params, env=env, session=session)
    if method == "resources/list":
        return _jsonrpc_result(message_id, {"resources": list_mcp_resources()})
    if method == "resources/templates/list":
        return _jsonrpc_result(message_id, {"resourceTemplates": list_mcp_resource_templates()})
    if method == "resources/read":
        uri = str(params.get("uri", ""))
        try:
            active_session = session or AgentSession(env=env)
            content = read_mcp_resource(uri, session_cache=active_session.cache)
        except (OSError, ValueError) as exc:
            return _jsonrpc_error(message_id, -32602, "Unknown resource", {"uri": uri, "message": str(exc)})
        return _jsonrpc_result(message_id, {"contents": [content]})
    if method == "prompts/list":
        return _jsonrpc_result(message_id, {"prompts": list_mcp_prompts()})
    if method == "prompts/get":
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _jsonrpc_error(message_id, -32602, "Invalid prompt arguments", {"prompt": name})
        try:
            prompt = get_mcp_prompt(name, arguments)
        except ValueError as exc:
            return _jsonrpc_error(message_id, -32602, "Unknown prompt", {"prompt": name, "message": str(exc), "available_prompts": prompt_names()})
        return _jsonrpc_result(message_id, prompt)

    return _jsonrpc_error(message_id, -32601, "Method not found", {"method": method})


def _handle_tools_call(
    message_id: Any,
    params: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None,
    session: AgentSession | None,
) -> dict[str, Any]:
    name = str(params.get("name", ""))
    tool = get_tool_definition(name)
    if tool is None:
        return _jsonrpc_error(message_id, -32602, "Unknown tool", {"tool": name})

    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _jsonrpc_error(message_id, -32602, "Invalid tool arguments", {"tool": name})
    validation_errors = validate_tool_arguments(tool, arguments)
    if validation_errors:
        return _jsonrpc_error(message_id, -32602, "Invalid tool arguments", {"tool": name, "errors": validation_errors})

    command_params = tool_params_to_command_params(tool, arguments)
    active_session = session or AgentSession(env=env)
    payload = active_session.execute(tool.command, command_params, tool=tool.name)
    return _jsonrpc_result(message_id, _tool_result(payload))


def iter_mcp_output(input_text: str, *, env: Mapping[str, str] | None = None) -> list[str]:
    lines: list[str] = []
    session = AgentSession(env=env)
    for raw_line in input_text.splitlines():
        if not raw_line.strip():
            continue
        response = handle_mcp_message(raw_line, env=env, session=session)
        if response is not None:
            lines.append(json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str))
    return lines
