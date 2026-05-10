# MCP Agent Tools 架构设计

## 任务目标

将 MCP 调研结论固化为项目架构文档，明确 Keepa-cli 后续如何为 Codex、Claude Code 和其他 Agent 暴露强类型 MCP tools。

## 背景与输入

- 用户要求先认真调研优秀 MCP 或相关 Agent 工具的组织方式，再组织本项目。
- 调研参考 MCP 官方 tools 规范、官方 Python SDK、OpenAI/Claude Code MCP 接入说明，以及 GitHub、Sentry、Stripe 等成熟 MCP server 的组织方式。
- 当前项目已有 `--json`、`--stdio`、Agent view、workflow plan、结构化 `next_actions` 与离线 fixture。

## 处理过程

1. 确认现有架构文档 `docs/architecture/service-cli-split-plan.md` 的写法，保持简洁 ADR 风格。
2. 新增 `docs/architecture/mcp-agent-tools.md`，明确以下设计：
   - MCP tools 不包装 CLI 字符串，只接受结构化 JSON params。
   - `run_command` 继续作为唯一业务入口。
   - 新增 `agent/tools.py`、`agent/session.py`、`agent/mcp.py`，并让 stdio 复用同一 session 层。
   - 第一阶段只暴露 5 个高价值 tools：`keepa.products_get`、`keepa.categories_search`、`keepa.categories_products`、`keepa.finder_query`、`keepa.audit_cost`。
   - session cache、dedupe、token ledger、confirmation policy 与 evidence/provenance 的契约。
   - MCP 响应同时返回 `structuredContent` 与 JSON text fallback。
   - 后续测试矩阵与实施顺序。

## 验证结果

- 文档已写入：`docs/architecture/mcp-agent-tools.md`。
- 本轮为设计文档固化，未执行真实 Keepa API 请求。

待交付前仍需运行：

```powershell
git diff --check
```

## 关联产物

- `docs/architecture/mcp-agent-tools.md`
- `evidence/tasks/20260510-mcp-agent-tools架构设计.md`

## 风险与后续

- 该文档只固化设计，尚未实现 MCP server。
- 下一步应先实现最小 MCP stdio server、5 个 tool schema 和测试，再接 session cache 与 budget ledger。
- P2 的 `research_graph`、`risk_taxonomy`、`fixtures promote` 应在协议层稳定后再做，避免耦合。

## 结论

MCP 接入的项目组织方式已固化：Keepa-cli 后续应采用薄 MCP transport、共享 `run_command`、独立 Agent session 层和集中 tool registry 的架构。
