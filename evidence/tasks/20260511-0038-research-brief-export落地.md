# research brief export 落地

## 任务目标

- 继续按 MCP 调研结果逐项优化 Keepa-cli MCP。
- 本轮聚焦 `research_brief.export`，把多步调研 payload 或 merged graph 转成调研 Agent 可直接接入的机器可读 handoff。
- 保持 offline-first，不访问真实 Keepa API，不消耗真实 token。
- 遵守用户约束：skill 只更新项目内 `.codex/skills/`，不写全局 skill 路径。

## 已落地改动

1. 新增 `keepa_cli/research_brief.py`
   - 从本地 JSON 文件、inline payload 或 `research_graph` 提取 `decision_summary`、`risk_summary`、`entity_graph_summary`、`follow_up_plan`、`evidence_links`。
   - 输出 `view=research_brief_export` 与 `recommended_read_order`，便于下游调研 Agent 先读结论再按需回证据。

2. 新增 service / CLI / MCP 能力
   - service command：`research_brief.export`。
   - MCP tool：`keepa.research_brief_export`。
   - CLI：`kc --json research brief <input.json...> --title ... --out brief.json`。
   - capabilities schema version 更新到 `2026-05-11.3`。

3. 新增 MCP resource templates
   - `keepa://research/{cache_key}/brief`：同一 MCP session 内回读 `research_brief.export` 的完整 brief。
   - `keepa://research/{cache_key}/graph`：同一 MCP session 内回读 brief 的图谱摘要与输入摘要。

4. 新增 MCP profile gating
   - `tools/list` 支持 `profile=offline_fixture_only/dry_run_default/live_read_allowed/tracking_readonly/fixture_curation`。
   - tool schema 的 `x-keepa.active` 标记当前阶段是否允许该工具。
   - `tools/call` 参数带同一 `profile` 时，若工具不允许，会返回 `inactive_tool`，不进入 service 执行层。

5. 更新项目内 skill 与文档
   - `.codex/skills/keepa-agent-research/SKILL.md`
   - `.codex/skills/keepa-cli/SKILL.md`
   - `README.md`
   - `README.zh-CN.md`
   - `docs/agent-contract.md`
   - `docs/architecture/mcp-agent-tools.md`

6. 更新测试与 Agent eval
   - 新增 service 与 MCP session cache/resource 测试。
   - 新增 `tests/agent_eval_fixtures/research_brief_export.json`。
   - 新增 `tests/agent_eval_fixtures/mcp_profile_gating.json`。
   - 更新 `mcp_resource_templates_contract` 与 `agent_schema_snapshot`。
   - 修正 `research_context_policy_and_target` 的预算断言：policy/target/context query 都是本地零 token 命令，应为 `session_estimated=0`。

## 推荐调研 Agent 链路

`tools/list profile=offline_fixture_only` -> `keepa://context/policy` -> `keepa.resolve_research_target` -> `keepa.query_research_context` -> `tools/list profile=dry_run_default` -> `keepa.workflow_plan` -> 最小工具执行 -> `keepa.research_graph_merge` -> `keepa.research_brief_export` -> `keepa://research/{cache_key}/brief`

## 验证记录

- `.\.venv\Scripts\python.exe -m unittest tests.test_mcp tests.test_capabilities tests.test_service_commands tests.test_schema_snapshot -v`：49 tests OK。
- `.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py`：16 specs OK。
- `git diff --check`：通过。
- `.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过。
- `.\.venv\Scripts\python.exe -m keepa_cli --json research brief tests\fixtures\agent_eval_category_search_output.json tests\fixtures\agent_eval_seller_output.json --title "fixture research brief"`：通过。
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`：225 tests OK。

## 风险与后续

- `research_brief.export` 当前是本地抽取式摘要，不做 LLM 改写，不访问外部网页；优势是可复现，局限是不会主动补充缺失事实。
- resource `/brief` 与 `/graph` 依赖同一 MCP 进程内 `AgentSession` cache；跨进程持久化不是本轮目标。
- 下一项最佳实践建议：live -> sanitize/promote -> eval parity 一键链路，减少真实请求转换为回归资产时的人为漏项。
