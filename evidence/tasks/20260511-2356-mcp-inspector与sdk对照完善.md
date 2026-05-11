# 任务日志：MCP Inspector 与 SDK adapter 对照完善

## 任务时间

- 开始时间：2026-05-11 23:52
- 最近更新时间：2026-05-11 23:56
- 完成时间：2026-05-11 23:56
- 当前状态：已完成

## 任务目标

- 补充 MCP Inspector 风格协议 fixture，覆盖初始化、发现、分页、错误与 ping。
- 做官方 Python MCP SDK adapter 对照，明确当前生产入口是否应切换。
- 增加 `serverInfo.name=keepa_mcp` 的客户端迁移说明，避免客户端别名和 `keepa.*` tool 名被误改。

## 背景与输入

- 用户输入：要求使用 `D:\.codex\skills\mcp-builder\SKILL.md` 继续完善项目，补 MCP Inspector 协议 fixture、官方 Python MCP SDK adapter 对照和 `serverInfo.name=keepa_mcp` 迁移说明。
- 本轮读取：`mcp-builder` skill、官方 Python MCP SDK README、Model Context Protocol lifecycle/serverInfo 规范、当前 diff、MCP fixture、Agent contract、README 与 docs index。
- 假设：本轮只做协议回归与文档契约补强，不引入新的运行时依赖，不访问真实 Keepa API，不消耗真实 token。
- 不确定性：官方 Python MCP SDK 后续版本仍可能调整 FastMCP、stdio 或 Inspector 调试链路；因此 adapter 被定位为隔离 spike，而不是直接替换当前生产 stdio transport。

## 处理过程

### 1. MCP Inspector 协议 fixture

- 新增 `tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json`。
- fixture 类型为 `mcp_session`，包含 7 个步骤：`initialize`、分页 `tools/list`、`resources/list`、`prompts/list`、`resources/templates/list`、非法 `tools/call` 与 `ping`。
- 断言覆盖 `protocolVersion=2025-11-25`、`serverInfo.name=keepa_mcp`、tool `title/execution/annotations/outputSchema`、分页 `_meta/nextCursor`、资源/提示词发现、结构化工具错误与 ping 空结果。

### 2. 官方 Python MCP SDK adapter 对照

- 新增 `docs/architecture/mcp-python-sdk-adapter-comparison.md`。
- 结论：当前保留手写 JSON-RPC stdio transport 作为生产入口；官方 Python MCP SDK / FastMCP 只作为后续隔离 adapter spike。
- 原因：现有实现已稳定承接 `run_command`、`AgentSession`、动态 toolset/profile/filter/pagination、resources/templates/prompts、chunk/output resources 与 budget ledger；直接切换会扩大依赖和协议兼容风险。
- 后续准入条件：SDK adapter 必须通过现有 MCP protocol fixture、agent eval fixture、schema snapshot、doctor、npm wrapper 与 release gate；且不得绕过 token budget、fixture/dry-run 和脱敏门禁。

### 3. 客户端迁移说明

- 更新 `docs/agent-contract.md`，明确 `serverInfo.name=keepa_mcp` 只表示 MCP server identity。
- 明确客户端配置别名仍可继续叫 `keepa`，不要强制改为 `keepa_mcp`。
- 明确 `keepa.*` tool 名保持不变，不因 serverInfo 迁移而重命名。
- 明确只有硬编码断言 `serverInfo.name == "keepa"` 的外部客户端才需要更新为 `keepa_mcp`。
- 同步 `README.md`、`README.zh-CN.md`、`docs/architecture/mcp-agent-tools.md` 与 `docs/index.html` 的入口链接和摘要。

## 验证结果

- `.\\.venv\\Scripts\\python.exe scripts\\check_agent_eval_fixtures.py`：通过，`agent eval fixtures ok: 30 specs`。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_agent_eval_fixtures tests.test_mcp -v`：通过，49 项通过。
- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：通过，314 项通过。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe -m keepa_cli --json doctor`：通过。
- `node .\\bin\\keepa-cli.js --json doctor`：通过。
- `node .\\bin\\kc.js --json doctor`：通过。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步通过，打包 `entryCount=109`。

## 关联产物

- Fixture：`tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json`
- 文档：`docs/architecture/mcp-python-sdk-adapter-comparison.md`
- 文档同步：
  - `docs/agent-contract.md`
  - `docs/architecture/mcp-agent-tools.md`
  - `README.md`
  - `README.zh-CN.md`
  - `docs/index.html`

## 风险与后续

- 风险：真实 MCP Inspector UI 可能在展示层增加非协议字段；本轮 fixture 固化的是协议会话核心，不模拟 UI 内部状态。
- 风险：官方 Python MCP SDK 的 FastMCP decorator 能减少样板，但动态 toolset/profile/pagination 仍需要 adapter 层，短期不应直接迁移生产入口。
- 后续建议 1：创建隔离 `mcp_sdk_adapter.py` spike，只注册本地只读 `context_policy/docs_index/docs_read`，用 fixture 做等价对比。
- 后续建议 2：把 MCP Inspector 手工 smoke 的请求/响应导出流程文档化，便于 CI 之外做客户端兼容复查。
- 后续建议 3：若未来增加 streamable HTTP，仍应复用现有 service/session 层，只替换 protocol adapter，不复制 Keepa 业务逻辑。
