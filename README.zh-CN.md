<p align="center">
  <h1 align="center">Keepa CLI</h1>
  <p align="center">面向 Agent 的 Keepa API CLI，用于商品研究、安全自动化和 MCP 原生工作流。</p>
</p>

<p align="center">
  <a href="https://github.com/cuNuo/Keepa-cli/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cuNuo/Keepa-cli/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776ab"></a>
  <a href="https://www.npmjs.com/package/@cunuo/keepa-cli"><img alt="npm" src="https://img.shields.io/badge/npm-%40cunuo%2Fkeepa--cli-cb3837"></a>
  <a href="https://cunuo.github.io/Keepa-cli/"><img alt="Docs" src="https://img.shields.io/badge/docs-pages-2563eb"></a>
  <a href="#agent-模式"><img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-6d28d9"></a>
  <a href="https://zread.ai/cuNuo/Keepa-cli"><img alt="zread" src="https://img.shields.io/badge/docs-zread-14b8a6"></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-111827"></a>
</p>

<p align="center">
  <a href="./README.md">English</a>
  · <a href="#安装">安装</a>
  · <a href="#配置-keepa-token">配置 Token</a>
  · <a href="#tui">TUI</a>
  · <a href="#agent-模式">Agent 模式</a>
</p>

Keepa CLI 将 Keepa API 工作流封装为稳定、可审计、适合 Agent 和人类共同使用的命令行界面。默认离线优先：dry-run 和 fixture 不访问 Keepa，也不消耗 token。真实请求必须显式配置 Keepa token。

适合用于可复现的 Amazon 商品研究、类目发现、Deal 对比、Seller 检查、Tracking 只读审计、本地报告，以及需要明确 token 成本和 evidence provenance 的 Agent pipeline。

## 能力概览

- `keepa-cli` 与 `kc` 双入口等价。
- JSON、stdio JSON Lines 与 MCP stdio 三种 Agent 入口共享同一 command service。
- Finder、Deals、Seller、Best Sellers、Top Sellers、Tracking 与 webhook 命令族。
- 本地 Web 浏览快照、ASIN 批处理、工作流模板、Markdown/JSON/CSV 报告。
- SQLite 响应缓存、cache explain 与成本审计，便于上线前确认 provenance 和 token 预算。
- 发布门禁包含测试、fixture 同步、Python/Node smoke、npm pack dry-run 和跨平台安装验证。

## 安装

本地开发：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\kc.exe --json doctor
```

npm wrapper 目标安装：

```powershell
npm install -g @cunuo/keepa-cli
kc --json doctor
```

如果需要指定 Python：

```powershell
$env:KEEPA_CLI_PYTHON="D:\github\Keepa-cli\.venv\Scripts\python.exe"
kc --json doctor
```

## 配置 Keepa Token

写入本地配置文件，CLI 输出会自动打码。保存前会先做本地格式校验：Keepa access key 必须是 64 个可见 ASCII 字符。

```powershell
kc --json config set-token YOUR_KEEPA_64_CHARACTER_ACCESS_KEY
kc --json doctor
```

默认配置路径：

- Windows：`%APPDATA%\keepa-cli\config.toml`
- macOS / Linux：`~/.config/keepa-cli/config.toml`

指定配置文件：

```powershell
kc --json config set-token YOUR_KEEPA_TOKEN --path .\config.local.toml
$env:KEEPA_CLI_CONFIG=(Resolve-Path .\config.local.toml)
kc --json doctor
```

环境变量优先级高于配置文件：

```powershell
$env:KEEPA_API_KEY="YOUR_KEEPA_TOKEN"
kc --json doctor
```

高订阅可调大单次请求 token 预算提示：

```powershell
kc --json config set-max-tokens 250
```

## 语言

默认界面语言为英文。切换中文：

```powershell
kc --json config set-language zh
```

切回英文：

```powershell
kc --json config set-language en
```

## 快速使用

fixture 命令不会消耗真实 token：

```powershell
kc --json products get B001GZ6QEC --domain US --history 0 --fixture product_B001GZ6QEC.json
kc --json products by-code 9780786222728 --domain US --code-limit 5 --dry-run
kc --json products summary B0D8W1YVBX --domain US --fixture product_agent_view_B0TEST.json
kc --json history trend B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json
kc --json tokens status --fixture token_status.json
```

高成本请求先 dry-run：

```powershell
kc --json bestsellers get 172282 --domain US --dry-run
kc --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
```

## 本地工作流

生成离线批处理计划、报告和本地 HTML 浏览页面：

```powershell
kc --json batch asins .\asins.txt --domain US --dry-run --out .\batch.json
kc --json reports build --input .\batch.json --format markdown --out .\report.md
kc --json browse snapshot --input .\batch.json --out-dir .\keepa-browse
```

查看内置模板：

```powershell
kc --json templates list
kc --json templates show finder-basic --out .\finder-basic.json
```

上线前解释缓存来源并估算 token 成本：

```powershell
kc --json cache explain --input .\batch.json --command products.get
kc --json cache explain-key --endpoint /product --param domain=1 --param asin=B001GZ6QEC
kc --json cache stats
kc --json cache inspect sqlite:<cache-key>
kc --json cache prune-expired --dry-run
kc --json cache clear --dry-run
kc --json audit cost products.get --param asin=B001GZ6QEC
```

live GET JSON 响应默认按配置里的 `cache_ttl_seconds` 写入 SQLite。dry-run、fixture、binary、POST 与禁用缓存的请求不会持久化。审计时可用 `--cache-path` 或 `KEEPA_CLI_CACHE_PATH` 覆盖缓存文件；可缓存 live 命令也支持 `--cache-ttl <秒>` 与 `--no-cache`，环境变量回退仍是 `KEEPA_CLI_CACHE_TTL_SECONDS` 与 `KEEPA_CLI_NO_CACHE=1`。`cache explain-key` 可按 method、endpoint 与脱敏后的请求参数反查确定性的 SQLite cache key；release gate 会运行 `scripts/check_live_cache_options.py`，防止新增可缓存 live CLI 命令漏掉显式缓存控制。

Tracking 与 webhook 示例默认 dry-run：

```powershell
kc --json tracking add --tracking-file .\tracking.json --dry-run
kc --json tracking webhook https://example.invalid/keepa --dry-run
```

## TUI

启动命令优先的终端界面：

```powershell
kc
```

TUI 采用 Codex/zread 风格：

- `kc ›` 始终作为底部 composer。
- 输入 `/` 后出现 slash 补全，可用方向键选择。
- 底部状态栏持续显示认证、domain、语言、预算和 schema。
- 配置入口保持简洁：`/token <64字符 Keepa key>`、`/max-tokens 250`、`/language zh`。
- 输出使用普通终端文本，摘要和完整 JSON envelope 都可直接选中复制。

强制旧版 slash TUI：

```powershell
kc tui --classic
```

## Agent 模式

```powershell
kc --json capabilities
kc --json domains list
'{"id":"1","method":"doctor","params":{}}' | kc --stdio
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | kc --mcp
'{"jsonrpc":"2.0","id":2,"method":"resources/list","params":{}}' | kc --mcp
'{"jsonrpc":"2.0","id":3,"method":"resources/templates/list","params":{}}' | kc --mcp
'{"jsonrpc":"2.0","id":4,"method":"prompts/list","params":{}}' | kc --mcp
```

MCP 默认只返回紧凑的 `research` toolset，使用结构化 JSON 参数，不解析 CLI 字符串。`tools/list` 可传 `toolset=research/docs/audit/reports/tracking-readonly/all` 控制上下文大小；`profile` 可按会话阶段标记 inactive tools（`offline_fixture_only`、`dry_run_default`、`live_read_allowed`、`tracking_readonly`、`fixture_curation`），被 profile 禁用的 `tools/call` 会在 service 执行前返回 `inactive_tool`。research 覆盖产品、类目、本地 Finder scaffold、Finder、Deals、Seller、榜单、workflow plan、docs index/read、`keepa.research_graph_merge` 与 `keepa.research_brief_export`；audit 覆盖 cost、cassette sanitize/promote 与 `keepa.cassettes_promote_and_verify`；reports 覆盖图谱合并、本地报告、浏览快照与 brief export；tracking 覆盖只读 tracking 与 cost audit。Agent 结果会尽量提供统一 `research_graph`，工具 envelope 包含 `structuredContent`、JSON text fallback、`cache_key`、`cache_hit` 与 `budget_ledger`。

MCP resources 用于减少 `tools/list` 上下文：`keepa://context/policy`、`keepa://schema/products-agent-view`、`keepa://fixtures/manifest`、`keepa://guides/cassette-promotion`、`keepa://evidence/recent`、`keepa://tools/index`、`keepa://prompts/index`、`keepa://zread/wiki/current`、`keepa://zread/wiki/toc`、`keepa://zread/wiki/pages`。`resources/templates/list` 会暴露 `keepa://schema/{name}`、`keepa://fixtures/{name}`、`keepa://cache-key/{command}/{encoded_params}`、`keepa://workflow/{encoded_params}/policy`、`keepa://research/{cache_key}`、`keepa://research/{cache_key}/brief`、`keepa://research/{cache_key}/graph`、`keepa://graphs/{root}`、`keepa://toolsets/{toolset}`、`keepa://tools/{name}`、`keepa://prompts/{name}`、`keepa://asin/{asin}/fixture`、`keepa://evidence/{encoded_logical_path}`、`keepa://zread/wiki/page/{slug_or_file}`、`keepa://chunk/{encoded_path}`、`keepa://output/{encoded_path}`，让 Agent 能发现 URI 形状而不是硬编码。`keepa://workflow/{encoded_params}/policy` 可从 base64url JSON 计划参数读取紧凑的 `workflow_policy` 和步骤摘要；`keepa://research/{cache_key}` 审计同一 MCP session 内缓存结果；`keepa://research/{cache_key}/brief` 回读已导出的 brief；`keepa://graphs/{root}` 从 session cache 和本地 fixture 查研究图来源。大响应仍完整保留在 `structuredContent`，text fallback 只返回摘要和 `mcp_resource_manifest`，其中 `keepa://chunk/...` / `keepa://output/...` 可按需读取具体分块。MCP prompts 提供 product research、category research、deal compare 与 project onboarding 起手式。

跨命令研究图可本地合并，不访问 Keepa：

```powershell
kc --json research-graph merge .\category.json .\compare.json .\seller.json --root agent_selection_research --out .\research-graph.json
```

合并结果会给出 `source_weight`、重复节点、孤立节点、label/type 冲突诊断、`diff` 摘要和可选 `--prefer-source` 冲突解析，便于 Agent 在多来源结果不一致时先审计再写报告。`reports build` 可以直接读取 merged graph JSON，并在 Markdown 中生成实体关系报告，或在 JSON 输出中写入 `research_graph_report`。

`workflow plan` 现在会同时输出 `workflow_policy`，包含推荐 MCP `toolset`、会话 `profile`、allowed/inactive tools、profile switch points、确认策略、缓存建议和预算账本种子。支持 `category-research`、`product-research`、`report-research` 与 `tracking-audit`；其中 `report-research` 只走本地 reports toolset，`tracking-audit` 只走 tracking-readonly toolset。Agent 应先按 `workflow_policy.tool_discovery` 收窄 `tools/list`，再根据 `profile_switch_points` 逐步切换 profile；高成本步骤只在用户确认后追加 `yes=true`。

## zread 文档

稳定公开文档入口：[GitHub Pages](https://cunuo.github.io/Keepa-cli/)。生成式架构 wiki 入口：[zread](https://zread.ai/cuNuo/Keepa-cli)，仓库内同时保留 `.zread/wiki/` 快照。

打开本地浏览页面：

```powershell
zread browse
```

Agent 和脚本接入时使用 stdio 模式：

```powershell
zread browse --stdio
```

当前本地快照索引为 [.zread/wiki/current](.zread/wiki/current) 与 [.zread/wiki/versions/2026-05-10-215740/wiki.json](.zread/wiki/versions/2026-05-10-215740/wiki.json)。Agent 可通过 `keepa://zread/wiki/current`、`keepa://zread/wiki/toc` 与 `keepa://zread/wiki/page/{slug_or_file}` 读取同一份快照。架构大改后可重新生成：

```powershell
zread generate -y --stdio --draft clear --skip-failed
```

## 开发

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
.\.venv\Scripts\python.exe scripts\install_verify.py --skip-npm-pack
git diff --check
```

## 安全

- 不提交 Keepa API key、`.env`、本地缓存或未脱敏 cassette。
- 输出会打码 `key`、`api_key`、`apikey`、`token`、`authorization`。
- 真实响应先用 `kc --json cassettes promote live.json --name fixture_name` 脱敏并同步写入双份 fixture，同时更新 `evidence/manifest.csv`。
- 把真实样本转成回归资产时，优先用 `kc --json cassettes promote-and-verify live.json --name fixture_name --run-eval`，一次完成脱敏提升、fixture parity 检查和可选 Agent eval。
- 真实 Keepa smoke 使用 GitHub Secrets 中的 `KEEPA_API_KEY` 手动触发。
