# Keepa-cli 项目 Agent 入口

## 常驻事实

- 项目目标：构建 Agent-first 的 Keepa API CLI，同时服务自动化 Agent 和人类终端用户。
- 主入口：`keepa-cli` 与 `kc` 必须完全等价；`python -m keepa_cli` 也必须可用于本地验证。
- 技术栈：Python 3.11+ 标准库优先，测试使用 `unittest`；npm 包只提供 Node.js bin wrapper，业务逻辑仍在 Python 包内。
- 本地开发必须使用项目 `.venv`，不要向基础环境安装依赖。
- 默认不访问真实 Keepa API，不消耗真实 token；真实请求必须显式配置 `KEEPA_API_KEY`，高成本或有副作用请求必须显式确认。

## 知识入口

- 首先读取 Serena memory，优先关注：`project_overview`、`suggested_commands`、`task_completion_checklist`、`project_health_improvement_backlog_20260509`。
- 项目概览与命令入口见 `README.md`。
- Agent 协议见 `docs/agent-contract.md`。
- Keepa 官方约束摘记见 `docs/keepa-official-api-notes.md`。
- 开发路线见 `docs/roadmaps/2026-05-09-keepa-cli-development-roadmap.md`。
- evidence 索引见 `evidence/README.md` 与 `evidence/manifest.csv`。
- Hook 快速索引见 `hooks/README.md`，项目级转发入口为 `hooks/run_relevant_hooks.py`。

## 执行约束

- 新增命令必须同时接入 `run_command`、CLI、stdio、Agent schema 或 capabilities，并覆盖 fixture/dry-run 测试。
- 涉及真实 Keepa API 的功能必须保留离线 fixture 或 fake opener 测试，不把真实 API 调用放进默认 CI。
- 涉及 secret、API key、token、authorization、webhook URL 的输出必须脱敏。
- 涉及 graphimage、文件输出、缓存或 cassette 时，输出必须包含可审计 provenance 元数据。
- `keepa_cli/service.py` 与 `keepa_cli/cli.py` 已较大；继续扩展命令族时应优先按 command family 拆分。

## 标准验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
node .\bin\keepa-cli.js --json doctor
node .\bin\kc.js --json doctor
npm pack --dry-run --json
```

发布或大改前优先运行：

```powershell
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
```

## 记录要求

- 任务完成时更新 `evidence/tasks/` 下的任务日志，并按需更新 `evidence/manifest.csv`。
- 长期稳定事实写入 Serena memory；一次性过程只写 evidence。
- 默认不由 Codex 自动提交；如用户要求提交，再按当前工作区状态分批 stage/commit。
