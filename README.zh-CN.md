<p align="center">
  <h1 align="center">Keepa CLI</h1>
  <p align="center">面向 Agent 的 Keepa API 命令行工具，支持 JSON、stdio、MCP、fixture、token 预算和命令优先 TUI。</p>
</p>

<p align="center">
  <a href="./README.md">English</a>
  · <a href="#安装">安装</a>
  · <a href="#配置-keepa-token">配置 Token</a>
  · <a href="#tui">TUI</a>
  · <a href="#agent-模式">Agent 模式</a>
</p>

Keepa CLI 将 Keepa API 工作流封装为稳定、可审计、适合 Agent 和人类共同使用的命令行界面。默认离线优先：dry-run 和 fixture 不访问 Keepa，也不消耗 token。真实请求必须显式配置 Keepa token。

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
```

MCP 默认只返回紧凑的 `research` toolset，使用结构化 JSON 参数，不解析 CLI 字符串。`tools/list` 可传 `toolset=research/audit/reports/tracking-readonly/all` 控制上下文大小：research 覆盖产品、类目、Finder、Deals、Seller、榜单与 workflow plan；audit 覆盖 cost 与 cassette sanitize/promote；reports 覆盖本地报告和浏览快照；tracking 只暴露只读操作。Agent 结果会尽量提供统一 `research_graph`，工具 envelope 包含 `structuredContent`、JSON text fallback、`cache_key`、`cache_hit` 与 `budget_ledger`。

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
- 真实 Keepa smoke 使用 GitHub Secrets 中的 `KEEPA_API_KEY` 手动触发。
