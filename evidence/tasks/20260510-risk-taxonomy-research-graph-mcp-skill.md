# risk taxonomy、research graph 与 MCP 语义增强

## 前置假设

- 本轮只使用离线 fixture 与本地评测，不访问真实 Keepa API。
- `evidence/runtime-logs/` 包含本地真实响应数据，继续保持未跟踪，不纳入提交。
- 当前工作区已有其他未提交改动，本轮只追加 Agent/MCP 语义层、评测、文档与 skill。

## 完成内容

1. 在 `keepa_cli/product_view.py` 增加统一 `risk_taxonomy`。
   - 稳定枚举：`data_missing`、`price_unstable`、`rank_declining`、`low_review_count`、`offer_competition_high`、`buybox_missing`、`category_mismatch`。
   - 每个风险 item 包含 `severity`、`reason`、`evidence_path`，并可带 `metric` 与 `follow_up`。
   - `agent_brief` 与 `selection_signals` 复用 `risk_taxonomy.codes`，便于 Agent 批量筛选。

2. 在 `keepa_cli/product_view.py` 增加 `research_graph`。
   - 节点覆盖 `product`、`brand`、`manufacturer`、`category`、`seller`、`variation`。
   - 边覆盖 `made_by`、`manufactured_by`、`in_category`、`parent_of`、`buybox_sold_by`、`variation_of`、`has_variation`。
   - `products.compare` 顶层输出合并后的 graph，并补 `risk_summary`。

3. MCP 完善。
   - 新增 `keepa.products_compare` tool，映射 `products.compare`。
   - `keepa.products_get` 描述更新为包含 Agent 语义层。
   - MCP 测试新增产品对比语义质量断言。

4. Agent evaluation fixtures 增强。
   - spec runner 新增 `length_min` 与 `contains_any` 断言。
   - 固定任务开始断言 risk code、风险 item 数、图谱节点/边、compare 顶层风险汇总与合并图谱。

5. 文档与 skill。
   - 更新 `docs/architecture/mcp-agent-tools.md`、`docs/agent-contract.md`、README / README.zh-CN 与 schema 文档。
   - 更新 `.codex/skills/keepa-cli/SKILL.md`。
   - 新增 `.codex/skills/keepa-agent-research/SKILL.md`，用于 Agent-first 产品研究、MCP、风险枚举、图谱和 fixture 安全流程。

## 验证记录

已通过：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_mcp tests.test_capabilities tests.test_agent_eval_fixtures -v
```

待最终收口继续运行全量 unittest、`git diff --check` 与项目 hooks。

## 后续最适合方向

1. 做 cassette promotion workflow：真实响应 -> sanitize -> promote fixture -> 自动补 manifest。
2. 做 MCP toolset 过滤：`research`、`audit`、`reports`、`tracking-readonly`，降低工具污染。
3. 扩展 research_graph 到 seller/category/finder/deals 输出，形成跨命令统一实体图谱。
