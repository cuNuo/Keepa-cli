# Research graph merge、MCP resources 与 Agent eval 增强

## 任务目标

- 实现 `research_graph.merge`，把 category -> products/compare -> seller/deals 输出合并成单个研究图。
- 增加 MCP resources，暴露 schema、fixture manifest、cassette 指南和最近 evidence，降低 `tools/list` 上下文。
- 对大响应提供统一 chunk/output resource manifest，让 MCP text fallback 只返回摘要和资源引用。
- 扩展 Agent evaluation fixtures，断言 graph merge、risk taxonomy、next_actions 可执行性和长链路 budget ledger。

## 前置假设

- 本轮不访问真实 Keepa API，不消耗真实 token；所有验证使用 fixture、dry-run、临时目录和本地命令。
- 当前工作区已有前序 command family、cache、MCP toolset 与 cassette promote 改动；本轮只在其基础上增量完善，不回退无关改动。
- `evidence/runtime-logs/` 不提交；真实响应如需沉淀，必须通过 `cassettes promote` 脱敏成双份 fixture。

## 完成内容

1. Research graph merge。
   - `keepa_cli/research_graph.py` 增加 `merge_research_graphs()`、`extract_research_graphs()` 与 `graph_summary()`。
   - `service` 增加 `research_graph.merge` / `research-graph.merge` / `graph.merge`，支持文件输入、inline graph/payload 输入和 `--out`。
   - CLI 新增 `research-graph merge`，本地合并图谱，不访问 Keepa。
   - 合并图会去重节点/边，增加 `research_graph` root 节点和 `includes_graph` 边，并保留 `sources`。

2. MCP resources 与 chunk manifest。
   - 新增 `keepa_cli/agent/resources.py`。
   - 静态 resources：`keepa://schema/products-agent-view`、`keepa://fixtures/manifest`、`keepa://guides/cassette-promotion`、`keepa://evidence/recent`。
   - 动态 resources：`keepa://chunk/...` 与 `keepa://output/...`，读取限制在项目根或系统临时目录下。
   - `agent/mcp.py` 支持 `resources/list`、`resources/read`。
   - `tools/call` 保留完整 `structuredContent`，但 text fallback 会压缩产品/compare/graph 数据，并附 `mcp_resource_manifest`。
   - 修正 resources 默认根为包所在项目根，避免从其他 cwd 启动 MCP 时找不到 docs/evidence。

3. MCP tool 与 capabilities。
   - 新增 `keepa.research_graph_merge`。
   - 将本地 scaffold `keepa.categories_finder_selection` 暴露到 `research` toolset。
   - `products_get` / `products_compare` MCP schema 支持 `chunks_dir`。
   - capabilities schema 升至 `2026-05-10.14`，并暴露 MCP resources。

4. Agent evaluation。
   - `scripts/check_agent_eval_fixtures.py` 支持 MCP 与 session spec、`$json` 路径解析、`not_contains`、`next_actions_executable`。
   - 新增/增强 specs：MCP resources contract、MCP chunk resource manifest、research graph merge、session budget ledger。
   - 对 category/search/finder/offers specs 增加 next_actions 可执行性断言。
   - schema snapshot 纳入 `research_graph.merge`、`mcp_resources_list`、`mcp_chunk_products_get`。

5. 文档与 companion skill。
   - README / README.zh-CN 增加 `research-graph merge`、MCP resources、chunk manifest 说明。
   - `docs/agent-contract.md` 与 `docs/architecture/mcp-agent-tools.md` 同步 MCP resources、merge tool、eval 门禁。
   - `.codex/skills/keepa-agent-research` 与 `.codex/skills/keepa-cli` 增加 graph merge、resources 与 chunk fallback 使用规则。

## 验证记录

已通过：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
.\.venv\Scripts\python.exe scripts\check_fixture_sync.py
.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
node .\bin\keepa-cli.js --json doctor
node .\bin\kc.js --json doctor
```

行为 smoke：

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json research-graph merge tests\fixtures\agent_eval_category_search_output.json tests\fixtures\agent_eval_products_compare_output.json tests\fixtures\agent_eval_seller_output.json --root agent_selection_research
```

该 smoke 返回 `node_count=19`、`edge_count=24`，`entity_counts` 覆盖 `category/product/seller/search_term/research_graph`，确认 category、compare 与 seller 图谱已合并。

## 风险与边界

- 未执行真实 Keepa 请求；真实 live parity 仍需低成本请求后通过 cassette promote 固化。
- 2026-05-10 后续迭代已补 `resources/templates/list`，客户端可发现 schema、fixture、chunk、output URI 模板；仍未提供按 cache_key/ASIN 的查询模板。
- 2026-05-10 后续迭代已补 `source_weight/confidence` 与 duplicate/orphan/conflict diagnostics；仍未提供完整 graph diff 视图。

## 后续最适合方向

1. 继续扩展 MCP resource templates：按 `cache_key`、ASIN、graph root 或 evidence logical path 查询资源，减少客户端拼 URI。
2. 给 `research_graph.merge` 增加 graph diff 与 source preference，帮助 Agent 判断多来源不一致。
3. 增加 reports/tracking-readonly 的 Agent eval specs，覆盖本地 report 输出、只读 tracking 与 ledger。
4. 让 reports builder 可直接消费 merged graph，输出 product/category/seller/deal 关系报告。
5. 增加 replay/live parity 测试流程：低成本 live -> sanitize/promote -> eval fixture 对比。

## 结论

本轮完成用户要求的 graph merge、MCP resources、大响应 chunk manifest 和 Agent eval 增强，并通过全量离线验证。当前 MCP/Agent 层已能用结构化工具、资源引用、预算账本和语义图谱支持更长的 Agent 选品研究链路。
