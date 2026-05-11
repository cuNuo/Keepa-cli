# report SVG resource 与时序图增强

## 前置说明

- 本轮目标是让 `reports.build` 自动嵌入 SVG resource / Markdown image，新增 `keepa://research/{cache_key}/figures` MCP resource template，并继续细化 Agent 报告图表。
- 未访问真实 Keepa API，未消耗真实 token；预览和验证均使用本地 fixture 与 service envelope。
- 根据 nature-figure 的图表契约，本轮保持单 SVG + source JSON，优先表达证据逻辑与可审计性，不引入额外绘图库依赖。

## 已落地

1. report 自动嵌图
   - `reports.build` 的 markdown/json 输出默认本地生成并嵌入 `agent-research-summary.svg`。
   - 新增 `--figure` 复用已有 SVG/图片路径，新增 `--figures-dir` 控制自动图表目录，新增 `--no-figures` 关闭嵌图。
   - 有 `--out` 时图表生成在报告旁边；无 `--out` 时生成到系统临时目录，避免污染 fixture 目录。

2. MCP figures resource
   - 新增 `keepa://research/{cache_key}/figures` resource template。
   - 该 resource 从同一 MCP session cache 的 structured result 生成图表 manifest，不访问 Keepa API。
   - SVG 与 source JSON 仍通过 `keepa://output/...` 暴露，SVG MIME 为 `image/svg+xml`，便于 Agent 插入报告。

3. 时序图增强
   - `figures.research` 支持从 payload 直接生成图表，MCP resource 不需要临时输入文件。
   - SVG 面板调整为：产品指标对比、真实 price/rank/review history 折线、窗口变化热图、多 ASIN 标准化 small multiples、风险与 research graph 审计摘要。
   - source JSON 新增 `history_series`、`window_heatmap`、`small_multiples`，并保留 `data_basis` / source path，便于 Agent 审计。
   - 若输入只有 compare 摘要，没有 full Agent history，则图表自动降级并在面板中提示缺失历史点。

4. 文档与 skill
   - 更新 README / README.zh-CN、`docs/agent-contract.md`、`docs/architecture/mcp-agent-tools.md`。
   - 更新项目内 `.codex/skills/keepa-cli` 与 `.codex/skills/keepa-agent-research`，说明新 resource template 与 report 自动嵌图。
   - 更新 Agent schema snapshot 与生成文档。

## 预览产物

- compare fixture 预览：`evidence/runtime/figures-preview/agent-research-summary.svg`
- full Agent history 预览：`evidence/runtime/figures-preview-full/agent-research-summary.svg`
- full 预览 source summary：`product_count=1`、`history_series_count=4`、`window_heatmap_cell_count=35`、`small_multiple_count=1`

上述 runtime 产物仅用于本地查看，不提交仓库。

## 已执行验证

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`：250 tests OK。
- `.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py`：29 specs OK。
- `.\.venv\Scripts\python.exe scripts\check_fixture_sync.py`：OK。
- `git diff --check`：OK。
- `.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only`：OK。
- `.\.venv\Scripts\python.exe -m keepa_cli --json doctor`：OK。
- `node .\bin\keepa-cli.js --json doctor`：OK。
- `node .\bin\kc.js --json doctor`：OK。
- `npm pack --dry-run --json`：OK；prepack release gate OK。

## 风险与后续

- 当前 SVG 仍是标准库静态图，优势是零依赖和 MCP 友好；后续如需要出版级复杂统计样式，可考虑可选 extras，但不应进入核心依赖。
- 多 ASIN small multiples 在 compare 摘要下使用当前指标标准化；若要画多 ASIN 真实历史折线，需要 compare 命令保留每个 ASIN 的 bounded `history_summary.last_points`。
- 下一步最值得做：让 `mcp_report_research_example.py` 演示 `keepa://research/{cache_key}/figures` resource 链路，并在 Agent eval 中断言 Markdown report 中的 SVG 链接可读取。

## 2026-05-11 增量收口

### 前置说明

- 本次继续沿用 `nature-figure` 的图表契约，但保持核心包零新增绘图库依赖；SVG 仍由标准库生成，重点补齐科学图表基本结构。
- 未访问真实 Keepa API，未消耗 token；预览使用 `tests/fixtures/agent_eval_products_compare_output.json` 与本地 `evidence/runtime-logs/20260510-B0D8W1YVBX-full.json`。
- `evidence/runtime/` 下预览产物仅用于本地查看，不进入提交。

### 已落地

1. 独立 SVG 图表
   - `figures.research` 现在除兼容的 `agent-research-summary.svg` 外，还生成独立图：`product-metric-comparison.svg`、`history-lines.svg`、`window-change-heatmap.svg`、`small-multiples.svg`、`risk-graph-summary.svg`。
   - 每张图在 manifest 中记录 `kind`、`x_axis`、`y_axis`、`caption`、`source_data_path` 与 MCP `resource_uri`。
   - 图表补齐白底、标题、副标题、坐标轴、刻度、图注与轻量语义色。

2. Raw Keepa body 时序提取
   - `figures.research` 可直接识别根层 Keepa raw body 的 `products[].csv`，复用 `product_view` 的 csv 解析逻辑生成 `history_series` 和 `window_heatmap`。
   - `B0D8W1YVBX-full.json` 离线预览已能提取 `history_series_count=4`、`window_heatmap_cell_count=35`。

3. MCP / report 链路
   - `scripts/mcp_report_research_example.py` 显式演示 `keepa://research/{cache_key}/figures`，并读取其中 SVG resource。
   - `reports.build` 的 figure 条目新增 `resource_uri`，Markdown 中追加 `- MCP resource: ...`，Agent 可直接通过 `resources/read` 读取 SVG。
   - Agent/MCP 测试新增 report Markdown SVG resource 可读断言。

4. products.compare 与 token 等待
   - `products.compare` 新增 `--keep-history-points` / `keep_history_points`，可在每个 ASIN 行保留 bounded `history_summary.series.*.last_points`，默认关闭以避免上下文膨胀。
   - Keepa live JSON 请求遇到 429 且返回 `refillIn` 时会最多等待一次再重试，成功时记录 `token_bucket.waited_for_refill_ms`；等待上限为 60 秒，避免长时间挂起。

### 预览产物

- Report Markdown：`evidence/runtime/report-preview-20260511-full/b0d8w1yvbx-report.md`
- 历史折线：`evidence/runtime/report-preview-20260511-full/b0d8w1yvbx-report-figures/history-lines.svg`
- 窗口热图：`evidence/runtime/report-preview-20260511-full/b0d8w1yvbx-report-figures/window-change-heatmap.svg`
- 多 ASIN 标准化图：`evidence/runtime/report-preview-20260511/agent-report-figures/small-multiples.svg`

### 已执行验证

- `.\.venv\Scripts\python.exe -m unittest tests.test_phase10_workflows tests.test_mcp tests.test_service_commands tests.test_client -v`：83 tests OK。
- `.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py`：29 specs OK。
- `.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json`：OK，确认 `keepa://research/{cache_key}/figures` 可读 SVG。

### 后续建议

- 针对真实多 ASIN full response 沉淀一个离线 sanitized fixture，用于验证多 ASIN 真实历史 small multiples，而不只验证当前指标标准化。
- 为 `figures.research` 增加可选 `--figure-set history|compare|audit|all`，让 Agent 控制返回图数量，进一步降低上下文和报告噪声。
- 增加 SVG 视觉快照 smoke：检查每张图存在标题、轴标签、至少一个数据几何元素或明确空态，防止后续图形回退。
