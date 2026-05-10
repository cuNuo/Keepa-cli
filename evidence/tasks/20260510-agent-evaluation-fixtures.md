# Agent Evaluation Fixtures

## 任务目标

补充固定 Agent evaluation fixtures，用离线任务集验证最终 JSON 质量，而不是只验证命令成功。

## 背景与输入

- 用户提供本地真实响应：`evidence/runtime-logs/20260510-B0D8W1YVBX-full.json`。
- 本轮优先使用本地 runtime log，不请求真实 Keepa API。
- 原始 runtime log 仍保持未跟踪，不直接提交。

## 处理过程

1. 从本地 runtime log 派生稳定 fixture：
   - `tests/fixtures/product_B0D8W1YVBX_agent_eval.json`
   - `tests/fixtures/products_compare_agent_eval.json`
2. 同步复制到包内 fixture：
   - `keepa_cli/fixtures/product_B0D8W1YVBX_agent_eval.json`
   - `keepa_cli/fixtures/products_compare_agent_eval.json`
3. 新增四个固定评测任务：
   - `category_term_candidates.json`
   - `deal_compare_three_asins.json`
   - `offer_gap_decision.json`
   - `category_finder_scaffold.json`
4. 新增 `tests/test_agent_eval_fixtures.py`，按 spec 运行 `run_command` 并断言关键 JSON path：
   - category 候选与 next action
   - 三 ASIN deal rows 的价格、需求、内容和缺失数据
   - offers 缺口与补请求建议
   - Finder scaffold 的 selection 字段和 evidence index
5. 增加双份 fixture 同步断言，避免 `tests/fixtures` 与 `keepa_cli/fixtures` 漂移。

## 验证结果

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_agent_eval_fixtures -v
```

结果：2 tests passed。

待最终交付前继续运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
```

## 关联产物

- `tests/agent_eval_fixtures/*.json`
- `tests/test_agent_eval_fixtures.py`
- `tests/fixtures/product_B0D8W1YVBX_agent_eval.json`
- `tests/fixtures/products_compare_agent_eval.json`
- `keepa_cli/fixtures/product_B0D8W1YVBX_agent_eval.json`
- `keepa_cli/fixtures/products_compare_agent_eval.json`

## 风险与后续

- 派生 fixture 来自真实响应，但已作为测试 fixture 稳定化；不包含 API key。
- 当前任务集覆盖 P0 Agent 工作流，后续可加入 MCP `tools/call` 层面的评测 spec。
- 下一步最值得做 `risk_taxonomy` 与 `research_graph`，让这些 evaluation specs 能断言更强的 Agent 语义。

## 结论

Agent evaluation fixtures 已建立，可离线验证类目发现、产品对比、offers 决策和 Finder scaffold 的最终 JSON 质量。
