# Keepa CLI 调研与实现方案

本仓库用于沉淀基于 Keepa API 的 Agent-first CLI 程序设计、实现计划与后续代码。最终目标是把 Keepa 能力封装成后续 Agent 可稳定调用的工具层，同时提供人类友好的交互界面。

本项目按开源项目维护，当前采用 MIT License。发布目标包括 Python 可编辑安装和 npm 全局安装；npm 包只提供 Node.js bin wrapper，业务逻辑仍在 Python `keepa_cli` 包内。

当前已完成调研报告：

- [Keepa CLI 实现调研与落地报告](docs/reports/2026-05-09-keepa-cli-implementation-report.md)
- [Keepa CLI 功能完善与完整开发路线](docs/roadmaps/2026-05-09-keepa-cli-development-roadmap.md)
- [Keepa CLI Agent 协议契约](docs/agent-contract.md)
- [Keepa 官方 API 约束摘记](docs/keepa-official-api-notes.md)
- [service.py / cli.py 拆分计划](docs/architecture/service-cli-split-plan.md)
- [贡献指南](CONTRIBUTING.md)
- [安全说明](SECURITY.md)
- [变更记录](CHANGELOG.md)

## 当前 MVP 状态

已落地 Phase 0 到 Phase 5 的最小可运行骨架：

- Python 包 `keepa_cli`
- 双入口声明：`keepa-cli` 与 `kc`
- `python -m keepa_cli`
- `--json doctor`
- `--json config show`
- `--json config init --dry-run`
- `--json domains list`
- `--json request get/post ... --dry-run`
- `--json products get/search ... --fixture ...`
- `--json categories get/search ... --fixture ...`
- `--json history export/trend ... --fixture ...`
- `--json finder query --selection-file ... --dry-run`
- `--json deals query --selection-file ... --fixture ... --out ...`
- `--json sellers get ... --fixture ...`
- `--json bestsellers get ... --dry-run`
- `--json topsellers list ... --fixture ... --out ...`
- `--json tokens status ... --fixture ...`
- `--json graphs image ... --dry-run`
- `--json lightningdeals list ... --dry-run`
- `--json tracking list/get/list-names ... --dry-run`
- `--json tracking add/remove/remove-all/webhook ... --dry-run`，真实写类请求必须 `--yes`
- `--json capabilities`
- `--stdio` JSON Lines 协议
- 标准库 TUI 工作台骨架：默认执行 `kc` / `keepa-cli` 进入 slash 命令界面
- JSON success/error envelope
- Keepa domain 归一化
- token 预算器
- request client dry-run、fixture/offline、gzip 解码、429/5xx 信息流测试
- Agent schema snapshot 测试
- record/replay transport，供未来真实 live smoke 录制后离线回放
- npm bin wrapper：`keepa-cli` 与 `kc`
- 凭据打码
- 标准库 `unittest` 测试

命令入口约定：

- `keepa-cli` 和 `kc` 都必须能完整调用 CLI 的所有能力。
- Agent 适配是硬门槛：`--json`、`--stdio`、结构化错误、token 预算、fixture/offline、凭据打码都必须优先稳定。
- 默认执行任一入口都进入人类友好的交互界面，但交互界面必须复用同一套 Agent-safe command service。
- 所有能力必须同时支持 `keepa-cli` 和 `kc` 两个入口。

安全约定：

- 不提交 Keepa API key、`.env`、本地缓存或临时浏览器产物。
- 后续如需 GitHub Actions 调用真实 Keepa API，使用 GitHub Secrets 保存 `KEEPA_API_KEY`。

## 本地开发

必须使用项目本地虚拟环境，不要在基础环境安装依赖：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

如需验证 console script，先安装到本项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\keepa-cli.exe --json doctor
.\.venv\Scripts\kc.exe --json doctor
.\.venv\Scripts\kc.exe --json config show
.\.venv\Scripts\kc.exe --json products get B001GZ6QEC --domain US --history 0 --fixture product_B001GZ6QEC.json
.\.venv\Scripts\kc.exe --json categories search "home kitchen" --domain US --fixture category_search_home.json
.\.venv\Scripts\kc.exe --json history export B001GZ6QEC --domain US --series amazon,new --format json --fixture product_history_B001GZ6QEC.json
.\.venv\Scripts\kc.exe --json history trend B001GZ6QEC --domain US --series amazon --window-days 30 --fixture product_history_B001GZ6QEC.json
.\.venv\Scripts\kc.exe --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
.\.venv\Scripts\kc.exe --json deals query --selection-file keepa_cli/fixtures/deals_selection.json --domain US --fixture deals_home.json --out deals.json
.\.venv\Scripts\kc.exe --json sellers get A2L77EE7U53NWQ --domain US --storefront --fixture seller_A2L77EE7U53NWQ.json
.\.venv\Scripts\kc.exe --json bestsellers get 172282 --domain US --dry-run
.\.venv\Scripts\kc.exe --json topsellers list --domain US --fixture topsellers_US.json --out topsellers.json
.\.venv\Scripts\kc.exe --json tokens status --fixture token_status.json
.\.venv\Scripts\kc.exe --json graphs image B09YNQCQKR --domain US --width 800 --height 400 --range 365 --param amazon=1 --dry-run
.\.venv\Scripts\kc.exe --json lightningdeals list --domain US --fixture lightningdeals_US.json
.\.venv\Scripts\kc.exe --json tracking list-names --dry-run
.\.venv\Scripts\kc.exe --json tracking add --tracking-json "{`"asin`":`"B09YNQCQKR`",`"domain`":1}" --dry-run
.\.venv\Scripts\kc.exe --json capabilities
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
```

stdio smoke test：

```powershell
'{"id":"1","method":"doctor","params":{}}' | .\.venv\Scripts\python.exe -m keepa_cli --stdio
```

启动人类 TUI 工作台：

```powershell
.\.venv\Scripts\python.exe -m keepa_cli
```

TUI 默认展示上下文状态、常用命令和结果面板；所有命令仍通过同一套 Agent-safe service 执行，不复制业务逻辑。常用 slash 命令示例：

```text
/doctor
/domains
/product B001GZ6QEC --domain US --fixture product_B001GZ6QEC.json
/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json
/bestsellers 172282 --domain US --dry-run
/seller A2L77EE7U53NWQ --fixture seller_A2L77EE7U53NWQ.json
/tokens --fixture token_status.json
/graph B09YNQCQKR --domain US --param amazon=1 --dry-run
/lightningdeals --domain US --dry-run
/tracking-list --asins-only --dry-run
/category 0 --domain US --parents --fixture category_roots_US.json
/category-search home kitchen --domain US --fixture category_search_home.json
/quit
```

## npm 安装目标

当前仓库已包含 npm wrapper，可本地 smoke：

```powershell
node bin/keepa-cli.js --json doctor
npm pack --dry-run
```

未来发布到 npm 后的目标安装方式：

```powershell
npm install -g @cunuo/keepa-cli
keepa-cli --json doctor
kc --json doctor
```

约束：

- npm wrapper 需要系统可用 Python 3.11+。
- 可通过 `KEEPA_CLI_PYTHON` 指定 Python 解释器路径。
- wrapper 不实现业务逻辑，只设置 `PYTHONPATH` 并执行 `python -m keepa_cli`。
