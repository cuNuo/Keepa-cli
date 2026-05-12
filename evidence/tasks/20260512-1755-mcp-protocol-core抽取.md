# MCP ProtocolCore 抽取

## 任务目标

按用户要求认真执行破坏性重构：抽出共享 `MCPProtocolCore`，把 MCP 方法分发、分页 cursor、JSON-RPC 错误映射、tool result 封装从 stdio raw handler 中剥离，让 stdio、官方 SDK adapter 与 Streamable HTTP adapter 都只保留 transport 边界。

## 背景与输入

- 用户输入：`抽出共享 MCPProtocolCore：把方法分发、分页、cursor、错误映射、tool result 封装从 raw handler 中抽离；stdio、SDK、HTTP 都只做 transport。认真去做`
- 对照约束：`$mcp-builder` 要求清晰协议边界、结构化 schema/result、分页、可操作错误与评测；项目根要求使用 `.venv`、默认离线、改动命中 Hook 时运行相关检查。
- 前置分析 evidence：`evidence/tasks/20260512-1729-mcp-builder官方实现对照评估.md`。

## 处理过程

1. 新增 `keepa_cli/agent/mcp_core.py`：
   - 定义无状态 `MCPProtocolCore`。
   - 迁移 JSON-RPC result/error、`initialize`、`tools/list`、`tools/call`、`resources/list/read`、`resources/templates/list`、`prompts/list/get`。
   - 迁移 cursor 编解码、分页、starter tools 排序、tool result、tool error result 与 compact text/resource link 封装。
2. 收缩 `keepa_cli/agent/mcp.py`：
   - 保留 `handle_mcp_message`、`iter_mcp_output`、`iter_mcp_stream` 兼容入口。
   - stdio 逐行处理只负责 I/O 与 session 生命周期，协议语义委托 `DEFAULT_MCP_PROTOCOL_CORE`。
   - 重新导出旧测试和脚本仍需使用的内部兼容 helper。
3. 调整官方 SDK adapter：
   - `handle_sdk_adapter_message()` 与 low-level SDK server 的 list/call 路径直接调用 `MCPProtocolCore`。
   - adapter status 的 `business_core` 更新为 `MCPProtocolCore -> AgentSession -> service`。
   - fixture 对比仍保留生产 stdio wrapper 作为外部兼容入口，确保迁移后输出等价。
4. 调整 Streamable HTTP：
   - `mcp_http_contract.py` 的 JSON-RPC 业务委托共享 core。
   - HTTP adapter 继续只处理 Origin、session、timeout、内容协商、HTTP status 与 CORS。
5. 同步文档与测试：
   - README、README.zh-CN、Agent contract、SDK adapter 对照文档中的业务核心描述改为 `MCPProtocolCore -> AgentSession -> service`。
   - 增加 `tests/test_mcp.py` 对 stdio wrapper 与 core 等价、core session cache 复用的直接覆盖。
   - 更新 capabilities、SDK adapter、HTTP contract 相关断言和 fixture 描述。

## 验证结果

- `.\.venv\Scripts\python.exe -m py_compile keepa_cli\agent\mcp_core.py keepa_cli\agent\mcp.py keepa_cli\agent\mcp_sdk_adapter.py keepa_cli\agent\mcp_http_contract.py keepa_cli\agent\mcp_http.py keepa_cli\capabilities.py`：通过。
- `.\.venv\Scripts\python.exe -m unittest tests.test_mcp tests.test_mcp_sdk_adapter tests.test_mcp_http_contract tests.test_mcp_http_adapter tests.test_capabilities -v`：82 项通过。
- `.\.venv\Scripts\python.exe scripts\check_mcp_quality_gate.py --require-sdk --json`：通过，覆盖 32 个 agent eval specs、output schema、performance gate、HTTP adapter、SDK fixture parity、typed smoke、typed Inspector fixture 与 snapshot。
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`：353 项通过。
- `git diff --check`：通过。
- `.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过。
- `.\.venv\Scripts\python.exe -m keepa_cli --json doctor`：通过。
- `node .\bin\keepa-cli.js --json doctor`：通过。
- `node .\bin\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步通过。

## 关联产物

- `keepa_cli/agent/mcp_core.py`
- `keepa_cli/agent/mcp.py`
- `keepa_cli/agent/mcp_sdk_adapter.py`
- `keepa_cli/agent/mcp_http_contract.py`
- `keepa_cli/agent/mcp_http.py`
- `keepa_cli/capabilities.py`
- `tests/test_mcp.py`
- `tests/test_mcp_sdk_adapter.py`
- `tests/test_mcp_http_contract.py`
- `tests/test_capabilities.py`
- `tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json`
- `README.md`
- `README.zh-CN.md`
- `docs/agent-contract.md`
- `docs/architecture/mcp-python-sdk-adapter-comparison.md`

## 风险与后续

- 兼容边界：`keepa_cli.agent.mcp.handle_mcp_message` 仍保留，外部脚本无需迁移；真正的协议实现已迁到 `MCPProtocolCore`。
- SDK adapter 仍不是默认生产入口，`python -m keepa_cli --mcp` 继续作为 stdio 生产入口；后续若提升 SDK adapter，应继续以质量门禁和真实 client matrix 验证。
- HTTP adapter 仍未实现 SSE/Tasks/progress；长任务仍按既有 `x-keepa.long_running_candidate` 边界处理。

## 结论

本次已完成共享 `MCPProtocolCore` 抽取。stdio、SDK adapter 和 HTTP adapter 的有效 JSON-RPC 业务路径已收敛到同一 core，降低了分页、cursor、错误映射和工具结果封装在多 transport 间漂移的风险。
