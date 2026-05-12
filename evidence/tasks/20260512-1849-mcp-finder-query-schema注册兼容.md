# MCP finder_query schema 注册兼容

## 任务目标

- 修复外部 MCP 客户端注册 `finder_query` 时的 schema 报错：`schema must have type 'object' and not have 'oneOf'/'anyOf'/'allOf'/'enum'/'not' at the top level`。
- 用真实 `python -m keepa_cli --mcp` stdio 路径验证 `tools/list` 与 `tools/call`，避免只在内存 handler 层通过。
- 明确当前会话若仍报错时的原因边界：正在运行的 Codex/MCP 会话可能已缓存旧工具 schema，需要重启宿主会话后重新握手。

## 背景与输入

- 用户反馈 Keepa MCP 仍因 `finder_query` schema 被外部函数注册层拒绝，导致实际对话无法继续。
- 相关工作区已有未提交改动：`keepa_cli/agent/tools.py`、`tests/test_mcp.py`，本轮在此基础上继续收口，没有回退既有变更。
- 关键假设：业务侧仍需要保留 `finder_query` / `deals_query` 的互斥入参校验；对外 MCP `inputSchema` 仅移除外部注册层不接受的顶层组合关键字，业务校验继续由 `validate_tool_arguments()` 与命令级规则执行。

## 处理过程

1. 在 `ToolDefinition.to_mcp_tool()` 中将对外 `inputSchema` 切换为 `_mcp_input_schema()`。
2. 新增 `ROOT_SCHEMA_KEYWORDS_UNSUPPORTED_BY_TOOL_REGISTRATION`，仅从 MCP 工具注册 schema 顶层移除 `oneOf`、`anyOf`、`allOf`、`enum`、`not`，并保证顶层 `type=object` 与 `properties` 存在。
3. 保留 `_schema_with_common_properties()` 作为工具调用入参校验 schema，避免为了外部注册兼容削弱运行时参数约束。
4. 在 `tests/test_mcp.py` 增加 handler 层 schema 注册兼容断言，覆盖所有 `toolset=all` 工具。
5. 在 `tests/test_mcp_client_example.py` 增加真实 stdio 子进程回归测试，启动 `python -m keepa_cli --mcp` 后验证：
   - `tools/list` 中 `finder_query.inputSchema.type == object`；
   - 顶层不含外部注册层禁用关键字；
   - `tools/call finder_query` 使用本地 selection fixture dry-run 成功。
6. 更新 `tests/snapshots/agent_schema_snapshot.json`，同步冻结新的 MCP 工具 schema 形状。

## 验证结果

- `.\.venv\Scripts\python.exe -m unittest tests.test_mcp.McpProtocolTests.test_tools_list_input_schemas_are_registration_compatible tests.test_mcp_client_example.McpClientExampleTests.test_real_stdio_finder_query_schema_is_registration_compatible -v`：通过。
- 真实 stdio 手动验证：`tools_count=33`，`finder_schema_type=object`，`finder_forbidden_root_keywords=[]`，`finder_call_is_error=false`，`finder_call_ok=true`。
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`：355 项通过。
- `git diff --check`：通过；期间发现 snapshot 被 Windows 默认 CRLF 重写，已规范化回 LF。
- `.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only`：相关 Hook 全部通过。
- `.\.venv\Scripts\python.exe -m keepa_cli --json doctor`：通过。
- `node .\bin\keepa-cli.js --json doctor`：通过。
- `node .\bin\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack 触发 release gate，包含 MCP quality gate、SDK adapter fixture parity、SDK smoke、typed fixture、Inspector snapshot 与全量 unittest。

## 关联产物

- `keepa_cli/agent/tools.py`
- `tests/test_mcp.py`
- `tests/test_mcp_client_example.py`
- `tests/snapshots/agent_schema_snapshot.json`

## 风险与后续

- 当前运行中的 Codex 会话如果已经在修复前加载了旧 MCP 工具清单，仍可能继续报同一 schema 错误；需要重启 Codex/宿主 MCP 会话，让 `D:\github\Keepa-cli\.venv\Scripts\python.exe -m keepa_cli --mcp` 重新握手并重新注册工具。
- 本次只移除对外注册 schema 的顶层组合关键字；嵌套属性中的 `enum` 仍保留，因为 OpenAI/JSON Schema 工具参数通常支持属性级 enum，且运行时 validator 已覆盖 enum 负向用例。
- 若后续仍有外部客户端采用更窄 JSON Schema 子集，可继续增加“注册 schema sanitizer”白名单测试，而不是削弱运行时 validator。

## 结论

`finder_query` 的 MCP 对外工具注册 schema 已兼容外部函数注册层要求，真实 stdio `tools/list` 与 `tools/call` 已验证成功。若用户当前对话仍看到相同错误，最可能是宿主会话缓存旧工具 schema，需要重启 Codex 会话后重连 Keepa MCP。

对应长期记忆：`mcp_finder_query_registration_schema_compat_20260512`。
