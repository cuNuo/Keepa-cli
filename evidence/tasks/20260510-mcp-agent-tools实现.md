# MCP Agent Tools 实现

## 任务目标

按 `docs/architecture/mcp-agent-tools.md` 实现第一阶段 MCP Agent tools：

- `agent/tools.py`：集中 MCP tool registry 与强类型 schema。
- `agent/session.py`：session cache、dedupe、token ledger 与确认阻断。
- `agent/mcp.py`：最小 MCP JSON-RPC stdio server。
- stdio 复用 `AgentSession`。
- CLI 暴露 `--mcp`。

## 背景与输入

- 用户要求功能要全面，遇到可优化点要继续完善。
- 当前项目已有 `run_command`、`--stdio`、Agent view、workflow plan 和 token budget。
- 本轮默认只使用 fixture/dry-run，不触发真实 Keepa API。

## 处理过程

1. 新增 `keepa_cli/agent/tools.py`，首批暴露：
   - `keepa.products_get`
   - `keepa.categories_search`
   - `keepa.categories_products`
   - `keepa.finder_query`
   - `keepa.audit_cost`
2. 新增 `keepa_cli/agent/session.py`：
   - 稳定 `cache_key`
   - 进程内成功响应缓存
   - `from_cache` 显式复用
   - 重复请求 dedupe
   - `budget_ledger.session_estimated/session_consumed/remaining_limit/blocked_actions/cache_hits`
3. 改造 `keepa_cli/agent/stdio.py`，让 JSON Lines 长会话复用同一个 `AgentSession`。
4. 新增 `keepa_cli/agent/mcp.py`，支持：
   - `initialize`
   - `notifications/initialized`
   - `tools/list`
   - `tools/call`
   - JSON-RPC parse、method、params、unknown tool 错误。
5. `cli.py` 新增 `--mcp` 入口。
6. `capabilities` schema 提升到 `2026-05-10.9`，暴露 MCP server 信息和 tools。
7. 更新 `README.md`、`README.zh-CN.md`、`docs/agent-contract.md` 与 MCP 架构文档。

## 验证结果

定向测试：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_session tests.test_mcp tests.test_stdio tests.test_capabilities -v
```

结果：22 tests passed。

待最终交付前继续运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
```

## 关联产物

- `keepa_cli/agent/tools.py`
- `keepa_cli/agent/session.py`
- `keepa_cli/agent/mcp.py`
- `keepa_cli/agent/stdio.py`
- `keepa_cli/cli.py`
- `keepa_cli/capabilities.py`
- `tests/test_agent_session.py`
- `tests/test_mcp.py`
- `tests/test_stdio.py`
- `tests/test_capabilities.py`
- `README.md`
- `README.zh-CN.md`
- `docs/agent-contract.md`
- `docs/architecture/mcp-agent-tools.md`

## 风险与后续

- MCP 当前为最小 stdio JSON-RPC server，尚未接官方 Python SDK、SSE 或 Streamable HTTP。
- Session cache 第一阶段只在进程内，不跨会话持久化。
- 下一步最值得做 Agent evaluation fixtures，用固定任务集断言 tool 输出，而不是只测协议成功。
- P2 后续应实现 `research_graph`、统一 `risk_taxonomy` 与 `fixtures promote`。

## 结论

Keepa-cli 已具备第一阶段 MCP Agent tools、会话缓存和 token ledger 基础能力，且仍保持 CLI、stdio、MCP 共享同一 `run_command` 业务入口。
