# SQLite cache 与 Agent eval 门禁

## 任务时间

- 开始时间：2026-05-10 16:00
- 最近更新时间：2026-05-10 16:42
- 当前状态：已完成

## 任务目标

- 补 Phase 3 持久缓存，让 `cache stats/clear` 不再只是说明性状态入口。
- 做结构性降债，继续按 command family 拆分 `cli.py` / `service.py`。
- 将 Agent evaluation fixtures 纳入稳定文档和 release gate 门禁。

## 本轮实现

- 新增 `SQLiteResponseCache`，默认缓存成功的 live GET JSON 响应。
- cache key 排除 `key`、`api_key`、`apikey`、`token`、`authorization` 等敏感字段。
- dry-run、fixture、binary、POST、TTL 为 0 或 `KEEPA_CLI_NO_CACHE=1` 的请求不写入持久缓存。
- `cache stats` / `cache clear` 现在读取和清理 SQLite response cache，支持 `--cache-path`。
- `KEEPA_CLI_CACHE_PATH` 可覆盖默认缓存路径，`KEEPA_CLI_CACHE_TTL_SECONDS` 可覆盖 TTL。
- cache hit 返回 `cache_hit=true`，本次 `tokens_consumed=0`，并保留 `cached_tokens_consumed` 供审计。
- 新增 `scripts/check_agent_eval_fixtures.py`，并接入 `scripts/release_gate.py`。
- 新增 `keepa_cli/cli_builders/cache.py` 与 `keepa_cli/commands/cache.py`，把 cache 命令族从 workflow builder/handler 中拆出。
- 更新 README / README.zh-CN / Agent contract / capabilities / schema snapshot / schema docs。

## 验证结果

- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_cache tests.test_client tests.test_phase10_workflows tests.test_agent_eval_fixtures tests.test_release_ecosystem -v`：通过，25 tests OK。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_cache tests.test_phase10_workflows tests.test_cli tests.test_capabilities tests.test_release_ecosystem -v`：通过，45 tests OK。
- `.\\.venv\\Scripts\\python.exe -m unittest tests.test_cache tests.test_client tests.test_service_commands tests.test_official_api_coverage tests.test_phase8_high_value_commands tests.test_phase10_workflows tests.test_capabilities tests.test_schema_snapshot tests.test_schema_docs tests.test_agent_eval_fixtures tests.test_release_ecosystem -v`：通过，73 tests OK。
- `.\\.venv\\Scripts\\python.exe scripts\\check_agent_eval_fixtures.py`：通过，4 specs OK。
- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：通过，191 tests OK。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe scripts\\release_gate.py --skip-npm-install`：通过，包含 compileall、全量测试、fixture sync、Agent eval fixtures、install verify、Python/Node doctor 与 npm pack dry-run。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- CLI smoke：
  - `python -m keepa_cli --json cache stats --cache-path <temp>`：通过。
  - `python -m keepa_cli --json cache clear --dry-run --cache-path <temp>`：通过。

## 风险与边界

- 当前默认只缓存 live GET JSON 响应，不缓存 fixture、dry-run、binary、POST 和 tracking 写操作。
- `cache clear` 只清理 SQLite response cache，不影响 `tests/fixtures`、包内 fixtures 或 Agent 进程内 session cache。
- 本轮未执行真实 Keepa live 请求；live cache 行为通过 fake opener 测试验证。
- 工作区包含前序阶段未提交改动，本轮没有回退这些改动。

## 后续建议

1. 为产品/分类等常用 CLI 显式补 `--cache-ttl` 与 `--no-cache` 参数，而不只依赖环境变量。
2. 增加 `cache inspect` / `cache prune-expired`，让 Agent 可审计单条 cache key 与过期清理。
3. 继续按 command family 拆分 `products`、`categories`、`tracking`，降低 `service.py` 与 `cli.py` 体积。
