<p align="center">
  <h1 align="center">Keepa CLI</h1>
  <p align="center">面向 Agent 的 Keepa API 命令行工具，支持 JSON、stdio、fixture、token 预算和现代 Textual TUI。</p>
</p>

<p align="center">
  <a href="./README.md">English</a>
  · <a href="#安装">安装</a>
  · <a href="#配置-keepa-token">配置 Token</a>
  · <a href="#tui">TUI</a>
  · <a href="#agent-模式">Agent 模式</a>
</p>

Keepa CLI 将 Keepa API 工作流封装为稳定、可审计、适合 Agent 和人类共同使用的命令行界面。默认离线优先：dry-run 和 fixture 不访问 Keepa，也不消耗 token。真实请求必须显式配置 Keepa token。

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
kc --json history trend B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json
kc --json tokens status --fixture token_status.json
```

高成本请求先 dry-run：

```powershell
kc --json bestsellers get 172282 --domain US --dry-run
kc --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
```

## TUI

启动现代终端工作台：

```powershell
kc
```

TUI 包含：

- 启动后默认聚焦命令输入框。
- 输入 `/` 时弹出命令建议。
- 认证状态、默认 domain 和单次 token 预算状态。
- token 与预算只在配置不完整时占用输入区。
- 可选中的 JSON 输出区域，便于复制完整 envelope。

强制旧版 slash TUI：

```powershell
kc tui --classic
```

## Agent 模式

```powershell
kc --json capabilities
kc --json domains list
'{"id":"1","method":"doctor","params":{}}' | kc --stdio
```

## 开发

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
git diff --check
```

## 安全

- 不提交 Keepa API key、`.env`、本地缓存或未脱敏 cassette。
- 输出会打码 `key`、`api_key`、`apikey`、`token`、`authorization`。
- 真实 Keepa smoke 使用 GitHub Secrets 中的 `KEEPA_API_KEY` 手动触发。
