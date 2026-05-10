# MCP toolset、cassette promote 与跨命令 research graph

## 任务目标

- 完成 cassette promote workflow：真实响应或本地 cassette -> sanitize -> promote fixture -> 更新 manifest。
- 完成 MCP toolset 过滤：`research`、`audit`、`reports`、`tracking-readonly`，降低 `tools/list` 上下文污染。
- 将 `research_graph` 扩展到 category、finder、deals、seller 与 ranking 输出，形成跨命令统一实体图谱。

## 前置假设

- 本轮不访问真实 Keepa API，不消耗真实 token；所有行为通过 fixture、dry-run、临时目录与本地测试验证。
- 当前工作区已有前序 cache、client、workflow 与 command family 拆分改动，本轮不回退、不覆盖无关改动。
- `evidence/runtime-logs/` 可能包含真实响应数据，继续保持不提交；需要沉淀时必须先通过 `cassettes promote` 脱敏成 fixture。

## 完成内容

1. Cassette promote workflow。
   - `keepa_cli/cassettes.py` 增加 `promote_cassette_fixture()`，对输入 JSON 再次脱敏。
   - 同步写入 `tests/fixtures/<name>.json` 与 `keepa_cli/fixtures/<name>.json`。
   - 追加 `evidence/manifest.csv`，并对重复 logical path 做幂等跳过。
   - `fixture_name` 禁止空名、`..` 与路径分隔符，避免写出目标目录。
   - CLI/service/MCP/capabilities 均接入 `cassettes.promote`。

2. MCP toolset 过滤。
   - 默认 `tools/list` 只返回 `research` toolset。
   - 显式支持 `audit`、`reports`、`tracking-readonly` 与 `all`。
   - 未知 toolset 返回 JSON-RPC `Invalid toolset`，并附 `available_toolsets`。
   - `audit` 暴露 cost 与 cassette sanitize/promote；`reports` 暴露本地 report/browse；`tracking-readonly` 只暴露 tracking 读取工具，不暴露写操作。

3. 跨命令 `research_graph`。
   - 新增 `keepa_cli/research_graph.py`，为非产品命令生成统一轻量实体关系图。
   - category/search/finder/deals/seller/bestsellers/topsellers 输出 `research_graph` 与 `entity_counts`。
   - `agent_brief` 与 `evidence_index` 补充图谱入口，方便 Agent 先读语义层再决定是否加载大响应。
   - 文档、schema snapshot、README 与 companion skills 同步更新。

## 验证记录

已通过：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
.\.venv\Scripts\python.exe scripts\check_fixture_sync.py
.\.venv\Scripts\python.exe scripts\check_agent_eval_fixtures.py
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
node .\bin\keepa-cli.js --json doctor
node .\bin\kc.js --json doctor
```

行为 smoke：

- `tools/list {}` 返回 10 个 research tools。
- `tools/list {"toolset":"audit"}` 返回 3 个 audit tools，包含 `keepa.cassettes_promote`。
- `tools/list {"toolset":"reports"}` 返回 2 个 reports tools。
- `tools/list {"toolset":"tracking-readonly"}` 返回 4 个只读 tracking tools。
- `tools/list {"toolset":"all"}` 返回 19 个 tools。
- `finder.query`、`categories.search`、`categories.products`、`deals.query`、`sellers.get`、`topsellers.list` 均返回非空 `research_graph.entity_counts`。
- 临时 cassette promote 连续执行两次仍只生成一条 manifest entry，输出 fixture 内未保留测试 secret。

## 风险与边界

- 本轮未执行真实 Keepa live 请求；真实响应沉淀仍需用户明确同意后再低成本调用，并立刻 promote 为脱敏 fixture。
- MCP 当前实现为最小 stdio JSON-RPC，尚未提供 Streamable HTTP / SSE transport。
- `research_graph` 目前是轻量图谱，不做跨命令持久化 merge；下游 Agent 需要自行根据 node id 合并。

## 后续最适合方向

1. 增加 `research_graph merge` / MCP resource，让 category -> products -> compare -> seller 可以合并成单个研究图。
2. 增加 MCP resources：暴露 schema、fixture manifest、cassette promotion 指南与最近 evidence，减少 tool schema 里的说明文字。
3. 给大响应工具增加统一 chunk resource manifest，MCP content 只返回摘要和资源引用。
4. 扩展 Agent evaluation fixtures：断言 graph merge、risk taxonomy、next_actions 可执行性和 budget ledger 长链路。
5. 将 toolset 与风险等级绑定策略文档化，未来若暴露写工具，必须通过显式 write toolset 与 confirmation gate。
