# 任务日志：MCP SDK adapter 隔离 spike

## 任务时间

- 开始时间：2026-05-12 00:02
- 最近更新时间：2026-05-12 00:17
- 完成时间：2026-05-12 00:17
- 当前状态：已完成

## 任务目标

- SDK adapter 先做隔离 spike，不直接替换当前 stdio 生产入口。
- 用当前 MCP Inspector fixture 对比 SDK adapter 和现有 `--mcp` 输出等价性。
- 若后续增加 Streamable HTTP，只替换协议 adapter，继续复用 service/session 层。

## 背景与输入

- 用户输入：要求按前序结论继续落地 SDK adapter 隔离 spike、fixture 等价对比和 Streamable HTTP 边界。
- 本轮读取：`mcp-builder` skill、官方 Python MCP SDK README、现有 `keepa_cli/agent/mcp.py`、`keepa_cli/agent_eval.py`、MCP Inspector fixture、release gate 与 MCP 架构文档。
- 假设：本轮不安装 `mcp` SDK 到项目 `.venv`，只提供可选 extra 和隔离探针；当前生产入口仍为 `python -m keepa_cli --mcp`。
- 不确定性：官方 FastMCP 对 dotted tool name、完整分页和 resource templates 的表达可能需要低层 Server adapter；因此本轮只把 FastMCP 只读样例作为 spike，不宣称生产等价。

## 处理过程

### 1. 隔离 adapter 模块

- 新增 `keepa_cli/agent/mcp_sdk_adapter.py`。
- `adapter_status()` 明确报告：
  - `server_info_name=keepa_mcp`
  - `production_entrypoint=python -m keepa_cli --mcp`
  - `production_entrypoint_replaced=false`
  - `business_core=AgentSession -> run_command`
  - Streamable HTTP 只替换协议 adapter。
- `handle_sdk_adapter_message()` 当前以现有 MCP JSON-RPC handler 作为兼容性 oracle，确保后续 SDK/HTTP adapter 必须先与生产输出等价。
- `create_fastmcp_readonly_spike()` 仅在安装可选依赖 `keepa-cli[mcp-sdk]` 后创建 FastMCP 只读样例，复用 `AgentSession` 执行 `keepa.context_policy`、`keepa.docs_index`、`keepa.docs_read`。

### 2. Fixture 等价对比

- 新增 `scripts/compare_mcp_sdk_adapter_fixture.py`。
- 默认读取 `tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json`。
- 分别运行当前 `--mcp` handler 与隔离 adapter handler，并递归比较完整 JSON 输出。
- release gate 已新增该脚本，避免 SDK/HTTP spike 后输出漂移未被发现。

### 3. 测试与文档

- 新增 `tests/test_mcp_sdk_adapter.py`，覆盖 adapter 状态、fixture 等价、脚本入口和可选 FastMCP spike。
- `pyproject.toml` 新增可选 extra：`mcp-sdk = ["mcp>=1,<2"]`。
- 更新 `README.md`、`README.zh-CN.md`、`docs/agent-contract.md`、`docs/architecture/mcp-agent-tools.md`、`docs/architecture/mcp-python-sdk-adapter-comparison.md` 与 `docs/index.html`。
- 文档明确：后续 Streamable HTTP adapter 只处理请求解码、session id、Origin/localhost 防护、响应编码、错误码映射和 SDK/ASGI 生命周期；不得复制 service/session/tool registry 业务层。

## 验证结果

- `.\\.venv\\Scripts\\python.exe -m py_compile keepa_cli\\agent\\mcp_sdk_adapter.py scripts\\compare_mcp_sdk_adapter_fixture.py tests\\test_mcp_sdk_adapter.py`：通过。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_mcp_sdk_adapter -v`：4 项通过。
- `.\\.venv\\Scripts\\python.exe scripts\\compare_mcp_sdk_adapter_fixture.py`：通过，7 steps 等价。
- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：通过，318 项通过。
- `.\\.venv\\Scripts\\python.exe scripts\\check_agent_eval_fixtures.py`：通过，30 specs。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe -m keepa_cli --json doctor`：通过。
- `node .\\bin\\keepa-cli.js --json doctor`：通过。
- `node .\\bin\\kc.js --json doctor`：通过。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步通过，包含 318 项 unittest、30 个 agent eval specs、SDK adapter fixture 等价检查，打包 `entryCount=110`。

## 关联产物

- 代码：
  - `keepa_cli/agent/mcp_sdk_adapter.py`
  - `scripts/compare_mcp_sdk_adapter_fixture.py`
- 测试：
  - `tests/test_mcp_sdk_adapter.py`
- 配置：
  - `pyproject.toml`
  - `scripts/release_gate.py`
- 文档：
  - `docs/architecture/mcp-python-sdk-adapter-comparison.md`
  - `docs/agent-contract.md`
  - `docs/architecture/mcp-agent-tools.md`
  - `README.md`
  - `README.zh-CN.md`
  - `docs/index.html`

## 风险与后续

- 风险：当前 `.venv` 未安装官方 `mcp` SDK，因此 FastMCP 只读样例只验证可选依赖缺失路径；真实 SDK 行为仍需安装 extra 后手工 smoke。
- 风险：FastMCP 默认 tool 命名与 Keepa-cli 现有 dotted `keepa.*` tool 名可能不一致，完整 adapter 可能需要官方低层 Server API。
- 后续建议 1：在临时环境安装 `keepa-cli[mcp-sdk]`，用 MCP Inspector 连接 FastMCP 只读样例，记录 dotted tool name 与 structured output 差异。
- 后续建议 2：新增 Streamable HTTP 前先扩展 fixture，覆盖 HTTP session id、Origin 防护和错误映射。
- 后续建议 3：若 SDK adapter 需要完整 tool registry，优先做协议层映射，不把 `tool_params_to_command_params`、workflow resolver 或 budget ledger 复制到 adapter 中。
