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
