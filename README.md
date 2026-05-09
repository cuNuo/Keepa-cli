# Keepa CLI 调研与实现方案

本仓库用于沉淀基于 Keepa API 的 Agent-first CLI 程序设计、实现计划与后续代码。最终目标是把 Keepa 能力封装成后续 Agent 可稳定调用的工具层，同时提供人类友好的交互界面。

当前已完成调研报告：

- [Keepa CLI 实现调研与落地报告](docs/reports/2026-05-09-keepa-cli-implementation-report.md)
- [Keepa CLI 功能完善与完整开发路线](docs/roadmaps/2026-05-09-keepa-cli-development-roadmap.md)
- [Keepa CLI Agent 协议契约](docs/agent-contract.md)

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
- `--stdio` JSON Lines 协议
- JSON success/error envelope
- Keepa domain 归一化
- token 预算器
- request client dry-run 与 fixture/offline 路径
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
```

stdio smoke test：

```powershell
'{"id":"1","method":"doctor","params":{}}' | .\.venv\Scripts\python.exe -m keepa_cli --stdio
```
