# 任务日志：MCP 官方 SDK adapter 实现

## 任务时间

- 开始时间：2026-05-12 00:22
- 最近更新时间：2026-05-12 00:40
- 完成时间：2026-05-12 00:40
- 当前状态：已完成

## 任务目标

- 在项目 `.venv` 安装官方 Python MCP SDK。
- 按官方文档规范实现隔离 SDK adapter，保留当前 `python -m keepa_cli --mcp` stdio 生产入口。
- 用当前 fixture 对比兼容输出，并用官方 SDK `ClientSession` 做真实连接 smoke。
- 做全量测试、低成本真实 token 验证，并审查当前实现待完善清单。

## 背景与输入

- 用户输入：要求本地 `.venv` 安装 `mcp` 包，使用 `mcp-builder` 按官方文档规范实现，做好全部测试，可调用真实 token 做最终验证，并整理待完善清单。
- 本轮读取：`mcp-builder` skill、官方 Python MCP SDK README、已安装 `mcp==1.27.1` 的 low-level Server / ClientSession API、现有 MCP handler、Agent eval、release gate、MCP 架构文档。
- 假设：真实 token 验证只允许安全只读、低成本路径；本轮选择能力表中 `estimated_tokens=0`、无需确认的 `tokens.status`。
- 不确定性：官方 SDK typed `ClientSession.list_tools()` 只支持标准 cursor 参数，不能传 Keepa 扩展 `toolset/limit`；SDK adapter 因此默认暴露 `toolset=all`，后续需继续优化 Agent 起手提示和分页策略。

## 处理过程

### 1. 安装与 SDK API 探查

- 在项目 `.venv` 中执行 `.\\.venv\\Scripts\\python.exe -m pip install "mcp>=1,<2"`。
- 安装结果：`mcp==1.27.1`。
- 探查确认：
  - low-level `Server` 支持 `list_tools`、`call_tool`、`list_resources`、`read_resource`、`list_resource_templates`、`list_prompts`、`get_prompt` 与 stdio runner。
  - `ClientSession` 支持 `initialize`、`list_tools`、`call_tool`、`list_resources`、`read_resource`、`list_prompts`。
  - SDK typed list request 只保留标准 `cursor`，不会保留 Keepa 自定义 `toolset/limit` 参数。

### 2. 官方 SDK low-level adapter

- 扩展 `keepa_cli/agent/mcp_sdk_adapter.py`：
  - `ADAPTER_NAME=keepa_mcp_sdk_adapter`。
  - `adapter_status()` 输出 `sdk_available`、`sdk_version`、`sdk_stdio_entrypoint`、生产入口未替换、业务核心仍为 `AgentSession -> run_command`。
  - 新增 `create_lowlevel_sdk_server()`，使用官方 low-level `Server("keepa_mcp")` 注册 tools/resources/resource templates/prompts。
  - 新增 `run_sdk_stdio()` 与 CLI 入口：`python -m keepa_cli.agent.mcp_sdk_adapter --stdio`。
  - `tools/call` 继续复用现有 `handle_mcp_message`，保留 `structuredContent`、JSON text fallback、`isError`、budget ledger、workflow resolver 和 profile gating。
  - `resources/read`、`prompts/get`、typed tool/resource/prompt 转换均使用 SDK types。
- 保留 `handle_sdk_adapter_message()` 作为当前 MCP Inspector fixture 的兼容 handler，继续做 JSON-RPC 等价检查。

### 3. SDK client smoke 与 release gate

- 新增 `scripts/smoke_mcp_sdk_adapter_client.py`：
  - 使用官方 `ClientSession` 启动 `python -m keepa_cli.agent.mcp_sdk_adapter --stdio`。
  - 验证 `serverInfo.name=keepa_mcp`、33 个 tools、16 个 resources、8 个 prompts。
  - 调用 `keepa.context_policy` 并读取 `keepa://context/policy`。
- 更新 `tests/test_mcp_sdk_adapter.py`，新增官方 SDK client smoke。
- 更新 `scripts/release_gate.py`，增加 `scripts/smoke_mcp_sdk_adapter_client.py --skip-if-missing`。

### 4. 文档与待完善清单

- 更新 `README.md`、`README.zh-CN.md`、`docs/agent-contract.md`、`docs/architecture/mcp-agent-tools.md`、`docs/index.html`。
- 更新 `docs/architecture/mcp-python-sdk-adapter-comparison.md`：
  - 记录 low-level Server adapter 形态。
  - 说明官方 `ClientSession` 与 Keepa 扩展 list 参数的差异。
  - 新增 P0/P1/P2 待完善清单：CI 安装 optional SDK job、typed fixture 映射、Streamable HTTP 安全 fixture、MCP Inspector 实机样本、真实 token smoke 分层。

## 验证结果

- `.\\.venv\\Scripts\\python.exe -m pip install "mcp>=1,<2"`：通过，安装 `mcp==1.27.1`。
- `.\\.venv\\Scripts\\python.exe -m py_compile keepa_cli\\agent\\mcp_sdk_adapter.py scripts\\smoke_mcp_sdk_adapter_client.py tests\\test_mcp_sdk_adapter.py`：通过。
- `.\\.venv\\Scripts\\python.exe scripts\\smoke_mcp_sdk_adapter_client.py --json`：通过，33 tools、16 resources、8 prompts。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_mcp_sdk_adapter tests.test_agent_eval_fixtures tests.test_mcp -v`：54 项通过。
- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：319 项通过。
- `.\\.venv\\Scripts\\python.exe scripts\\check_agent_eval_fixtures.py`：通过，30 specs。
- `.\\.venv\\Scripts\\python.exe scripts\\compare_mcp_sdk_adapter_fixture.py`：通过，7 steps 等价。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- `.\\.venv\\Scripts\\python.exe -m keepa_cli --json doctor`：通过。
- `node .\\bin\\keepa-cli.js --json doctor`：通过。
- `node .\\bin\\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步通过，包含 319 项 unittest、30 specs、SDK fixture 等价与 SDK client smoke，打包 `entryCount=110`。
- 真实 token 低成本 smoke：`.\\.venv\\Scripts\\python.exe -m keepa_cli --json tokens status` 通过，`tokensConsumed=0`，`tokensLeft=139`，`source=live`。

## 关联产物

- 代码：
  - `keepa_cli/agent/mcp_sdk_adapter.py`
  - `scripts/smoke_mcp_sdk_adapter_client.py`
- 测试：
  - `tests/test_mcp_sdk_adapter.py`
- 门禁：
  - `scripts/release_gate.py`
- 文档：
  - `docs/architecture/mcp-python-sdk-adapter-comparison.md`
  - `docs/agent-contract.md`
  - `docs/architecture/mcp-agent-tools.md`
  - `README.md`
  - `README.zh-CN.md`
  - `docs/index.html`

## 风险与后续

- P0：远端 CI 当前仍不安装 `.[mcp-sdk]`，官方 SDK client smoke 在缺依赖环境会跳过；建议新增单独 CI job。
- P0：SDK adapter 默认暴露 `toolset=all`，后续需优化 Agent 起手策略，避免上下文过大。
- P1：当前 fixture 等价检查仍是兼容 handler 对比；需要继续把 Inspector fixture step 映射为 SDK typed client 调用。
- P1：Streamable HTTP adapter 需要先补 Origin/session/error fixture，不应直接上线。
- P2：真实 token smoke 当前只覆盖 `tokens.status`；产品 live read 需要单独手动流程、明确 token budget、cache provenance 和输出脱敏。
