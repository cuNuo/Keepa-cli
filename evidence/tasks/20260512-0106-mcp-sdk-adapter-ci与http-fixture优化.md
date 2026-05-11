# 任务日志：MCP SDK adapter CI 与 HTTP fixture 优化

## 任务时间

- 开始时间：2026-05-12 00:50
- 最近更新时间：2026-05-12 01:15
- 完成时间：待补充远端 CI
- 当前状态：本地验证通过，等待远端 CI

## 任务目标

- 远端 CI 增加安装 `.[mcp-sdk]` 的 SDK adapter job。
- 优化官方 SDK adapter 默认 `tools/list` 起手策略，保留 `toolset=all` 可发现性但避免一次性加载全部 schema。
- 将 MCP Inspector fixture step 映射为官方 SDK typed client 调用。
- 在实现 Streamable HTTP 前，先补 Origin、`MCP-Session-Id` 与错误映射 fixture。
- 为产品 live read 建立手动流程，带 token budget、cache provenance 和脱敏输出。

## 背景与输入

- 用户明确指出 FastMCP 默认 tool 命名可能不保留 dotted `keepa.*`，完整 adapter 可能需要 low-level Server API；当前实现继续使用官方 Python MCP SDK low-level `Server("keepa_mcp")`。
- 官方 MCP Streamable HTTP transport 文档要求服务器验证 `Origin`，本地 server 应优先绑定 localhost，初始化可返回 `MCP-Session-Id`，后续请求需携带该 header，缺失/过期 session 分别应按 400/404 处理。
- 官方 Python SDK typed `ClientSession.list_tools()` 只提供标准 cursor，不承载 Keepa 自定义 `toolset/limit` 参数；因此 typed fixture 映射需要记录该限制。

## 处理过程

### 1. CI 与 SDK typed client

- `.github/workflows/ci.yml` 新增 `mcp-sdk-adapter` job：
  - 安装 `python -m pip install -e ".[mcp-sdk]"`。
  - 运行 `tests.test_mcp_sdk_adapter` 与 `tests.test_mcp_http_contract`。
  - 运行 fixture 等价、官方 SDK smoke 与 typed fixture 映射脚本。
- `scripts/check_mcp_sdk_adapter_typed_fixture.py` 新增官方 SDK typed client 对照：
  - 映射 `initialize`、`tools/list`、`resources/list`、`prompts/list`、`resources/templates/list`、非法 `tools/call` 与 `ping`。
  - 对 `toolset/limit` 记录为 typed API 不支持的 fixture 扩展参数。

### 2. SDK adapter 起手策略

- `keepa_cli/agent/mcp_sdk_adapter.py` 保留 `toolset=all` 全集，但 SDK typed `list_tools` 默认分页为 8 个 starter tools。
- 第一页固定优先展示 `keepa.context_policy`、`keepa.docs_index`、`keepa.workflow_plan`、`keepa.agent_profile_generate` 与核心 research tools。
- `ListToolsResult._meta.adapter_start_strategy` 给出推荐起手调用：先 `keepa.context_policy`，再读 `keepa://tools/index` 与 `keepa://toolsets/research`，之后按 `nextCursor` 继续拉取完整 schema。

### 3. Streamable HTTP 前置 fixture

- 新增 `keepa_cli/agent/mcp_http_contract.py`，只描述协议边界，不启动 HTTP server。
- 新增 `tests/agent_eval_fixtures/mcp_streamable_http_boundary_fixture.json`：
  - Origin allowlist 与跨站 reject。
  - 初始化 session id、后续缺失 session、过期 session、DELETE not allowed。
  - malformed JSON、invalid request、application JSON-RPC error 与 notification 202 映射。
- 新增 `tests/test_mcp_http_contract.py` 覆盖 fixture 合约。

### 4. 产品 live read 手动流程

- 新增 `scripts/manual_live_product_read.py`：
  - 默认只执行 `products.get` dry-run，输出 worst-case token budget 与 dry-run cache provenance。
  - 只有显式 `--yes-live` 且存在 `KEEPA_API_KEY` 时才执行单 ASIN live read。
  - live 输出只包含 `tokens.status` 前后摘要、SQLite cache provenance、cache hit 与产品数量，不打印 API key 或完整原始商品响应。
- 新增 `tests/test_manual_live_product_read.py` 验证默认 dry-run 不访问真实 Keepa API。

## 已完成验证

- `.\\.venv\\Scripts\\python.exe -m pip install -e ".[mcp-sdk]"`：通过，本地 `.venv` 已安装 `mcp==1.27.1` 并以 editable 方式安装项目 optional extra。
- `.\\.venv\\Scripts\\python.exe -m py_compile keepa_cli/agent/mcp_sdk_adapter.py keepa_cli/agent/mcp_http_contract.py keepa_cli/agent_eval.py scripts/smoke_mcp_sdk_adapter_client.py scripts/check_mcp_sdk_adapter_typed_fixture.py scripts/manual_live_product_read.py`：通过。
- `.\\.venv\\Scripts\\python.exe scripts/smoke_mcp_sdk_adapter_client.py --json`：通过，33 tools、5 pages、first page 8 starter tools、16 resources、8 prompts。
- `.\\.venv\\Scripts\\python.exe scripts/check_mcp_sdk_adapter_typed_fixture.py --json`：通过，Inspector 7 steps 已映射，typed `list_tools` 记录 unsupported `limit/toolset`。
- `.\\.venv\\Scripts\\python.exe scripts/check_agent_eval_fixtures.py`：通过，31 specs。
- `.\\.venv\\Scripts\\python.exe scripts/manual_live_product_read.py --asin B001GZ6QEC --json`：通过，未执行 live，worst-case token=1，cache provenance source=dry-run。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_mcp_sdk_adapter tests.test_mcp_http_contract tests.test_manual_live_product_read tests.test_agent_eval_fixtures -v`：12 项通过。
- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：324 项通过。
- `.\\.venv\\Scripts\\python.exe scripts/check_fixture_sync.py`：通过。
- `.\\.venv\\Scripts\\python.exe scripts/compare_mcp_sdk_adapter_fixture.py`：通过，7 steps 等价。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- `.\\.venv\\Scripts\\python.exe -m keepa_cli --json doctor`、`node .\\bin\\keepa-cli.js --json doctor`、`node .\\bin\\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步跑过 compileall、324 项 unittest、live cache option lint、fixture sync、31 specs、SDK fixture 等价、SDK smoke、typed fixture、install_verify 与 doctor。

## 待完成验证

- 提交、推送并检查远端 CI。

## 风险与后续

- 官方 SDK typed `ClientSession` 仍不能传 Keepa 扩展 `toolset/limit`，当前通过 starter page + cursor 分页 + resource-first 指引规避；若后续 SDK 支持自定义 params，应优先恢复 typed 级 toolset/profile 过滤。
- Streamable HTTP 目前只有 contract fixture，没有 HTTP server；后续实现必须先让该 fixture 红线转为真实 adapter 集成测试。
- 产品 live read 脚本不会进入默认 CI；真实 token 验证必须人工显式 `--yes-live`，并应选择单 ASIN、低预算、可缓存请求。
