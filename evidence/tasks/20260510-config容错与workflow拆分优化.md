# 任务日志：config 容错与 workflow 拆分优化

## 任务时间

- 开始时间：2026-05-10 10:48
- 最近更新时间：2026-05-10 10:48
- 完成时间：2026-05-10 10:48
- 当前状态：已完成

## 任务目标

- 修复用户真实启动 `python -m keepa_cli` 时因本地 `config.toml` 反斜杠未转义导致的崩溃。
- 继续优化项目结构，把 v1 本地 workflow 命令族从 `service.py` / `cli.py` 拆出。

## 背景与输入

- 用户反馈：`tomllib.TOMLDecodeError: Unescaped '\\' in a string` 导致 TUI 启动失败。
- 已知约束：默认不访问真实 Keepa API；配置错误不能泄露 token；新增源码需中文文件头；验证使用项目 `.venv`。
- 相关入口：`keepa_cli/config.py`、`keepa_cli/doctor.py`、`keepa_cli/service.py`、`keepa_cli/cli.py`、`docs/architecture/service-cli-split-plan.md`。

## 处理过程

### 1. 配置解析容错

- 做了什么：`load_config()` 捕获 `tomllib.TOMLDecodeError` 和 `OSError`，返回默认配置并附带 `_config_error`；`build_config_report()` 输出 `valid` 与 `error`；`doctor` 将坏配置报告为 `auth.source = config_error`。
- 为什么这么做：用户配置文件可能手写错误，但 CLI/TUI 不应因配置解析失败直接崩溃。
- 结果：坏 TOML 配置下 `doctor` 与 `tui --json` 可正常返回结构化结果。

### 2. workflow 命令族拆分

- 做了什么：新增 `keepa_cli/commands/workflows.py` 和 `keepa_cli/cli_builders/workflows.py`，并增加对应包入口。
- 为什么这么做：`service.py` 与 `cli.py` 已较大，先用本地 workflow 命令族建立低风险拆分样板。
- 结果：`cli.py` 从约 41KB 降到约 35KB，`service.py` 从约 34KB 降到约 31KB；公开 command id 与 JSON envelope 未变化。

## 验证结果

- 验证方式：执行 `.\\.venv\\Scripts\\python.exe -m unittest tests.test_config tests.test_doctor tests.test_modern_tui -v`。
- 验证结论：30 个测试通过。
- 验证方式：执行坏 TOML 配置 smoke：`KEEPA_CLI_CONFIG=<bad.toml> python -m keepa_cli --json doctor` 与 `python -m keepa_cli --json tui`。
- 验证结论：均正常返回 JSON，未崩溃。
- 验证方式：执行 `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`。
- 验证结论：131 个测试全部通过。
- 验证方式：执行 `.\\.venv\\Scripts\\python.exe scripts\\release_gate.py --skip-npm-install`。
- 验证结论：compileall、全量测试、fixture sync、install verify、Python/Node smoke、npm pack dry-run 全部通过。
- 验证方式：执行 `git diff --check`。
- 验证结论：无空白错误。
- 验证方式：执行 `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`。
- 验证结论：文件头与目录反模式审计通过。
- 未验证项：未执行真实 Keepa live 请求；本轮无 live 需求。

## 关联产物

- 相关 memory：`config_tolerance_and_workflow_split_20260510`
- 建议沉淀 memory topic：坏配置容错、workflow 命令族拆分样板。
- 相关运行日志：无单独落盘运行日志。
- 相关数据工件：无。
- 相关路由文档：`docs/architecture/service-cli-split-plan.md`
- 相关文档：无文档正文改动。

## 风险与后续

- 当前风险：坏配置会被忽略并使用默认值，用户仍需通过 `kc --json config show` 查看 `valid=false` 后修复或重新 `config set-token`。
- 当前风险：`service.py` / `cli.py` 仍偏大，后续应继续按 `tracking`、`graphs`、`history` 等命令族拆分。
- 建议后续动作：为 `config show` 在非 JSON 人类输出中增加更醒目的 invalid config 提示；继续拆分一个 API 命令族验证模板可复用性。

## 结论

- 本轮已修复坏 TOML 配置导致 CLI/TUI 启动崩溃的问题，并完成本地 workflow 命令族拆分样板，验证与发布门禁均通过。
