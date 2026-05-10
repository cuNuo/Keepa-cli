# Family 拆分与 cache key 门禁任务日志

## 任务目标

- 继续拆分 `raw`、`history`、`finder`、`deals` command family，进一步降低 `keepa_cli/cli.py` 与 `keepa_cli/service.py` 复杂度。
- 增加 `cache explain-key`，让 Agent 能从 method、endpoint 与请求参数反查 SQLite response cache key。
- 把“新增可缓存 live 命令必须显式暴露 `--cache-ttl` / `--no-cache`”纳入 release gate 或轻量 lint。
- 完成本轮优化并提交由本轮优化涉及的文件。

## 背景与输入

- 用户要求延续上一轮 cache 与 command family 拆分工作。
- 默认不访问真实 Keepa API，不消耗真实 token；真实网络 smoke 仍需用户显式授权。
- 当前工作区存在前序未提交 Agent/MCP、research graph、skills 与文档改动；本轮提交阶段使用显式 pathspec，只纳入本轮优化和必要依赖文件。

## 处理过程

- 新增 CLI builder：
  - `keepa_cli/cli_builders/history.py`
  - `keepa_cli/cli_builders/finder.py`
  - `keepa_cli/cli_builders/deals.py`
  - `keepa_cli/cli_builders/raw.py`
- 新增 service command family：
  - `keepa_cli/commands/history.py`
  - `keepa_cli/commands/finder.py`
  - `keepa_cli/commands/deals.py`
  - `keepa_cli/commands/raw.py`
  - `keepa_cli/commands/selection.py`
- `keepa_cli/cli.py` 改为注册和分发 history/finder/deals/raw family，删除对应内联 parser 与分发分支。
- `keepa_cli/service.py` 改为通过 `can_handle_*` / `handle_*` 分发 raw/history/finder/deals，移除 selection 与 history 的内联实现。
- `keepa_cli/cache.py` 增加 `explain_response_cache_key()`；`cache explain-key` 通过 CLI、service、capabilities 和 docs 暴露。
- 新增 `scripts/check_live_cache_options.py` 并接入 `scripts/release_gate.py`，校验可缓存 live CLI 命令均显式支持 `--cache-ttl` / `--no-cache`。
- 门禁首版发现 tracking 写入命令无 cache 控制。由于 SQLite response cache 只缓存 live GET JSON，已将二进制 `graphs.image` 和 tracking 写入/副作用命令排除在 cacheable live 检查外。

## 验证结果

- `.\.venv\Scripts\python.exe -m compileall -q keepa_cli scripts tests`：通过。
- `.\.venv\Scripts\python.exe scripts\check_live_cache_options.py`：通过。
- `.\.venv\Scripts\python.exe -m unittest tests.test_cache tests.test_cli tests.test_project_tools tests.test_phase8_high_value_commands tests.test_service_commands -v`：72 tests OK。
- `.\.venv\Scripts\python.exe -m unittest tests.test_schema_snapshot -v`：OK。

## 关联产物

- 拆分入口：`keepa_cli/cli.py`、`keepa_cli/service.py`。
- CLI builder：`keepa_cli/cli_builders/history.py`、`keepa_cli/cli_builders/finder.py`、`keepa_cli/cli_builders/deals.py`、`keepa_cli/cli_builders/raw.py`。
- service handler：`keepa_cli/commands/history.py`、`keepa_cli/commands/finder.py`、`keepa_cli/commands/deals.py`、`keepa_cli/commands/raw.py`、`keepa_cli/commands/selection.py`。
- cache 审计：`keepa_cli/cache.py`、`keepa_cli/workflows.py`、`keepa_cli/cli_builders/cache.py`、`keepa_cli/commands/cache.py`、`keepa_cli/capabilities.py`。
- 门禁：`scripts/check_live_cache_options.py`、`scripts/release_gate.py`。
- 测试与契约：`tests/test_cache.py`、`tests/test_cli.py`、`tests/test_project_tools.py`、`tests/snapshots/agent_schema_snapshot.json`。
- 文档：`README.md`、`README.zh-CN.md`、`docs/agent-contract.md`。

## 风险与后续

- 未执行真实 Keepa live 请求；真实请求路径仍需在显式授权和低成本 smoke 中验证。
- `sellers`、`bestsellers`、`topsellers`、`tokens`、`graphs`、`lightningdeals` 仍在 `service.py` / `cli.py` 内，可继续按 family 拆分。
- `cache explain-key` 当前接受手工 method/endpoint/param；后续可增加从 dry-run envelope 自动提取 request spec 的模式。

## 结论

本轮已完成 raw/history/finder/deals family 拆分、cache key 反查审计命令、可缓存 live cache 控制 lint 与 release gate 接入，并完成定向验证。长期稳定结论写入 Serena memory：`family_split_cache_explain_key_gate_20260510`。
