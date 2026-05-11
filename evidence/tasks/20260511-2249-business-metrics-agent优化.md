# business metrics 与 Agent MCP 业务入口优化

## 前置说明

- 时间：2026-05-11 22:49
- 范围：Keepa-cli 本地业务指标、MCP tools/resources/prompts、workflow plan、Agent profile 生成器、报告 brief 顺序。
- 输入来源：用户要求继续吸收 `D:\github\keepa_MCP` 的业务场景优势，并明确对外表述使用 Agent 中性措辞。
- 假设：默认不访问真实 Keepa API；`monthlySold`、offer count、out-of-stock、price 等字段可能缺失，缺失时只能降低置信度，不能输出确定库存数量。

## 变更摘要

- 新增 `keepa_cli.metrics`，把 velocity、seller competition、inventory risk、cashflow proxy 公式集中到纯本地模块。
- 新增 `business.find-fast-movers`、`business.inventory-audit`、`business.market-opportunity`、`seller-metrics.summary`、`velocity.research`、`inventory.audit` 与 `agent.profile.generate` service 命令。
- 新增 CLI：`business find-fast-movers`、`business inventory-audit`、`business market-opportunity`、`business seller-metrics`、`business velocity`、`business inventory`、`business agent-profile`。
- 新增 MCP tools：`keepa.find_fast_movers`、`keepa.inventory_audit`、`keepa.market_opportunity`、`keepa.agent_profile_generate`；新增 `business` toolset，并接入 `offline_fixture_only` / `dry_run_default` profile。
- 新增 MCP prompts：`keepa.inventory_audit`、`keepa.velocity_research`、`keepa.market_opportunity`。
- 新增 resources：`keepa://guides/categories`、`keepa://guides/marketplaces`、`keepa://guides/agent-profile`。
- 扩展 `workflow.plan`：`inventory-audit`、`velocity-research`、`market-opportunity` 固定走 `business` + `offline_fixture_only`。
- `reports.build` markdown 改为 Brief 优先：先给 decision、risk、next action，再给 evidence table、figures 和 graph 明细。

## 公式与置信度

- 每个估算对象都带 `method`、`version`、`inputs`、`confidence`、`evidence_path`。
- `velocity` 优先使用 `monthlySold`；缺失时只把 sales rank drops 作为低置信 proxy。
- `seller_metrics` 优先使用 `totalOfferCount`，再降级到 FBA/FBM 或 seller id 样本下界。
- `inventory` 基于 out-of-stock percentage、seller count 与 velocity 估算缺货风险，不输出确定库存数量。
- `cashflow` 只输出 GMV proxy，明确排除成本、费率、广告、退款、税与账期。

## 验证

- `.\.venv\Scripts\python.exe -m py_compile keepa_cli\metrics.py keepa_cli\agent_profile.py keepa_cli\commands\business.py keepa_cli\cli_builders\business.py keepa_cli\service.py keepa_cli\agent\tools.py keepa_cli\agent\resources.py keepa_cli\agent\prompts.py keepa_cli\agent\workflow_resolver.py keepa_cli\workflows.py keepa_cli\cli.py keepa_cli\capabilities.py`
- `.\.venv\Scripts\python.exe -m unittest tests.test_business_metrics tests.test_phase10_workflows tests.test_mcp tests.test_schema_snapshot -v`

## 风险与后续

- 当前 inventory 仍是 risk proxy，不是真实库存估算；若后续接入 offer-level stock 字段，需要新增公式版本并保留替换策略。
- business alias 目前依赖既有产品证据；若用户只有关键词，仍应先走 category/product workflow 获取输入。
- schema snapshot 因 capabilities/resources/tools 扩展已同步重建，后续 contract 改动仍需同时跑 snapshot 测试。
