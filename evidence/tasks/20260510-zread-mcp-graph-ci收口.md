# zread 接入、MCP resource templates 与 research graph diff 收口

## 任务目标

- 按用户要求把已生成的 `.zread/wiki/` 作为项目知识资产接入，而不是忽略。
- 参考 zread wiki 对主链路做二次审查，继续完善 Agent/MCP 协议层。
- 修复 GitHub Actions Node.js 20 runtime deprecation 提示。
- 补齐 reports / tracking-readonly Agent eval，并完成提交前验证。

## 前置假设

- 本轮不访问真实 Keepa API，不消耗真实 Keepa token。
- `.zread/wiki/versions/2026-05-10-215740` 是用户已生成的本地 wiki 快照，本轮不重新调用 zread 生成，避免额外 LLM 成本。
- zread wiki 反映的是生成时点的架构状态；本轮后续新增的 cache-key/ASIN/evidence resource template 与 graph diff 以 README、docs、tests 和本 evidence 为准。

## 完成内容

1. zread 接入。
   - README / README.zh-CN 增加 zread badge。
   - README 增加 `zread browse` 与 `zread browse --stdio` 使用说明。
   - README 链接 `.zread/wiki/current` 与 `.zread/wiki/versions/2026-05-10-215740/wiki.json`。
   - `.zread/` 未加入 `.gitignore`，本轮作为可提交文档快照纳入仓库。

2. GitHub Actions runtime。
   - `.github/workflows/ci.yml`：`actions/checkout@v4` -> `actions/checkout@v6`，`actions/setup-python@v5` -> `actions/setup-python@v6`。
   - `.github/workflows/live-keepa-smoke.yml` 同步升级。
   - 已读取官方 action.yml 验证：
     - `actions/checkout@v6` 使用 `runs.using: node24`。
     - `actions/setup-python@v6` 使用 `runs.using: node24`。

3. MCP resource templates。
   - 新增 `keepa_cli/agent/cache_keys.py`，把 AgentSession cache key 生成逻辑拆到无业务依赖模块，避免 resources -> session -> service -> capabilities -> resources 循环导入。
   - `resources/templates/list` 现在暴露：
     - `keepa://schema/{name}`
     - `keepa://fixtures/{name}`
     - `keepa://cache-key/{command}/{encoded_params}`
     - `keepa://asin/{asin}/fixture`
     - `keepa://evidence/{encoded_logical_path}`
     - `keepa://chunk/{encoded_path}`
     - `keepa://output/{encoded_path}`
   - `resources/read` 支持预览 cache key、按 ASIN 查 fixture 候选、按 manifest logical path 读取 evidence task log。

4. Research graph diff 与 source preference。
   - `research_graph.merge` / `keepa.research_graph_merge` 新增 `prefer_source` / `--prefer-source`。
   - 合并结果新增 `diff`，包含冲突节点 variants、resolutions、preferred_source 与摘要计数。
   - 冲突节点会按同一 resolution 更新主图节点，避免 `diff` 和 `graph.nodes` 不一致。
   - `data_quality`、`agent_brief.read_order`、`evidence_index` 同步加入 `diff`。

5. Agent eval 增强。
   - 新增 `reports_build_local_output.json`，断言 reports toolset 可生成本地 markdown 报告并返回 provenance/output。
   - 新增 `tracking_readonly_session_ledger.json`，断言 tracking-readonly 参数质量、session cache hit 与 budget ledger。
   - 扩展 `mcp_resource_templates_contract.json` 与 `research_graph_merge.json`，覆盖新 templates、graph diff 与 next graph audit 字段。
   - 同步新增双份 fixture：`agent_eval_report_input.json`。

## 验证记录

- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`：213 tests OK。
- `.\\.venv\\Scripts\\python.exe scripts\\check_agent_eval_fixtures.py`：11 specs OK。
- `.\\.venv\\Scripts\\python.exe scripts\\check_fixture_sync.py`：通过。
- `git diff --check`：通过。
- `.\\.venv\\Scripts\\python.exe scripts\\release_gate.py --skip-npm-install`：通过。
- `.\\.venv\\Scripts\\python.exe D:\\.codex\\hooks\\run_relevant_hooks.py --changed-only`：通过。
- `node .\\bin\\keepa-cli.js --json doctor`：通过。
- `node .\\bin\\kc.js --json doctor`：通过。
- `.\\.venv\\Scripts\\python.exe -m keepa_cli --json capabilities`：通过，schema version 为 `2026-05-10.16`。

## 风险与边界

- `.zread/wiki` 是本地静态快照，后续架构大改后应重新运行 `zread generate -y --stdio --draft clear --skip-failed`。
- README badge 链接到公开 zread 页面；公开页面是否即时刷新取决于 zread 服务，不影响本地 `.zread/wiki` 可审计性。
- 本轮未触发 live Keepa smoke，也未使用真实 token。

## 后续最适合方向

1. 给 MCP 增加 graph root / cache-key 的 resource template，按研究图 root 读取图摘要。
2. 让 reports builder 可直接消费 merged research graph，输出实体关系报告。
3. 把 `.zread/wiki` 的关键页面刷新纳入发布前 checklist，避免文档快照长期落后。
4. 为 tracking-readonly 增加更多 fixture 覆盖 `tracking.get` 与通知游标场景。
