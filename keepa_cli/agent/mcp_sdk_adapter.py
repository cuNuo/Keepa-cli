"""
keepa_cli/agent/mcp_sdk_adapter.py
文件说明：官方 Python MCP SDK adapter 的隔离 spike。
主要职责：提供可审计的 adapter 边界和 fixture 等价对比，不替换生产 --mcp stdio 入口。
依赖边界：默认不依赖 mcp 包；可选 SDK 只作为后续 FastMCP/streamable HTTP spike 的探针。
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from keepa_cli.agent.mcp import handle_mcp_message
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import get_tool_definition, tool_params_to_command_params


SDK_PACKAGE = "mcp"
ADAPTER_NAME = "keepa_mcp_sdk_spike"
PRODUCTION_ENTRYPOINT = "python -m keepa_cli --mcp"
SUPPORTED_SPIKE_METHODS = (
    "initialize",
    "tools/list",
    "tools/call",
    "resources/list",
    "resources/templates/list",
    "resources/read",
    "prompts/list",
    "prompts/get",
    "ping",
)


def sdk_dependency_available() -> bool:
    return importlib.util.find_spec(SDK_PACKAGE) is not None


def adapter_status() -> dict[str, Any]:
    return {
        "adapter": ADAPTER_NAME,
        "sdk_package": SDK_PACKAGE,
        "sdk_available": sdk_dependency_available(),
        "server_info_name": "keepa_mcp",
        "production_entrypoint": PRODUCTION_ENTRYPOINT,
        "production_entrypoint_replaced": False,
        "boundary": "protocol_adapter_only",
        "business_core": "AgentSession -> run_command",
        "supported_fixture_methods": list(SUPPORTED_SPIKE_METHODS),
        "streamable_http_rule": "streamable HTTP 只替换协议 adapter，继续复用 AgentSession/service/session cache。",
    }


def handle_sdk_adapter_message(
    raw_message: str,
    *,
    env: Mapping[str, str] | None = None,
    session: AgentSession | None = None,
) -> dict[str, Any] | None:
    """SDK adapter spike 的协议入口。

    当前 spike 以现有 stdio JSON-RPC handler 作为兼容性 oracle，确保后续接入官方 SDK
    或 streamable HTTP adapter 时，必须先与生产 `--mcp` 输出等价。
    """

    return handle_mcp_message(raw_message, env=env, session=session)


def _execute_local_tool(session: AgentSession, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    tool = get_tool_definition(tool_name)
    if tool is None:
        raise ValueError(f"unknown MCP tool: {tool_name}")
    command_params = tool_params_to_command_params(tool, dict(arguments))
    return session.execute(tool.command, command_params, tool=tool.name)


def create_fastmcp_readonly_spike(*, env: Mapping[str, str] | None = None) -> Any:
    """创建官方 Python SDK FastMCP 只读 spike。

    该函数只证明 SDK adapter 可以复用 `AgentSession -> run_command`，不承诺与生产
    `keepa.*` tool 名完全一致；真正替换前必须通过 `compare_fixture_outputs`。
    """

    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError("官方 Python MCP SDK 未安装；使用 keepa-cli[mcp-sdk] 后再运行该 spike。") from exc

    mcp = FastMCP("keepa_mcp", json_response=True)
    session = AgentSession(env=env)

    @mcp.tool()
    def keepa_context_policy() -> dict[str, Any]:
        """读取 Keepa-cli Agent/MCP 上下文策略。"""

        return _execute_local_tool(session, "keepa.context_policy", {})

    @mcp.tool()
    def keepa_docs_index() -> dict[str, Any]:
        """读取本地 Agent 文档与 MCP resource 索引。"""

        return _execute_local_tool(session, "keepa.docs_index", {})

    @mcp.tool()
    def keepa_docs_read(uri: str = "", page: str = "") -> dict[str, Any]:
        """读取本地 MCP resource URI 或 zread 页面。"""

        arguments = {key: value for key, value in {"uri": uri, "page": page}.items() if value}
        return _execute_local_tool(session, "keepa.docs_read", arguments)

    return mcp


def run_mcp_fixture_steps(
    steps: Sequence[Mapping[str, Any]],
    *,
    handler: Callable[..., dict[str, Any] | None],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    session = AgentSession(env=env)
    responses: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        response = handler(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": step.get("id") or f"adapter-fixture-{index}",
                    "method": step["method"],
                    "params": step.get("params") or {},
                },
            ),
            env=env,
            session=session,
        )
        if response is not None:
            responses.append(response)
    return {"ok": True, "kind": "mcp_session", "responses": responses, "budget_ledger": session.ledger.to_dict()}


def _first_difference(left: Any, right: Any, path: str = "$") -> str | None:
    if type(left) is not type(right):
        return f"{path}: type {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        if left_keys != right_keys:
            return f"{path}: keys {sorted(left_keys)} != {sorted(right_keys)}"
        for key in sorted(left_keys):
            diff = _first_difference(left[key], right[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} != {len(right)}"
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            diff = _first_difference(left_item, right_item, f"{path}.{index}")
            if diff:
                return diff
        return None
    if left != right:
        return f"{path}: {left!r} != {right!r}"
    return None


def compare_fixture_outputs(spec: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if spec.get("kind") != "mcp_session":
        raise ValueError("SDK adapter equivalence only supports mcp_session fixtures")
    steps = spec.get("steps") or []
    if not isinstance(steps, list):
        raise ValueError("mcp_session fixture steps must be a list")

    current = run_mcp_fixture_steps(steps, handler=handle_mcp_message, env=env)
    adapter = run_mcp_fixture_steps(steps, handler=handle_sdk_adapter_message, env=env)
    diff = _first_difference(current, adapter)
    return {
        "ok": diff is None,
        "fixture_id": spec.get("id"),
        "step_count": len(steps),
        "response_count": len(current["responses"]),
        "adapter_status": adapter_status(),
        "first_difference": diff,
        "current": current if diff else None,
        "adapter": adapter if diff else None,
    }
