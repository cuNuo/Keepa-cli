"""
keepa_cli/agent/mcp.py
文件说明：MCP stdio transport 兼容入口。
主要职责：逐行处理 stdio JSON-RPC，并把协议语义委托给共享 MCPProtocolCore。
依赖边界：不承载方法分发、分页、cursor 或工具结果封装逻辑。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from keepa_cli.agent.mcp_core import (
    CURSOR_SCHEMA_VERSION,
    DEFAULT_ALL_TOOLSET_LIST_LIMIT,
    DEFAULT_MCP_PROTOCOL_CORE,
    DEFAULT_PAGED_LIST_LIMIT,
    JSONRPC_VERSION,
    MAX_PAGED_LIST_LIMIT,
    MCP_PROTOCOL_VERSION,
    MCPProtocolCore,
    RAW_AGENT_START_TOOLS,
    _json_text,
    _jsonrpc_error,
    _jsonrpc_result,
    _paginated_result,
    _tool_result,
)
from keepa_cli.agent.session import AgentSession


def handle_mcp_message(
    raw_message: str,
    *,
    env: Mapping[str, str] | None = None,
    session: AgentSession | None = None,
    protocol_core: MCPProtocolCore = DEFAULT_MCP_PROTOCOL_CORE,
) -> dict[str, Any] | None:
    return protocol_core.handle_message(raw_message, env=env, session=session)


def iter_mcp_output(
    input_text: str,
    *,
    env: Mapping[str, str] | None = None,
    protocol_core: MCPProtocolCore = DEFAULT_MCP_PROTOCOL_CORE,
) -> list[str]:
    lines: list[str] = []
    session = AgentSession(env=env)
    for raw_line in input_text.splitlines():
        if not raw_line.strip():
            continue
        response = handle_mcp_message(raw_line, env=env, session=session, protocol_core=protocol_core)
        if response is not None:
            lines.append(json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str))
    return lines


def iter_mcp_stream(
    raw_lines: Any,
    *,
    env: Mapping[str, str] | None = None,
    protocol_core: MCPProtocolCore = DEFAULT_MCP_PROTOCOL_CORE,
) -> Any:
    """逐行处理 MCP JSON-RPC 输入，供真实 stdio client 动态串联前序结果。"""

    session = AgentSession(env=env)
    for raw_line in raw_lines:
        if not str(raw_line).strip():
            continue
        response = handle_mcp_message(str(raw_line), env=env, session=session, protocol_core=protocol_core)
        if response is not None:
            yield json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str)
