"""
keepa_cli/agent/mcp_sdk_adapter.py
文件说明：官方 Python MCP SDK adapter 的隔离实现。
主要职责：提供可运行的 low-level SDK server、adapter 边界和 fixture 等价对比，不替换生产 --mcp stdio 入口。
依赖边界：业务逻辑仍复用 AgentSession/run_command；mcp 包只存在于 SDK adapter 与测试 smoke。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import importlib.util
import importlib.metadata
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from keepa_cli import __version__
from keepa_cli.agent.mcp import handle_mcp_message
from keepa_cli.agent.prompts import get_mcp_prompt, list_mcp_prompts, prompt_names
from keepa_cli.agent.resources import list_mcp_resource_templates, list_mcp_resources, read_mcp_resource
from keepa_cli.agent.session import AgentSession
from keepa_cli.agent.tools import get_tool_definition, tool_params_to_command_params


SDK_PACKAGE = "mcp"
ADAPTER_NAME = "keepa_mcp_sdk_adapter"
PRODUCTION_ENTRYPOINT = "python -m keepa_cli --mcp"
SDK_STDIO_ENTRYPOINT = "python -m keepa_cli.agent.mcp_sdk_adapter --stdio"
SDK_DEFAULT_TOOL_PAGE_SIZE = 8
SDK_DEFAULT_RESOURCE_PAGE_SIZE = 6
SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE = 6
SDK_DEFAULT_PROMPT_PAGE_SIZE = 4
SDK_AGENT_START_TOOLS = (
    "context_policy",
    "docs_index",
    "workflow_plan",
    "agent_profile_generate",
    "products_get",
    "products_compare",
    "categories_search",
    "finder_query",
)
SDK_AGENT_START_RESOURCES = (
    "keepa://context/policy",
    "keepa://tools/index",
    "keepa://toolsets/research",
    "keepa://guides/agent-profile",
)
SDK_AGENT_START_RESOURCE_TEMPLATES = (
    "keepa://toolsets/{toolset}",
    "keepa://tools/{name}",
    "keepa://prompts/{name}",
    "keepa://workflow/{encoded_params}/policy",
    "keepa://research/{cache_key}",
    "keepa://cache-key/{command}/{encoded_params}",
)
SDK_AGENT_START_PROMPTS = (
    "product_research",
    "category_research",
    "deal_compare",
    "project_onboarding",
)
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


def sdk_dependency_version() -> str | None:
    try:
        return importlib.metadata.version(SDK_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def adapter_status() -> dict[str, Any]:
    return {
        "adapter": ADAPTER_NAME,
        "sdk_package": SDK_PACKAGE,
        "sdk_available": sdk_dependency_available(),
        "sdk_version": sdk_dependency_version(),
        "server_info_name": "keepa_mcp",
        "production_entrypoint": PRODUCTION_ENTRYPOINT,
        "sdk_stdio_entrypoint": SDK_STDIO_ENTRYPOINT,
        "production_entrypoint_replaced": False,
        "boundary": "protocol_adapter_only",
        "business_core": "AgentSession -> run_command",
        "supported_fixture_methods": list(SUPPORTED_SPIKE_METHODS),
        "sdk_default_tool_page_size": SDK_DEFAULT_TOOL_PAGE_SIZE,
        "sdk_default_resource_page_size": SDK_DEFAULT_RESOURCE_PAGE_SIZE,
        "sdk_default_resource_template_page_size": SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE,
        "sdk_default_prompt_page_size": SDK_DEFAULT_PROMPT_PAGE_SIZE,
        "sdk_agent_start_tools": list(SDK_AGENT_START_TOOLS),
        "sdk_agent_start_resources": list(SDK_AGENT_START_RESOURCES),
        "sdk_agent_start_resource_templates": list(SDK_AGENT_START_RESOURCE_TEMPLATES),
        "sdk_agent_start_prompts": list(SDK_AGENT_START_PROMPTS),
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


def _require_sdk() -> Any:
    try:
        import mcp.types as types
        from mcp.server.lowlevel import NotificationOptions, Server
        import mcp.server.stdio
    except ModuleNotFoundError as exc:
        raise RuntimeError("官方 Python MCP SDK 未安装；请先在项目 .venv 中安装 keepa-cli[mcp-sdk] 或 mcp>=1,<2。") from exc
    return types, NotificationOptions, Server, mcp.server.stdio


def _content_to_sdk(types: Any, content: Mapping[str, Any]) -> Any:
    content_type = content.get("type")
    if content_type == "text":
        return types.TextContent(type="text", text=str(content.get("text", "")))
    if content_type == "image":  # pragma: no cover - 当前 Keepa MCP 只返回 text/resource。
        return types.ImageContent(type="image", data=str(content.get("data", "")), mimeType=str(content.get("mimeType") or "image/png"))
    if content_type == "resource":  # pragma: no cover - 预留给后续 embedded resource。
        return types.EmbeddedResource(type="resource", resource=content["resource"])
    return types.TextContent(type="text", text=json.dumps(content, ensure_ascii=False, sort_keys=True))


def _tool_to_sdk(types: Any, payload: Mapping[str, Any]) -> Any:
    annotations = payload.get("annotations") or {}
    execution = payload.get("execution") or {}
    extra = {"x-keepa": payload["x-keepa"]} if "x-keepa" in payload else {}
    return types.Tool(
        name=str(payload["name"]),
        title=payload.get("title"),
        description=payload.get("description"),
        inputSchema=dict(payload.get("inputSchema") or {"type": "object", "properties": {}}),
        outputSchema=payload.get("outputSchema"),
        annotations=types.ToolAnnotations(**annotations) if annotations else None,
        execution=types.ToolExecution(**execution) if execution else None,
        **extra,
    )


def _resource_to_sdk(types: Any, payload: Mapping[str, Any]) -> Any:
    return types.Resource(
        uri=payload["uri"],
        name=str(payload["name"]),
        title=payload.get("title"),
        description=payload.get("description"),
        mimeType=payload.get("mimeType"),
    )


def _resource_template_to_sdk(types: Any, payload: Mapping[str, Any]) -> Any:
    return types.ResourceTemplate(
        uriTemplate=str(payload["uriTemplate"]),
        name=str(payload["name"]),
        title=payload.get("title"),
        description=payload.get("description"),
        mimeType=payload.get("mimeType"),
    )


def _prompt_to_sdk(types: Any, payload: Mapping[str, Any]) -> Any:
    arguments = [
        types.PromptArgument(
            name=str(argument["name"]),
            description=argument.get("description"),
            required=argument.get("required"),
        )
        for argument in payload.get("arguments") or []
        if isinstance(argument, Mapping) and "name" in argument
    ]
    return types.Prompt(
        name=str(payload["name"]),
        title=payload.get("title"),
        description=payload.get("description"),
        arguments=arguments or None,
    )


def _prompt_message_to_sdk(types: Any, payload: Mapping[str, Any]) -> Any:
    return types.PromptMessage(role=str(payload["role"]), content=_content_to_sdk(types, payload.get("content") or {"type": "text", "text": ""}))


def _tool_result_to_sdk(types: Any, result: Mapping[str, Any]) -> Any:
    content = [_content_to_sdk(types, item) for item in result.get("content") or [] if isinstance(item, Mapping)]
    return types.CallToolResult(
        content=content or [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, sort_keys=True))],
        structuredContent=result.get("structuredContent"),
        isError=bool(result.get("isError")),
        _meta=result.get("_meta"),
    )


def _current_mcp_result(
    method: str,
    params: Mapping[str, Any] | None,
    *,
    session: AgentSession,
    env: Mapping[str, str] | None,
) -> dict[str, Any]:
    response = handle_mcp_message(
        json.dumps({"jsonrpc": "2.0", "id": "sdk-adapter", "method": method, "params": dict(params or {})}),
        env=env,
        session=session,
    )
    if response is None:
        return {}
    if "error" in response:
        raise ValueError(json.dumps(response["error"], ensure_ascii=False, sort_keys=True))
    result = response.get("result")
    return dict(result or {}) if isinstance(result, Mapping) else {}


def _encode_sdk_cursor(offset: int, *, collection: str = "tools") -> str:
    raw = json.dumps({"sdk_offset": offset, "sdk_collection": collection}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_sdk_cursor(cursor: Any, *, collection: str = "tools") -> int:
    if cursor in (None, ""):
        return 0
    if not isinstance(cursor, str):
        raise ValueError(f"SDK {collection} cursor must be a string")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"SDK {collection} cursor is not valid") from exc
    offset = payload.get("sdk_offset") if isinstance(payload, dict) else None
    if not isinstance(offset, int) or offset < 0:
        raise ValueError(f"SDK {collection} cursor does not contain a valid offset")
    cursor_collection = payload.get("sdk_collection")
    if cursor_collection not in (None, collection):
        raise ValueError(f"SDK cursor for {cursor_collection!r} cannot be used for {collection!r}")
    return offset


def _sdk_ordered_items(
    items: Sequence[Mapping[str, Any]],
    priority_names: Sequence[str],
    identity: Callable[[Mapping[str, Any]], str],
) -> list[dict[str, Any]]:
    priority = {name: index for index, name in enumerate(priority_names)}
    indexed = [(index, dict(item)) for index, item in enumerate(items)]
    indexed.sort(key=lambda item: (priority.get(identity(item[1]), len(priority) + item[0]), item[0]))
    return [item for _index, item in indexed]


def _sdk_ordered_tools(tools: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _sdk_ordered_items(tools, SDK_AGENT_START_TOOLS, lambda tool: str(tool.get("name")))


def _sdk_page(
    items: Sequence[Mapping[str, Any]],
    *,
    cursor: Any,
    collection: str,
    page_size: int,
    priority_names: Sequence[str],
    identity: Callable[[Mapping[str, Any]], str],
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    offset = _decode_sdk_cursor(cursor, collection=collection)
    ordered = _sdk_ordered_items(items, priority_names, identity)
    page = ordered[offset : offset + page_size]
    next_offset = offset + len(page)
    has_more = next_offset < len(ordered)
    return (
        page,
        _encode_sdk_cursor(next_offset, collection=collection) if has_more else None,
        _sdk_pagination_meta(
            collection=collection,
            total_count=len(ordered),
            offset=offset,
            count=len(page),
            has_more=has_more,
            limit=page_size,
            first_page_priority=priority_names,
        ),
    )


def _sdk_pagination_meta(
    *,
    collection: str,
    total_count: int,
    offset: int,
    count: int,
    has_more: bool,
    limit: int,
    first_page_priority: Sequence[str],
) -> dict[str, Any]:
    return {
        "count": count,
        "total_count": total_count,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "collection": collection,
        "adapter_start_strategy": {
            "default_page_size": limit,
            "first_page_priority": list(first_page_priority),
            "note": "官方 SDK typed list_* 只支持标准 cursor；adapter 默认提供压缩首页，Agent 可按 nextCursor 拉取全集。",
        },
    }


def _sdk_tools_meta(*, total_count: int, offset: int, count: int, has_more: bool) -> dict[str, Any]:
    meta = _sdk_pagination_meta(
        collection="tools",
        total_count=total_count,
        offset=offset,
        count=count,
        has_more=has_more,
        limit=SDK_DEFAULT_TOOL_PAGE_SIZE,
        first_page_priority=SDK_AGENT_START_TOOLS,
    )
    meta["toolset"] = "all"
    meta["adapter_start_strategy"].update(
        {
            "recommended_first_calls": [
                {"method": "tools/call", "name": "context_policy", "arguments": {}},
                {"method": "resources/read", "uri": "keepa://tools/index"},
                {"method": "resources/read", "uri": "keepa://toolsets/research"},
            ],
            "resource_first_uris": list(SDK_AGENT_START_RESOURCES),
            "resource_template_first_uris": list(SDK_AGENT_START_RESOURCE_TEMPLATES),
            "prompt_first_names": list(SDK_AGENT_START_PROMPTS),
            "note": "官方 SDK typed list_tools 只支持标准 cursor；adapter 默认分页展示 all toolset，Agent 应先读 policy/resource，再按 nextCursor 拉取更多 schema。",
        }
    )
    return meta


def create_lowlevel_sdk_server(*, env: Mapping[str, str] | None = None) -> Any:
    """创建官方 Python SDK low-level Server。

    SDK server 只负责协议适配；工具、资源、提示词和预算账本继续复用现有
    registry 与 `AgentSession -> run_command`。
    """

    types, NotificationOptions, Server, _stdio = _require_sdk()
    server = Server(
        "keepa_mcp",
        version=__version__,
        instructions=(
            "Use context_policy first, then prefer keepa://tools/index or keepa://toolsets/research "
            "before paging through every tool schema. Prefer fixture or dry_run before live calls. "
            "High-cost requests return confirmation_required unless yes=true is supplied."
        ),
    )
    session = AgentSession(env=env)

    async def _list_tools(req: Any) -> Any:
        cursor = req.params.cursor if getattr(req, "params", None) and req.params.cursor else None
        offset = _decode_sdk_cursor(cursor)
        result = _current_mcp_result("tools/list", {"toolset": "all"}, session=session, env=env)
        ordered = _sdk_ordered_tools(result.get("tools") or [])
        page = ordered[offset : offset + SDK_DEFAULT_TOOL_PAGE_SIZE]
        next_offset = offset + len(page)
        has_more = next_offset < len(ordered)
        tools = [_tool_to_sdk(types, tool) for tool in page]
        server._tool_cache.clear()
        for tool in tools:
            server._tool_cache[tool.name] = tool
        return types.ServerResult(
            types.ListToolsResult(
                tools=tools,
                nextCursor=_encode_sdk_cursor(next_offset, collection="tools") if has_more else None,
                _meta=_sdk_tools_meta(total_count=len(ordered), offset=offset, count=len(page), has_more=has_more),
            )
        )
    server.request_handlers[types.ListToolsRequest] = _list_tools

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
        response = handle_mcp_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "sdk-call",
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                },
            ),
            env=env,
            session=session,
        )
        if response is None:
            return types.CallToolResult(content=[], isError=False)
        if "error" in response:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(response["error"], ensure_ascii=False, sort_keys=True))],
                structuredContent={"error": response["error"]},
                isError=True,
            )
        return _tool_result_to_sdk(types, response.get("result") or {})

    async def _list_resources(req: Any) -> Any:
        cursor = req.params.cursor if getattr(req, "params", None) and req.params.cursor else None
        result = _current_mcp_result("resources/list", {}, session=session, env=env)
        page, next_cursor, meta = _sdk_page(
            result.get("resources") or [],
            cursor=cursor,
            collection="resources",
            page_size=SDK_DEFAULT_RESOURCE_PAGE_SIZE,
            priority_names=SDK_AGENT_START_RESOURCES,
            identity=lambda resource: str(resource.get("uri")),
        )
        return types.ServerResult(
            types.ListResourcesResult(
                resources=[_resource_to_sdk(types, resource) for resource in page],
                nextCursor=next_cursor,
                _meta=meta,
            )
        )
    server.request_handlers[types.ListResourcesRequest] = _list_resources

    async def _list_resource_templates(req: Any) -> Any:
        cursor = req.params.cursor if getattr(req, "params", None) and req.params.cursor else None
        result = _current_mcp_result("resources/templates/list", {}, session=session, env=env)
        page, next_cursor, meta = _sdk_page(
            result.get("resourceTemplates") or [],
            cursor=cursor,
            collection="resource_templates",
            page_size=SDK_DEFAULT_RESOURCE_TEMPLATE_PAGE_SIZE,
            priority_names=SDK_AGENT_START_RESOURCE_TEMPLATES,
            identity=lambda template: str(template.get("uriTemplate")),
        )
        return types.ServerResult(
            types.ListResourceTemplatesResult(
                resourceTemplates=[_resource_template_to_sdk(types, template) for template in page],
                nextCursor=next_cursor,
                _meta=meta,
            )
        )
    server.request_handlers[types.ListResourceTemplatesRequest] = _list_resource_templates

    async def _read_resource(req: Any) -> Any:
        content = read_mcp_resource(str(req.params.uri), session_cache=session.cache)
        if "text" in content:
            resource_content = types.TextResourceContents(
                uri=content["uri"],
                text=str(content["text"]),
                mimeType=content.get("mimeType"),
                _meta=content.get("_meta"),
            )
        else:
            resource_content = types.BlobResourceContents(  # pragma: no cover - 当前资源均为 text。
                uri=content["uri"],
                blob=str(content.get("blob", "")),
                mimeType=content.get("mimeType"),
                _meta=content.get("_meta"),
            )
        return types.ServerResult(types.ReadResourceResult(contents=[resource_content]))
    server.request_handlers[types.ReadResourceRequest] = _read_resource

    async def _list_prompts(req: Any) -> Any:
        cursor = req.params.cursor if getattr(req, "params", None) and req.params.cursor else None
        result = _current_mcp_result("prompts/list", {}, session=session, env=env)
        page, next_cursor, meta = _sdk_page(
            result.get("prompts") or [],
            cursor=cursor,
            collection="prompts",
            page_size=SDK_DEFAULT_PROMPT_PAGE_SIZE,
            priority_names=SDK_AGENT_START_PROMPTS,
            identity=lambda prompt: str(prompt.get("name")),
        )
        return types.ServerResult(
            types.ListPromptsResult(
                prompts=[_prompt_to_sdk(types, prompt) for prompt in page],
                nextCursor=next_cursor,
                _meta=meta,
            )
        )
    server.request_handlers[types.ListPromptsRequest] = _list_prompts

    @server.get_prompt()
    async def _get_prompt(name: str, arguments: dict[str, str] | None) -> Any:
        try:
            prompt = get_mcp_prompt(name, dict(arguments or {}))
        except ValueError as exc:
            raise ValueError(json.dumps({"prompt": name, "message": str(exc), "available_prompts": prompt_names()}, ensure_ascii=False)) from exc
        return types.GetPromptResult(
            description=prompt.get("description"),
            messages=[_prompt_message_to_sdk(types, message) for message in prompt.get("messages") or []],
            _meta=prompt.get("_meta"),
        )

    # Touch registries early so startup failures surface before clients initialize.
    list_mcp_resources()
    list_mcp_prompts()
    server._keepa_notification_options = NotificationOptions()  # type: ignore[attr-defined]
    return server


async def run_sdk_stdio(*, env: Mapping[str, str] | None = None) -> None:
    types, NotificationOptions, _Server, stdio = _require_sdk()
    del types
    server = create_lowlevel_sdk_server(env=env)
    async with stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(notification_options=NotificationOptions()),
            raise_exceptions=False,
        )


def create_fastmcp_readonly_spike(*, env: Mapping[str, str] | None = None) -> Any:
    """创建官方 Python SDK FastMCP 只读 spike。

    该函数只证明 SDK adapter 可以复用 `AgentSession -> run_command`，不承诺与生产
    tool 名全集完全一致；真正替换前必须通过 `compare_fixture_outputs`。
    """

    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError("官方 Python MCP SDK 未安装；使用 keepa-cli[mcp-sdk] 后再运行该 spike。") from exc

    mcp = FastMCP("keepa_mcp", json_response=True)
    session = AgentSession(env=env)

    @mcp.tool(name="context_policy")
    def keepa_context_policy() -> dict[str, Any]:
        """读取 Keepa-cli Agent/MCP 上下文策略。"""

        return _execute_local_tool(session, "context_policy", {})

    @mcp.tool(name="docs_index")
    def keepa_docs_index() -> dict[str, Any]:
        """读取本地 Agent 文档与 MCP resource 索引。"""

        return _execute_local_tool(session, "docs_index", {})

    @mcp.tool(name="docs_read")
    def keepa_docs_read(uri: str = "", page: str = "") -> dict[str, Any]:
        """读取本地 MCP resource URI 或 zread 页面。"""

        arguments = {key: value for key, value in {"uri": uri, "page": page}.items() if value}
        return _execute_local_tool(session, "docs_read", arguments)

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or inspect the isolated official MCP SDK adapter.")
    parser.add_argument("--stdio", action="store_true", help="Run the official SDK low-level server over stdio.")
    parser.add_argument("--status", action="store_true", help="Print adapter status as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.status or not args.stdio:
        print(json.dumps(adapter_status(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    asyncio.run(run_sdk_stdio(env=None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
