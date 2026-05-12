# MCP JSON Schema validator 与入口评估

## 前置说明

- 时间：2026-05-12 11:29 +08:00。
- 范围：MCP `tools/call` 入参校验、raw stdio handler、官方 Python SDK adapter smoke、Agent eval fixture、生产入口评估。
- 规范来源：`D:\.codex\skills\mcp-builder\SKILL.md`、MCP Python SDK README、MCP `2025-11-25` tools 规范。
- 网络与真实 API：仅读取官方公开文档；未访问真实 Keepa API，未消耗真实 token。

## 变更

- 在 `keepa_cli/agent/tools.py` 新增共享 JSON Schema 子集 validator，覆盖 `type`、`enum`、`minimum`、`maximum`、`oneOf`、`anyOf`、`additionalProperties` 和 array `items`。
- `validate_tool_arguments()` 改为先基于 MCP 实际暴露的 `inputSchema` 做统一校验，再追加既有业务级跨字段规则。
- `tools/call` 失败路径继续返回 JSON-RPC result，`isError=true`，`structuredContent.error.kind=invalid_arguments`，保持 Agent 可自修复语义。
- 新增 `tests/agent_eval_fixtures/mcp_schema_validation_negative.json`，固定错误类型、非法 enum、越界 integer、array item 类型错误四类负向 fixture。
- `tests/test_mcp.py` 增加 raw MCP JSON Schema 负向单测。
- `scripts/smoke_mcp_sdk_adapter_client.py` 增加官方 `ClientSession` 负向调用，确认 SDK adapter 也得到同一 `invalid_arguments` 结构化错误。
- FastMCP 只读 spike 改为通过 `@mcp.tool(name=...)` 显式注册 `context_policy`、`docs_index`、`docs_read`，避免函数名把 `keepa_` 前缀带回工具名。
- `docs/architecture/mcp-python-sdk-adapter-comparison.md` 更新生产入口评估：暂不替换生产入口，公共 MCP tool/prompt 名破坏性移除 `keepa.` 前缀，不保留旧名 alias。

## 生产入口评估

当前不把官方 SDK adapter 提升为生产入口，改为保留 `python -m keepa_cli --mcp` 作为稳定 stdio 入口，并持续用官方 SDK adapter 质量门禁约束兼容性。

原因：

- JSON Schema 校验已落在共享 tool registry 调用层，raw handler 与 SDK adapter 都会复用同一结果。
- 官方 `ClientSession.list_*` 仍只支持标准 cursor，不支持 Keepa 扩展 `toolset/limit/profile` 过滤参数；直接替换会改变 Agent 起手发现策略。
- 现有 dynamic resource templates、session cache、workflow resolver、budget ledger 与 compact text resource manifest 仍依赖项目自有协议边界。
- 为符合当前命名要求，本轮直接移除公共 MCP tool/prompt 名的 `keepa.` 前缀；旧名不再作为 alias 兼容。

## 验证

- `python -m py_compile keepa_cli\agent\tools.py`：通过。
- `python -m unittest tests.test_mcp.McpProtocolTests.test_invalid_tool_arguments_return_structured_tool_error tests.test_mcp.McpProtocolTests.test_json_schema_tool_arguments_return_structured_errors -v`：通过。
- `python scripts/check_agent_eval_fixtures.py`：通过，32 specs。
- `python scripts/smoke_mcp_sdk_adapter_client.py --json`：通过，包含 SDK adapter schema 负向调用。
- `python scripts/check_mcp_quality_gate.py --require-sdk --json`：通过。
- `python -m unittest discover -s tests -v`：通过，329 tests。
- `tools/call context_policy`：通过；`tools/call keepa.context_policy`：返回 JSON-RPC `-32602 Unknown tool`。
- FastMCP 只读 spike 注册工具名：`context_policy`、`docs_index`、`docs_read`，无 `keepa.` 或 `keepa_` 公开前缀。
- `git diff --check`、`D:\.codex\hooks\run_relevant_hooks.py --changed-only`、Python/Node doctor、`npm pack --dry-run --json`：通过。

## 风险与后续

- 当前 validator 是项目内置 JSON Schema 子集实现，避免给默认安装新增依赖；后续若 schema 复杂度继续上升，再评估引入 `jsonschema` 作为正式依赖。
- 无前缀工具名是当前唯一公开契约；若后续需要恢复旧名，需要单独提出兼容策略并补客户端迁移测试。
- 若要切换到 FastMCP 生产入口，应先做完整 adapter parity：toolset/profile/filter 分页、resource templates、direct `CallToolResult`、session cache 与 Inspector UI 都必须稳定。
