# Keepa CLI Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-05-09 健康检查中列出的 P0-P3 完善项转化为可验证的项目基础设施、Agent 能力协议和最小运行时能力。

**Architecture:** 先补项目治理入口和 evidence 索引，再用标准库脚本建立 release gate、fixture 同步检查和 live cassette 脱敏流程；运行时只做低风险增量：`capabilities` 能力发现、schema version、graphimage binary 输出和 cache provenance 元数据。大规模拆分先落文档与边界，不在同一轮做破坏性重构。

**Tech Stack:** Python 3.11+ 标准库、unittest、argparse、GitHub Actions、npm wrapper。

---

### Task 1: P0 治理入口

**Files:**
- Create: `AGENTS.md`
- Create: `evidence/README.md`
- Create: `evidence/manifest.csv`
- Modify: `evidence/tasks/20260509-2326-项目健康检查与完善项记录.md`

- [ ] 写入项目根常驻规则：`.venv`、双入口、Agent-first、无真实 API 默认调用、验证命令和知识入口。
- [ ] 写入 evidence 根 README，定义 tasks、manifest 和后续归档规则。
- [ ] 建立 manifest，登记历史调研日志与本次健康检查日志。
- [ ] 运行 `git diff --check`。

### Task 2: Release Gate 与 CI

**Files:**
- Create: `scripts/release_gate.py`
- Create: `scripts/check_fixture_sync.py`
- Create: `scripts/redact_cassette.py`
- Modify: `.github/workflows/ci.yml`
- Create: `.github/workflows/live-keepa-smoke.yml`
- Modify: `pyproject.toml`
- Modify: `package.json`

- [ ] 先写脚本测试，要求 release gate 能执行 compileall、unittest、fixture sync、npm pack dry-run。
- [ ] 实现 fixture 双目录字节级同步检查。
- [ ] 实现 cassette 脱敏脚本，清理 URL query 与 JSON 字段里的 key/api_key/apikey/token/authorization。
- [ ] CI 改为 Windows/Linux/macOS 与 Python 3.11/3.12 矩阵，保留 npm wrapper smoke。
- [ ] live smoke workflow 只允许手动触发，缺 secret 时失败前给出明确说明，不进入默认 CI。

### Task 3: Capabilities、Schema Version 与 Cache Provenance

**Files:**
- Create: `keepa_cli/capabilities.py`
- Create: `keepa_cli/cache.py`
- Modify: `keepa_cli/service.py`
- Modify: `keepa_cli/cli.py`
- Modify: `keepa_cli/agent/stdio.py`
- Test: `tests/test_capabilities.py`
- Test: `tests/test_cache.py`

- [ ] 先写 `capabilities` 和 cache provenance 测试。
- [ ] `kc --json capabilities` 返回 schema version、commands、预算、确认、fixture/live 支持。
- [ ] `run_command("capabilities")` 与 stdio `capabilities` 可用。
- [ ] dry-run / fixture / live envelope 附带可审计 provenance 元数据。

### Task 4: Graphimage Binary Transport

**Files:**
- Modify: `keepa_cli/client.py`
- Modify: `keepa_cli/service.py`
- Modify: `keepa_cli/cli.py`
- Test: `tests/test_official_api_coverage.py`

- [ ] 先把现有 live unsupported 测试改为期望 `--out` 写 PNG。
- [ ] 无 `--out` 的 live graphimage 仍拒绝，避免二进制写入 stdout。
- [ ] fake opener 返回 PNG bytes 时，写入目标文件，并返回路径、字节数、content type 和 cache provenance。
- [ ] CLI 增加 `graphs image --out <path>`。

### Task 5: P3 拆分策略与文档入口

**Files:**
- Create: `docs/architecture/service-cli-split-plan.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CHANGELOG.md`
- Modify: `README.md`

- [ ] 写明 `service.py` / `cli.py` 何时拆、怎么拆、哪些测试先保护。
- [ ] 补贡献、安全和变更记录入口。
- [ ] README 链接治理、发布、能力发现和安全文档。

### Task 6: 验证与收口

**Files:**
- Create: `evidence/tasks/20260509-硬化完善实施记录.md`
- Update: `evidence/manifest.csv`
- Serena memory: update health/backlog implementation summary

- [ ] 运行 `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- [ ] 运行 `.\\.venv\\Scripts\\python.exe scripts\\release_gate.py --skip-npm-install`。
- [ ] 运行 `git diff --check`。
- [ ] 运行 `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`。
- [ ] 写 evidence 和 memory。
