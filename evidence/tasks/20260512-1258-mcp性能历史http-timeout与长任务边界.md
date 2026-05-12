# MCP 性能历史、HTTP timeout 与长任务边界

## 任务目标

- 继续按 MCP 官方规范完善 Keepa-cli MCP，不恢复 `keepa.*` 旧工具名。
- 让 performance gate 可在 CI 跑几轮后基于真实 p95 历史收紧阈值。
- Streamable HTTP 继续只做协议 adapter 前置合约，先固定 timeout / session-id / Origin 边界。
- `figures_research` / `reports_build` 后续走 MCP Tasks/progress，不让普通 `tools/call` 承担大型长阻塞任务。

## 背景与输入

- 生产入口仍是 raw stdio：`python -m keepa_cli --mcp` / `kc --mcp`。
- 官方 SDK adapter 与未来 HTTP adapter 只允许复用 `AgentSession`、`run_command`、tool/resource/prompt registry 与 workflow resolver。
- 默认不访问真实 Keepa API；本轮所有验证均使用 fixture / dry-run。
- 官方 MCP 参考：`2025-11-25` 版本支持工具分页、结构化工具结果、Streamable HTTP、Tasks/progress；当前项目仍不声明 Tasks capability。

## 处理过程

- `scripts/check_mcp_performance_gate.py` 增加 `--out`，完整写出单轮 benchmark JSON，payload 追加 `generated_at`。
- `scripts/check_mcp_quality_gate.py` 增加 `--performance-out`，CI 中通过聚合门禁直接产出 performance artifact。
- `.github/workflows/ci.yml` 的 `mcp-sdk-adapter` job 上传 `artifacts/mcp-performance/*.json`，保留 14 天，供后续多轮汇总。
- 新增 `scripts/summarize_mcp_performance_history.py`，读取多个 JSON 文件、目录或 glob，按 benchmark label 汇总历史 p95 / bytes max，并输出 `suggested_thresholds` 与 `ready_to_tighten`。
- `keepa_cli.agent.mcp_http_contract` 增加请求级 timeout 规范：默认 30000 ms，允许 1000..300000 ms，非法 timeout 映射 HTTP 400，执行超时映射 HTTP 504。
- `tests/agent_eval_fixtures/mcp_streamable_http_boundary_fixture.json` 扩展 timeout case，并继续覆盖 Origin allowlist/reject、`MCP-Session-Id` 初始化/缺失/过期/DELETE、JSON-RPC 错误映射和 notification 202。
- `reports_build` 与 `figures_research` 增加 `x-keepa.long_running_candidate`、`normal_tools_call_policy=fixture_or_small_output_only` 与 future Tasks/progress metadata；当前 `execution.taskSupport` 仍保持 `forbidden`，避免在未声明 Tasks capability 前误导客户端。
- 同步 README、README.zh-CN、`docs/agent-contract.md`、`docs/architecture/mcp-python-sdk-adapter-comparison.md`、schema snapshot 与测试。

## 验证结果

- `python -m py_compile scripts/check_mcp_performance_gate.py scripts/summarize_mcp_performance_history.py scripts/check_mcp_quality_gate.py keepa_cli/agent/mcp_http_contract.py keepa_cli/agent/tools.py keepa_cli/agent/resources.py`：通过。
- `python -m unittest tests.test_mcp_http_contract tests.test_mcp_performance_history tests.test_release_ecosystem -v`：11 项通过。
- `python scripts/check_agent_eval_fixtures.py`：32 specs 通过。
- `python -m unittest tests.test_mcp -v`：49 项通过。
- `python scripts/check_mcp_performance_gate.py --json --iterations 3 --out <local temp>`：通过，确认 `--out` 写入性能 JSON。
- `python scripts/summarize_mcp_performance_history.py <local temp dir> --json --out <local temp>`：通过，确认单轮历史时 `ready_to_tighten=false` 且能生成建议阈值。
- `python -m unittest tests.test_schema_snapshot tests.test_schema_docs -v`：3 项通过。
- `python scripts/check_mcp_quality_gate.py --require-sdk --performance-out <temp>`：通过。
- `python -m unittest discover -s tests -v`：335 项通过。
- `git diff --check`：通过。
- `python D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过。
- `python -m keepa_cli --json doctor`、`node .\bin\keepa-cli.js --json doctor`、`node .\bin\kc.js --json doctor`：均通过。
- `npm pack --dry-run --json`：通过；prepack 触发 release gate，release gate 通过。

## 风险与后续

- 当前性能阈值仍是宽松基线；至少累计 3 轮 CI artifact 后，再用 `scripts/summarize_mcp_performance_history.py` 的 `ready_to_tighten=true` 输出收紧 `THRESHOLDS`。
- `Keepa-MCP-Timeout-Ms` 是项目 HTTP adapter 前置合约字段，不代表当前 stdio 生产入口已经具备 HTTP transport。
- `reports_build` / `figures_research` 只是标记未来 Tasks/progress 迁移边界；未实现 Tasks capability 前，不能把 `execution.taskSupport` 改成 `required`。
- SDK adapter 仍未提升为生产入口；提升前必须继续通过 toolset/profile/filter/cursor parity、typed Inspector snapshot、真实客户端验证与性能门禁。

## 结论

MCP 性能门禁已具备可积累历史并基于真实 p95 收紧的路径；HTTP 前置合约补齐 timeout/session-id/Origin；报告与图表长任务已标记未来 Tasks/progress 边界。现有 stdio 服务保持正常，公共工具名继续使用无前缀新名。
