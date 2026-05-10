# report 与 tracking 工作流策略增强

## 前置说明

- 本轮继续优化 Keepa-cli 的 Agent/MCP 接入面，重点把前序 `workflow_policy` 从产品/类目研究扩展到报告生成和 tracking 只读审计链路。
- 未访问真实 Keepa API，未消耗真实 token；全部验证使用 fixture、dry-run、本地 MCP/CLI 或发布门禁。
- 本轮目标不是新增 tracking 写操作，而是让 Agent 在只读 tracking 审计中拿到受限 toolset、预算账本和可执行 step。

## 已落地

1. `workflow.plan report-research`
   - 新增本地报告链路：`research_graph.merge -> reports.build / research_brief.export / browse.snapshot`。
   - 推荐 `reports` toolset 与 `offline_fixture_only` profile。
   - 计划总 token 为 0，适合在已有 category / compare / seller 输出后做离线合并、报告和浏览页。

2. `workflow.plan tracking-audit`
   - 新增只读 tracking 审计链路：`tracking.list -> tracking.notifications / tracking.get / audit.cost`。
   - 推荐 `tracking-readonly` toolset 与 `tracking_readonly` profile。
   - 所有 tracking step 默认 `dry_run=true`，且不暴露 `tracking.add/remove/webhook` 等写操作。

3. MCP toolset 与 schema 同步
   - `reports` toolset 纳入 `keepa.research_graph_merge`，让报告链路能从图谱合并开始发现完整工具集。
   - `tracking-readonly` toolset 纳入 `keepa.audit_cost`，让 Agent 能在只读 tracking 计划内估算预算。
   - tracking MCP schemas 补 `domain` 参数，保证 `next_actions` 与 workflow step 可结构化执行。

4. Agent eval 与快照更新
   - 新增 `workflow_plan_report_research.json` 与 `workflow_plan_tracking_audit.json`。
   - Agent eval specs 从 19 扩展到 21，覆盖 reports/tracking workflow profile、toolset、预算与只读边界。
   - capabilities schema version 更新到 `2026-05-11.6`，并刷新 schema snapshot 与产品 agent-view schema。

5. 文档与项目内 skill 同步
   - README / 中文 README 增加 report/tracking workflow 示例。
   - `docs/agent-contract.md` 与 `docs/architecture/mcp-agent-tools.md` 记录四类内置 workflow plan。
   - 项目内 `.codex/skills/keepa-cli` 与 `.codex/skills/keepa-agent-research` 同步说明新 workflow。

## 已执行验证

- `python -m unittest discover -s tests -q`：通过。
- `python scripts/check_agent_eval_fixtures.py`：通过，21 specs。
- `python scripts/check_fixture_sync.py`：通过。
- `git diff --check`：通过；期间修正 `tests/snapshots/agent_schema_snapshot.json` 行尾回 LF。
- `python D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过。
- `python -m keepa_cli --json doctor`：通过。
- `node .\bin\keepa-cli.js --json doctor`：通过。
- `node .\bin\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过。
- `python scripts\release_gate.py --skip-npm-install`：独立日志确认退出码 0，输出 `release gate ok`。

## 风险与后续

- `report-research` 当前使用占位输入 `<CATEGORY_JSON>`、`<COMPARE_JSON>`、`<SELLER_JSON>`，后续可让 Agent 从 `keepa://research/{cache_key}` 或 `keepa://graphs/{root}` 自动填充候选输入。
- `tracking-audit` 仍是只读计划，不应静默升级为写入工具；若未来加入 tracking 写入 workflow，必须使用单独 profile 并强制人工确认。
- 下一步最适合继续完善：为 `workflow.plan` 增加 `inputs` / `artifacts` 字段和 `resource_templates` 建议，让 Agent 不需要从 CLI 字符串里推断中间产物路径。
