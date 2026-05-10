# workflow policy 与 promote 验证增强

## 前置说明

- 本轮继续按用户要求检查 Keepa-cli 的 Agent/MCP 接入体验，并优先选择离线可验证、可进 CI 的优化点。
- 未访问真实 Keepa API，未消耗真实 token；所有验证使用 fixture、dry-run 或本地命令。
- 本轮同时保留并审查了工作区中已出现的 `cassettes.promote_and_verify` 相关改动，确认它符合前序 cassette promotion 路线，因此一并纳入验证与收口。

## 已落地

1. `workflow.plan` 增强为 Agent 可执行策略
   - 每个 step 增加 `mcp_tool`、`mcp.toolset`、`mcp.profile`、`mcp.call` 与 `execution`。
   - 新增 `workflow_policy`：包含 `recommended_toolset`、`recommended_profile`、`allowed_tools`、`inactive_tools`、`profile_switch_points`、`confirmation_policy`、`budget_ledger_seed`、`tool_discovery` 与 `cache_policy`。
   - 高成本步骤不再在计划参数中预塞 `yes=true`，只在 `execution.confirmation_params` 与 `confirmation_policy` 中提示确认后追加。

2. Agent eval 固化 workflow profile policy
   - 新增 `tests/agent_eval_fixtures/workflow_plan_profile_policy.json`。
   - 覆盖推荐 profile、inactive tools、确认 step、预算 seed、MCP call 和 `next_actions` 可执行性。

3. `cassettes.promote_and_verify` 工程化收口
   - 暴露 CLI：`kc --json cassettes promote-and-verify ...`。
   - 暴露 MCP：`keepa.cassettes_promote_and_verify`，并允许 `fixture_curation` profile 使用。
   - promote 后检查双份 fixture parity；可选 `--run-eval` 运行 Agent eval fixtures。
   - 新增包内 `keepa_cli.fixture_sync` 与 `keepa_cli.agent_eval`，避免 service 层直接依赖仓库 `scripts/` 做 parity 与 Agent eval 检查。

4. 文档与技能同步
   - 更新 README、中文 README、`docs/agent-contract.md`、`docs/architecture/mcp-agent-tools.md`。
   - 更新项目内 `.codex/skills/keepa-cli` 与 `.codex/skills/keepa-agent-research`。
   - 刷新 schema snapshot 与 capabilities schema version。

5. `keepa://workflow/{encoded_params}/policy` resource template
   - `resources/templates/list` 新增 workflow policy 资源模板。
   - `resources/read` 可读取 `keepa://workflow/<base64url-json>/policy`，内部复用本地 `workflow.plan`，不访问 Keepa。
   - 返回 `view=workflow_policy_resource`、原始 `params`、`workflow_policy`、`totals`、紧凑 `step_summary` 与 `recommended_read_order`。
   - 新增 `tests/agent_eval_fixtures/workflow_policy_resource.json`，覆盖推荐 profile、确认 step 与首个 MCP tool 摘要。

6. 公开项目元数据收口
   - 将 `package.json` homepage 与 `pyproject.toml` Homepage / Documentation 统一指向 GitHub Pages 稳定入口。
   - 保留 `pyproject.toml` Architecture 指向 zread public wiki，区分稳定入口与生成式架构 wiki。
   - 用本地 HTTP server + Playwright 快照检查 `docs/index.html` 首屏与文档入口，确认无明显遮挡或缺失。

## 已执行验证

- 定向测试：`python -m unittest tests.test_phase10_workflows tests.test_mcp tests.test_project_tools tests.test_capabilities -q` 通过。
- Agent eval：`python scripts/check_agent_eval_fixtures.py` 通过，18 specs。
- Schema snapshot：`python -m unittest tests.test_schema_snapshot -q` 通过。
- 追加验证：`python -m unittest tests.test_mcp tests.test_capabilities tests.test_schema_snapshot -v` 中 MCP/capabilities 通过，schema snapshot 在新增 resource template 后按测试构造逻辑刷新。
- 追加 Agent eval：`python scripts/check_agent_eval_fixtures.py` 通过，19 specs。
- 全量测试：`python -m unittest discover -s tests -v` 通过，232 tests OK。
- Fixture sync：`python scripts/check_fixture_sync.py` 通过。
- 文本门禁：`git diff --check` 通过；schema snapshot 刷新后统一恢复 LF 行尾。
- Hook 路由：`python D:\.codex\hooks\run_relevant_hooks.py --changed-only` 通过。
- Doctor smoke：`python -m keepa_cli --json doctor`、`node .\bin\keepa-cli.js --json doctor`、`node .\bin\kc.js --json doctor` 均通过。
- Pack dry-run：`npm pack --dry-run --json` 通过，并触发 release gate 通过。

## 风险与后续

- `workflow_policy` 当前覆盖 `category-research` 与 `product-research` 两类计划；后续可把 reports/tracking-readonly 长链路也纳入同一计划器。
- `cassettes.promote_and_verify --run-eval` 依赖本地 eval specs；发布包环境若没有 `tests/agent_eval_fixtures`，会以结构化 `agent_eval.ok=false` 报告缺失，而不是访问网络。
- 下一步最适合继续完善：新增 `workflow.plan` for `report-research` / `tracking-audit`，让 Agent 在非产品研究链路里同样少猜。

## CI 反馈修复

- 首次推送提交 `e1f31fb` 后，GitHub Actions CI 在 `Check fixture sync` 失败。
- 根因：CI 直接运行 `python scripts/check_fixture_sync.py`，干净环境未执行 editable install，脚本目录被放入 `sys.path` 后无法导入仓库根包 `keepa_cli`。
- 修复：`scripts/check_fixture_sync.py` 与 `scripts/check_agent_eval_fixtures.py` 在导入包内模块前显式把仓库根目录加入 `sys.path`，保持直接脚本执行与包内复用两种路径一致。
- 修复后复验：`python scripts/check_fixture_sync.py`、`python scripts/check_agent_eval_fixtures.py`、`python -m unittest discover -s tests -q`、`git diff --check` 与 `D:\.codex\hooks\run_relevant_hooks.py --changed-only` 均通过。
