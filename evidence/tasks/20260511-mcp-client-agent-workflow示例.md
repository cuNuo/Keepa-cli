# MCP client Agent workflow 示例

## 前置说明

- 本轮目标是补一个可复制的 MCP client 示例，把 `workflow.plan -> resource_uri -> risk schema validation -> graph/brief/report` 串成外部 Agent 可直接参考的集成样例。
- 未访问真实 Keepa API，未消耗真实 token；示例全程使用 fixture 与同一 MCP stdio session 内的 cache/resource URI。
- 发现并修正 `kc --mcp` 入口原先会等待 stdin 关闭才输出的问题；现在逐行处理并 flush，真实 MCP client 可以按上一步 `cache_key` 动态发下一步请求。

## 已落地

1. MCP client 示例
   - 新增 `scripts/mcp_agent_workflow_example.py`。
   - 新增 `scripts/mcp_example_support.py`，抽出标准库 JSON-RPC stdio client、`keepa://research/{cache_key}` URI helper、graph count helper 与 `risk_taxonomy` schema 校验。
   - 三个示例统一支持 `--save-summary <path>`，便于 Agent pipeline 把集成摘要写入受控路径。
   - 仅依赖 Python 标准库，通过 `python -m keepa_cli --mcp` 启动本地 MCP stdio server。
   - 串联 `initialize`、收窄 `tools/list`、`keepa.workflow_plan`、`resources/read keepa://schema/risk-taxonomy`、`keepa.categories_products`、`keepa.products_compare`、`keepa.research_graph_merge`、`keepa.research_brief_export` 与 `keepa.reports_build`。
   - 使用 `keepa://research/{cache_key}` 与 `keepa://research/{cache_key}/graph` 连接前后步骤，不复制大 payload。
   - 在 client 侧校验 `risk_taxonomy.codes/items/severity/evidence_path` 是否符合 `keepa://schema/risk-taxonomy`。
   - 输出紧凑 JSON summary：tool names、cache/resource URI、风险校验结果、graph counts、brief one-line、report graph counts 与最终 budget ledger。

2. MCP stdio 真实客户端兼容性
   - 新增 `iter_mcp_stream`，保持一个 `AgentSession`，逐行处理 JSON-RPC 输入。
   - `cli.py --mcp` 改为逐行输出并 flush；批量 JSONL 输入仍兼容。

3. tracking-audit 示例
   - 新增 `scripts/mcp_tracking_audit_example.py`。
   - 使用 `tools/list toolset=tracking-readonly profile=tracking_readonly` 展示 MCP 只读工具面。
   - 用 `tracking_list.json` fixture 调用 `keepa.tracking_list`，再把 `keepa://research/{cache_key}` 传给 `keepa.tracking_get` 与 `keepa.audit_cost`，验证 resolver 能从上游 tracking list 推导 ASIN。
   - 尝试调用 `keepa.tracking_add` 并记录 `Unknown tool`，证明 MCP 未暴露 tracking 写路径。

4. report-research 示例
   - 新增 `scripts/mcp_report_research_example.py`。
   - 使用 `tools/list toolset=reports profile=offline_fixture_only` 展示纯本地 report 工具面。
   - 从 `tests/fixtures/agent_eval_products_compare_output.json` 合并 research graph，导出 brief，生成 browse snapshot 和 SVG figures，并用 `workflow_context.steps/outputs` 把 graph artifact 传给 `keepa.reports_build`。
   - 输出 graph counts、brief one-line、browse index 是否生成、SVG resource、report graph counts 与 0 token ledger。

5. browse snapshot 与 SVG figures
   - `browse.snapshot` 已增强为优先读取 raw product body；若没有 raw rows，则从 `research_graph` product nodes 提取 ASIN、title、brand，并在 HTML 与 `data.json` 中暴露 graph node/edge summary。
   - 新增 `keepa_cli/figures.py`，使用 Python 标准库生成统一 SVG，不引入绘图库依赖；面板包含产品指标对比、风险枚举频率、research graph 实体计数和时序信号摘要。
   - 新增 `figures.research` CLI/service 命令与 `keepa.figures_research` MCP reports tool；MCP text fallback 会通过 `mcp_resource_manifest` 暴露 `image/svg+xml` 的 `keepa://output/...` resource。
   - `keepa_cli/risk_schema.py` 已成为 MCP examples 与 Agent eval 共享的 risk schema helper，避免示例和评测逻辑漂移。

6. 测试与文档
   - 新增 `tests/test_mcp_client_example.py`，直接运行示例脚本并断言 workflow plan、resource URI、risk schema validation、graph、brief、report 与 ledger。
   - README / README.zh-CN / `docs/agent-contract.md` / `docs/architecture/mcp-agent-tools.md` 已增加示例入口。
   - 项目内 `.codex/skills/keepa-cli` 与 `.codex/skills/keepa-agent-research` 已同步示例命令。

## 已执行验证

- `.\.venv\Scripts\python.exe scripts\mcp_agent_workflow_example.py --json`：通过。
- `.\.venv\Scripts\python.exe scripts\mcp_tracking_audit_example.py --json`：通过。
- `.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json`：通过。
- `.\.venv\Scripts\python.exe -m keepa_cli --json figures research --input tests\fixtures\agent_eval_products_compare_output.json --out-dir %TEMP%\keepa-figures-smoke --title "Keepa Agent Research Smoke"`：通过，生成 SVG 与 source JSON。
- `.\.venv\Scripts\python.exe -m unittest tests.test_phase10_workflows tests.test_mcp_client_example tests.test_mcp -q`：通过，55 tests OK。
- `.\.venv\Scripts\python.exe -m unittest tests.test_mcp_client_example tests.test_mcp tests.test_agent_session tests.test_agent_eval_fixtures -q`：通过，50 tests OK。
- `.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py`：通过，29 specs OK。
- `.\.venv\Scripts\python.exe scripts\check_fixture_sync.py`：通过。
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`：通过，249 tests OK。
- `git diff --check`：通过。
- `.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过，相关 Hook 全部通过。
- `.\.venv\Scripts\python.exe -m keepa_cli --json doctor`：通过。
- `node .\bin\keepa-cli.js --json doctor`：通过。
- `node .\bin\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 通过。

## 风险与后续

- 示例刻意使用 fixture，适合 Agent 集成与 CI；切换到 live 前仍需读取 `workflow_policy.confirmation_policy` 并由用户确认高成本步骤。
- 当前风险校验是轻量 schema 子集校验，没有引入 `jsonschema` 依赖；如后续需要完整 JSON Schema draft 2020-12 校验，可作为可选 extras，而不应加入核心依赖。
- SVG 图表目前是静态多面板摘要，后续可继续补价格/排名真实历史折线、窗口特征置信区间和多产品标准化热图，但仍应保持单一 SVG 输出和 source JSON 可审计。
