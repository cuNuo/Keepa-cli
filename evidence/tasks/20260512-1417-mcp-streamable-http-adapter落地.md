# MCP Streamable HTTP adapter 落地

## 任务目标

- 将 Streamable HTTP 从 contract harness 升级为真实可运行 adapter。
- 保持 HTTP adapter 只做协议层，不复制 Keepa tool/resource/prompt/service 业务逻辑。
- 保持公共 MCP tool/prompt 名无 `keepa.` 前缀。
- 长任务仍不塞进普通 `tools/call`；后续 Tasks/progress 必须同时覆盖 cancel、progress、result resource。

## 背景与输入

- 官方 MCP `2025-11-25` Streamable HTTP 规范要求 HTTP endpoint 处理 JSON-RPC message，支持 session id、protocol version、Origin 防护，并允许 DELETE 终止 session；GET SSE 仅在服务端支持 server-to-client stream 时启用。
- 官方 MCP Tasks 仍是实验能力；当前项目不声明 Tasks capability，因此本轮只保留 future contract，不把 `reports_build` / `figures_research` 改成长任务队列。
- 本轮不访问真实 Keepa API，不消耗真实 token。

## 处理过程

- 新增 `keepa_cli/agent/mcp_http.py`：
  - 使用 Python 标准库 `ThreadingHTTPServer`，默认 `127.0.0.1:8765`。
  - 暴露 `POST /mcp`、`DELETE /mcp`、`OPTIONS /mcp`。
  - `GET /mcp` 明确返回 405，当前不声明 SSE stream。
  - 处理 CORS preflight、Origin allowlist、`MCP-Protocol-Version`、`MCP-Session-Id`、`Keepa-MCP-Timeout-Ms`、显式错误 `Accept` / `Content-Type` 和 JSON response encoding。
- 扩展 `StreamableHttpAdapterContract`：
  - 由前置 contract harness 升级为 HTTP adapter shared protocol core。
  - session id 改为带随机 token 的可见 ASCII id。
  - DELETE 会终止活动 session，并让旧 id 后续返回 expired session。
  - 空闲 session 默认 1 小时清理，活动 HTTP session 上限 128，避免长进程反复 initialize 后状态无限增长。
  - JSON-RPC response / notification 映射为 HTTP 202。
  - 有效 JSON-RPC 请求统一进入 `handle_mcp_message -> AgentSession -> service`。
  - 请求 timeout 通过 daemon thread wait boundary 返回 HTTP 504，避免 HTTP handler 无限阻塞；长任务仍应迁移 Tasks/progress。
- CLI 增加：
  - `--mcp-http`
  - `--mcp-http-host`
  - `--mcp-http-port`
  - `--mcp-http-origin`
- 能力发现更新：
  - `schema_version=2026-05-12.3`
  - `protocols` 增加 `mcp-http`
  - `mcp.transports.streamable_http` 记录 endpoint、entrypoint、session/protocol/timeout/header 内容协商与 `business_core`。
- 质量门禁更新：
  - `scripts/check_mcp_quality_gate.py` 纳入 `tests.test_mcp_http_contract` 与 `tests.test_mcp_http_adapter`。
- Fixture / 文档同步：
  - `mcp_streamable_http_boundary_fixture.json` 把 DELETE 从“显式不支持”改为“终止活动 session”，并补充显式错误 `Accept` 406、非 JSON `Content-Type` 415。
  - README、README.zh-CN、`docs/agent-contract.md`、`docs/architecture/mcp-python-sdk-adapter-comparison.md` 同步 HTTP adapter 已落地边界。

## 验证结果

- `python -m py_compile keepa_cli/agent/mcp_http_contract.py keepa_cli/agent/mcp_http.py keepa_cli/cli.py tests/test_mcp_http_adapter.py tests/test_mcp_http_contract.py`：通过。
- `python -m unittest tests.test_mcp_http_contract tests.test_mcp_http_adapter -v`：17 项通过。
- `python -m unittest tests.test_mcp_http_contract tests.test_mcp_http_adapter tests.test_capabilities tests.test_schema_snapshot -v`：19 项通过。
- `python scripts/check_agent_eval_fixtures.py`：32 specs 通过。
- `python scripts/check_mcp_quality_gate.py --require-sdk --json`：通过，新增 `streamable http adapter` step。
- `python -m unittest discover -s tests -v`：349 项通过。
- `git diff --check`：通过。
- `python D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过，覆盖源码头、目录反模式、AGENTS 与治理文本 mixed 检查。
- `python -m keepa_cli --json doctor`、`node .\bin\keepa-cli.js --json doctor`、`node .\bin\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步执行 compile、349 项 unittest、fixture sync、MCP quality gate 与 install verify。
- 真实 CLI HTTP smoke：`python -m keepa_cli --mcp-http --mcp-http-host 127.0.0.1 --mcp-http-port 0` 启动后，`POST /mcp initialize` 返回 HTTP 200、`MCP-Session-Id` 与 `serverInfo.name=keepa_mcp`。
- `python -m keepa_cli --json capabilities`：返回 `schema_version=2026-05-12.3` 且 `streamable_http.endpoint=/mcp`。

## 风险与后续

- 当前 `GET /mcp` 不提供 SSE stream；若未来需要服务端主动事件流，必须新增真实 event stream 测试后再声明支持。
- Timeout 只能让 HTTP handler 返回 504；Python 线程无法跨平台强杀已启动业务逻辑，所以大型报告/图表仍必须迁移 MCP Tasks/progress，而不是依赖 timeout。
- HTTP endpoint 默认本机监听；开放到远程网络前必须显式配置 Origin、部署层 TLS、请求体大小与外层超时。
- Keepa token 不足继续返回等待/降级 guidance，不作为永久拒绝。

## 结论

Streamable HTTP adapter 已作为真实入口落地，入口命令为 `keepa-cli --mcp-http --mcp-http-host 127.0.0.1 --mcp-http-port 8765`。HTTP server 与 fixture tests 共用同一个 adapter core，所有业务仍复用 raw MCP handler、AgentSession 与 service 层。
