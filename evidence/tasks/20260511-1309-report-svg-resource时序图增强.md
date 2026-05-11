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

## 2026-05-11 视觉与真实 full history fixture 收口

### 前置说明

- 本轮继续按 `nature-figure` 的图表契约处理，但仍保持核心包零新增绘图库依赖；SVG 由标准库生成，重点修正可读性、布局与 Agent 报告插图稳定性。
- 未访问真实 Keepa API，未消耗 token；真实 full history 回归资产来自本地已有 runtime full 响应，并经过脱敏与 token/account 运行字段清理后写入固定 fixture。
- 视觉检查使用浏览器内联 SVG 渲染；`evidence/runtime/` 下预览和截图仅用于本地 QA，不提交仓库。

### 已落地

1. SVG 视觉与字体
   - `figures.research` schema 升至 `2026-05-11.4`。
   - SVG 统一字体族为 `'Times New Roman', 'SimSun', '宋体', serif`，英文优先 Times New Roman，中文可走宋体/SimSun。
   - `history-lines.svg` 从单 ASIN 多线图升级为“每个指标一行、不同 ASIN 颜色对比”的 normalized history layout，rank 反向处理后向上代表更好。
   - `small-multiples.svg` 改为共享 metric 图例、每个 ASIN 单独卡片、卡片高度自适应且设上限，避免底部截断和大片空白。
  - 总览图高度从 1120 调整到 1260，并拉开 history / small multiples / audit 面板间距；总览内 history 面板使用紧凑模式，独立图保留完整 x 轴说明，避免报告预览互相挤压。

2. 多 ASIN 真实 full history fixture
   - 新增脱敏 raw full history fixture：`tests/fixtures/products_multi_asin_full_history_sanitized.json` 与 `keepa_cli/fixtures/products_multi_asin_full_history_sanitized.json`。
   - 来源为本地 runtime full 响应 `B0D8W1YVBX` 与 `B0F7XPYCSJ`，保留 `products[].csv`、stats 和产品字段；清理 `refillIn/refillRate/tokenFlowReduction/tokensConsumed/tokensLeft/timestamp` 等账户/运行字段。
   - 新增 Agent-safe compare fixture：`tests/fixtures/agent_eval_products_compare_real_full_history_output.json` 与 `keepa_cli/fixtures/agent_eval_products_compare_real_full_history_output.json`，由 `products.compare --keep-history-points --history-limit 80` 从上述 raw fixture 生成。
   - 保留三 ASIN `agent_eval_products_compare_history_output.json`，用于 Agent deal compare 与多 ASIN compare 输出回归；真实 full history 曲线回归使用新增 raw full fixture 链路。

3. 测试与 MCP resource
   - `tests/test_phase10_workflows.py` 新增真实 full history figure 回归，断言中文标题、宋体、真实 ASIN、history series 与 bounded history small multiples。
   - `tests/test_service_commands.py` 新增 `products.compare` 从真实 full history fixture 保留多 ASIN bounded history points 的断言。
   - `tests/test_mcp.py` 的 `keepa://research/{cache_key}/figures` resource 测试切到真实 full history fixture，并断言 small-multiples SVG resource、`image/svg+xml`、真实 ASIN 与中文字体。

### 视觉 QA

- 最终预览目录：`evidence/runtime/figures-visual-check-20260511-final/`
- 关键 SVG：`small-multiples.svg`、`history-lines.svg`、`agent-research-summary.svg`。
- 浏览器内联 SVG 检查结果：三张图均可渲染；`small-multiples.svg` 与 `history-lines.svg` 尺寸均为 1160 x 760；总览图按比例渲染；文本几何检查 `outsideCount=0`。
- Playwright 截图：`evidence/runtime/figures-visual-check-20260511-final/keepa-svg-visual-check-final.png`（本地 QA 产物，不纳入提交）。

### 已执行验证

- `.\.venv\Scripts\python.exe -m unittest tests.test_phase10_workflows tests.test_service_commands tests.test_mcp -v`：75 tests OK。

### 风险与后续

- 当前 SVG 是静态科学图表，不做交互；MCP resource 已返回 `image/svg+xml`，但简易本地 HTTP 预览需要正确 MIME 才能用 `<img>` 直接显示。
- 真实 full history fixture 目前覆盖 2 个 ASIN；后续如果需要更接近选品场景，可在用户批准真实请求后再补 3-5 个不同类目的 sanitized full history fixture。
- 下一步最适合完善：为 `figures.research` 增加 `figure_set` / `--figure-set`，让 Agent 只请求 `history`、`compare` 或 `audit` 图组，减少报告噪声和 resource manifest 大小。

## 2026-05-11 figure_set 图表组收口

### 前置说明

- 本轮目标是把上一节后续建议落地为 Agent/MCP 可执行契约：让报告、CLI 与 MCP resource 都能按图表组返回，减少上下文噪声。
- 未访问真实 Keepa API，未消耗 token；验证输入使用固定 fixture `tests/fixtures/agent_eval_products_compare_real_full_history_output.json` 与 `products_multi_asin_full_history_sanitized.json`。
- 按 `nature-figure` 的图表契约继续保持白底、坐标轴、标题、刻度、图注和 source JSON；未新增绘图库依赖。

### 已落地

1. `figures.research` 图表组
   - 新增 `figure_set=all|history|compare|audit`。
   - `all` 保持兼容：输出 `agent-research-summary.svg` 与全部独立 SVG。
   - `history` 只输出 `history-lines.svg` 与 `window-change-heatmap.svg`。
   - `compare` 只输出 `product-metric-comparison.svg` 与 `small-multiples.svg`。
   - `audit` 只输出 `risk-graph-summary.svg`。
   - 返回体新增 `figure_set` 与 `available_figure_sets`，便于 Agent 在 report pipeline 中审计实际输出范围。

2. CLI / report / MCP 同步
   - `figures research` 新增 `--figure-set`。
   - `reports build` 新增 `--figure-set`，自动嵌图可按图表组收窄。
   - MCP tools `keepa.figures_research` 与 `keepa.reports_build` schema 暴露同一 enum。
   - MCP resource template 新增 `keepa://research/{cache_key}/figures/{figure_set}`；旧的 `keepa://research/{cache_key}/figures` 继续等价于 `all`。

3. Agent 文档与 skill
   - 更新 README、`docs/agent-contract.md`、`docs/architecture/mcp-agent-tools.md`。
   - 更新 `.codex/skills/keepa-cli` 与 `.codex/skills/keepa-agent-research`，要求 Agent 优先读取 scoped figure resource，而不是一次加载所有图。
   - `tests/test_mcp.py` 断言 `resources/templates/list` 暴露 scoped template，并验证 `keepa://research/{cache_key}/figures/history` 只返回 history 图组。

### 预览产物

- 本地 scoped 预览目录：`evidence/runtime/figures-figure-set-check/`。
- 生成结果：`history-lines.svg`、`window-change-heatmap.svg`、`agent-research-summary.source.json`。
- 该目录仅用于本地 QA，不纳入提交。

### 已执行验证

- `.\.venv\Scripts\python.exe -m unittest tests.test_phase10_workflows tests.test_mcp -v`：58 tests OK。
- `.\.venv\Scripts\python.exe -m compileall -q keepa_cli scripts`：OK。
- `.\.venv\Scripts\python.exe scripts\check_fixture_sync.py`：OK。
- `.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py`：29 specs OK。
- `git diff --check`：OK。
- `.\.venv\Scripts\python.exe hooks\run_relevant_hooks.py --changed-only`：OK。
- `.\.venv\Scripts\python.exe -m keepa_cli --json doctor`：OK。

### 风险与后续

- 旧客户端继续使用 `all` 不破坏兼容；新 Agent 应按报告段落选择 `history`、`compare` 或 `audit`，避免 resource manifest 膨胀。
- scoped set 当前仍复用同一个 source JSON，便于审计；如果后续 source JSON 过大，可进一步按 figure_set 分片为 `source.history.json` 等。
- 下一步最适合完善：把 SVG 视觉 smoke 做成独立脚本，检查每个 figure set 至少有标题、轴标签、图注和非空数据几何或明确空态，并将 report Markdown 中的 scoped SVG resource 纳入 Agent eval。
