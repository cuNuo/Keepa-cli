# 任务日志：MCP quality gate JSON 失败输出优化

## 任务时间

- 开始时间：2026-05-12 01:49
- 最近更新时间：2026-05-12 01:55
- 完成时间：2026-05-12 01:55
- 当前状态：已完成

## 任务目标

- 继续优化 MCP 质量门禁的 Agent 可解析性。
- 保持生产 `python -m keepa_cli --mcp` 入口不变。
- 确保 `scripts/check_mcp_quality_gate.py --json` 在失败时仍只输出单一 JSON payload，不混入子进程 stdout/stderr。
- 补回归测试，提交推送并检查远端 CI。

## 背景与输入

- 上一轮已新增 SDK typed 分页、typed Inspector snapshot 与统一 MCP quality gate。
- 本轮复查发现 `_run_step()` 在 `--json` 模式下遇到失败步骤时仍会先打印子进程 stdout/stderr，再输出失败 JSON，导致 Agent 或 CI 解析 stdout 时可能得到非 JSON 内容。
- 优化边界：普通人类 CLI 模式仍保留失败子进程输出；只有 JSON 模式收敛为机器可解析 payload。

## 处理过程

- `scripts/check_mcp_quality_gate.py` 新增 `QualityGateStepError`，携带失败 step 的结构化结果。
- `_run_step()` 在 `json_mode=True` 时不直接打印子进程 stdout/stderr；失败详情进入 `stdout_tail` 与 `stderr_tail`。
- `main(["--json"])` 捕获失败后输出 `{ok:false, steps:[...failed_step], error:...}`，保证 stdout 仍可直接 `json.loads()`。
- 非 JSON 模式保留原有行为：打印命令、子进程失败输出和失败摘要。
- `tests/test_mcp_sdk_adapter.py` 新增两个回归测试：
  - 直接覆盖 `_run_step(..., json_mode=True)` 失败时不写 stdout/stderr。
  - 覆盖 `quality_gate_main(["--json"])` 失败 payload 包含失败 step 且可解析。
- `docs/architecture/mcp-python-sdk-adapter-comparison.md` 补充 `--json` 成功/失败输出均为单一 JSON payload 的约定。

## 已完成验证

- `.\\.venv\\Scripts\\python.exe -m py_compile scripts\\check_mcp_quality_gate.py tests\\test_mcp_sdk_adapter.py`：通过。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_mcp_sdk_adapter -v`：通过，10 项通过。
- `.\\.venv\\Scripts\\python.exe scripts\\check_mcp_quality_gate.py --require-sdk --json`：通过，输出可解析 JSON。
- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：通过，328 项通过。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- `.\\.venv\\Scripts\\python.exe -m keepa_cli --json doctor`、`node .\\bin\\keepa-cli.js --json doctor`、`node .\\bin\\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack release gate 同步跑过 compileall、328 项 unittest、live cache option lint、fixture sync、MCP quality gate、install_verify 与 doctor。
- 已提交并推送 `c052f2b mcp: stabilize quality gate json failures` 到 `origin/main`。
- 远端 CI：`https://github.com/cuNuo/Keepa-cli/actions/runs/25687526327` 通过；包含 ubuntu/macos/windows Python 3.11/3.12 matrix 与 `mcp-sdk-adapter` job。
- Pages：`https://github.com/cuNuo/Keepa-cli/actions/runs/25687526410` 通过。

## 待完成验证

- 无。

## 风险与后续

- 本轮只改变 quality gate 失败输出语义，不改变 MCP adapter、tool schema 或生产 stdio 行为。
- 后续如果新增更多聚合门禁，应保持 JSON 模式失败时只输出结构化 payload，避免 Agent 解析失败。
