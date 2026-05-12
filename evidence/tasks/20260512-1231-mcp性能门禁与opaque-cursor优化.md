# MCP 性能门禁与 opaque cursor 优化

- 日期：2026-05-12
- 范围：MCP raw stdio、官方 SDK adapter parity、质量门禁、文档同步
- 输入来源：用户 P0/P1/P2 要求、项目现有 MCP 实现、MCP 2025-11-25 官方 pagination/tools 规范

## 假设与不确定性

- 默认不访问真实 Keepa API；所有验证使用本地 fixture、dry-run 或本地 MCP resources。
- 官方 Python SDK typed `list_*` 当前仍只支持标准 `cursor`，不能表达 Keepa 扩展的 `toolset/profile/allow_tools/exclude_tools/limit` 参数；因此生产入口仍保持 raw stdio。
- 性能阈值先按当前本地基线加宽松上限固化，后续 CI 收集稳定后再收紧。

## 变更摘要

- 新增 `scripts/check_mcp_performance_gate.py`，固定 initialize、`tools/list research`、`tools/list all limit=8`、`resources/list`、`prompts/list`、`context_policy` 与 fixture `products_get` 基准；默认连续 30 次取 p95，记录 latency、JSON bytes、text fallback bytes、structuredContent bytes 与 fixture cache hit p95。
- `scripts/check_mcp_quality_gate.py` 纳入 outputSchema 离线校验、performance gate 与新增 SDK adapter filter parity fixture。
- raw stdio cursor 从 offset 升级为不透明 payload，包含 `schema_version`、`collection`、`offset`、`fingerprint`；错 collection 或错 filter 复用 cursor 会返回 JSON-RPC `-32602 Invalid pagination params`。
- `toolset=all` 未显式传 `limit` 时默认只返回 8 个 starter tools：`context_policy`、`docs_index`、`workflow_plan`、`agent_profile_generate`、`products_get`、`products_compare`、`categories_search`、`finder_query`，并返回 `nextCursor`。
- `list_mcp_tools()` 增加静态 MCP schema cache，profile active/inactive 只做轻量 overlay。
- `tools/call` 重输出继续保留 `mcp_resource_manifest` text fallback，并追加官方 `resource_link` content block。
- 新增 `tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json`，覆盖 `toolset/profile/allow_tools/exclude_tools/limit/cursor` parity；SDK adapter typed `list_tools` 显式从 raw registry 拉取 `toolset=all limit=100` 后再做 8 项 starter page。

## 官方规范对齐

- MCP pagination 要求 list 操作用 opaque cursor 和 `nextCursor` 分页；支持 `resources/list`、`resources/templates/list`、`prompts/list`、`tools/list`，非法 cursor 应映射为 `-32602`。
- MCP tools 结果允许 `structuredContent`，并建议同时提供 text fallback；结果 content 可包含 `resource_link`。
- outputSchema 校验不放到热路径，改由 fixture/quality gate 覆盖代表性成功与错误输出。

## 验证记录

- `python -m py_compile keepa_cli/agent/mcp.py keepa_cli/agent/tools.py keepa_cli/agent/mcp_sdk_adapter.py scripts/check_mcp_performance_gate.py scripts/check_mcp_output_schema.py scripts/check_mcp_quality_gate.py`：通过。
- `python scripts/check_agent_eval_fixtures.py`：通过，32 specs。
- `python scripts/check_mcp_output_schema.py --json`：通过。
- `python scripts/check_mcp_performance_gate.py --json --iterations 5`：通过；`tools_list_all_page` 约 20 KB，默认 all starter page 返回 8 tools + `nextCursor`。
- `python scripts/compare_mcp_sdk_adapter_fixture.py --fixture tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json`：通过。
- `python -m unittest tests.test_mcp tests.test_mcp_sdk_adapter -v`：通过，60 tests。
- `python scripts/check_mcp_quality_gate.py --require-sdk --json`：通过，包含 30 次 performance gate、outputSchema、adapter parity、SDK smoke、typed fixture 与 snapshot。
- `python -m unittest discover -s tests -v`：通过，331 tests。
- `git diff --check`：通过。
- `python D:\.codex\hooks\run_relevant_hooks.py --changed-only`：通过。
- `python -m keepa_cli --json doctor`、`node .\bin\keepa-cli.js --json doctor`、`node .\bin\kc.js --json doctor`：通过。
- `npm pack --dry-run --json`：通过；prepack 触发 release gate 并通过。

## 后续风险

- 30 次默认 performance gate 尚需在完整质量门禁和 CI 环境持续观察；如果 Windows/macOS/Ubuntu p95 差异较大，应只调阈值，不降低基准项覆盖。
- SDK adapter 已补 parity fixture，但仍不应提升为生产入口；真实生产化前还需要持续通过全量 gate、真实客户端烟测和 Streamable HTTP 边界评估。
- 长任务如 figures/report 后续更适合 MCP Tasks/progress，不应把普通 `tools/call` 长时间阻塞作为默认设计。
