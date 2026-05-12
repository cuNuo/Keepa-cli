# MCP Agent Tools 架构设计

## 背景

Keepa-cli 已经具备 `--json`、`--stdio`、结构化 `next_actions`、Agent 视图、workflow plan 和离线 fixture。下一阶段需要给 Agent 与其他 MCP 客户端暴露 MCP tools，让 Agent 直接调用强类型工具，而不是拼接 CLI 字符串。

本设计基于以下调研结论：

- MCP tool 应以 `name`、`description`、`inputSchema` 为最小契约，并可补充 `outputSchema`、`annotations`、`structuredContent`。
- 成熟 MCP server 通常暴露少量任务导向 tools，而不是把完整 REST API 或 CLI 参数表原样映射出去。
- Agent 客户端对 `structuredContent` 支持程度不完全一致，tool 响应应同时提供结构化结果和 JSON text fallback。
- 长会话里的缓存、token 账本、确认阻断和 evidence index 属于 Agent 协议层能力，应独立于 CLI argparse。
- 当前项目标准库优先，因此先实现最小 MCP stdio JSON-RPC server；后续如需要 SSE、Streamable HTTP 或 SDK 高级能力，再评估接入官方 Python SDK。
- 官方 Python MCP SDK adapter 对照见 `docs/architecture/mcp-python-sdk-adapter-comparison.md`；结论是先保留当前 stdio 生产入口，再用 `keepa_cli/agent/mcp_sdk_adapter.py`、`scripts/compare_mcp_sdk_adapter_fixture.py`、`scripts/smoke_mcp_sdk_adapter_client.py` 和 `scripts/check_mcp_sdk_adapter_typed_fixture.py` 对比 Inspector 与官方 SDK client 兼容性。SDK typed client 默认第一页限制为 starter tools，完整 all-toolset 通过 cursor 分页继续发现。

## 目标

- 为 Agent 提供稳定、强类型、任务导向的 MCP tools。
- 继续保持 `run_command` 作为唯一业务入口，避免 CLI、stdio、MCP 三套逻辑分叉。
- 在 stdio 与 MCP 会话中共享 session cache、dedupe 和 token ledger。
- 默认 fixture/dry-run 友好，不把真实 Keepa 请求放进默认测试或隐式执行路径。
- 让大响应通过 Agent view、chunk manifest、evidence index 和 `--from-cache` 式引用来消费，减少上下文污染。

## 非目标

- 不在第一阶段暴露所有 Keepa API 端点。
- 不让 MCP server 解析或执行 CLI 字符串。
- 不在 MCP tool 中直接实现 Keepa HTTP 请求逻辑。
- 不默认持久化 session cache；第一阶段只做进程内缓存，避免泄露 token 或 raw body。
- 不在默认 MCP tools 中暴露有副作用 tracking 写操作。

## 目录组织

```text
keepa_cli/
  agent/
    __init__.py
    mcp.py          # MCP JSON-RPC stdio transport，薄协议适配层
    prompts.py      # MCP prompts，提供产品/类目/对比/项目上手工作流起手式
    resources.py    # MCP resources 与 chunk/output resource manifest
    session.py      # AgentSession、cache_key、dedupe、budget ledger
    stdio.py        # 复用 AgentSession 的 JSON Lines transport
    tools.py        # MCP tool registry、schema、service command mapping
```

分层职责：

- `tools.py`：定义工具名、描述、输入 schema、输出 schema 摘要、确认策略和 service command 映射。
- `session.py`：维护本进程会话状态，包括 cache、dedupe、token ledger、blocked actions。
- `mcp.py`：只处理 JSON-RPC：`initialize`、`tools/list`、`tools/call`、`resources/list`、`resources/templates/list`、`resources/read`、`prompts/list`、`prompts/get` 和协议错误。
- `prompts.py`：定义不执行请求的 Agent 起手式，帮助不同 MCP 客户端稳定启动 product/category/deal/project workflow。
- `resources.py`：暴露 schema、fixture manifest、cassette 指南、最近 evidence、resource templates，并把大响应 chunk/output path 转为 `keepa://...` resource 引用。
- `stdio.py`：继续提供现有 JSON Lines 协议，但调用同一个 `AgentSession`。
- `service.py`：继续承载业务命令分发，MCP 不绕过 `run_command`。

## 初始 Tool Surface

第一阶段只暴露高价值、低歧义、Agent 常用 tools：

| MCP tool | service command | 目的 | 默认风险 |
| --- | --- | --- | --- |
| `products_get` | `products.get` | 单 ASIN/少量 ASIN 产品研究，含 `risk_taxonomy` 与 `research_graph` | 低；`offers`、`rating`、`buybox` 可能增量成本 |
| `products_compare` | `products.compare` | 多 ASIN deal/research 横向对比，含统一风险汇总与合并图谱 | 低；`offers` 可能增量成本 |
| `categories_search` | `categories.search` | 关键词找候选 category | 低 |
| `categories_products` | `categories.products` | category 生成商品候选 | 高；真实请求需确认 |
| `categories_finder_selection` | `categories.finder-selection` | 本地生成 Finder selection scaffold | 低，本地计算 |
| `finder_query` | `finder.query` | Product Finder selection 查询 | 中高；真实请求需确认 |
| `deals_query` | `deals.query` | Deals selection 查询，返回 deal/product 图谱 | 中 |
| `sellers_get` | `sellers.get` | Seller 与 storefront ASIN 研究 | 低 |
| `bestsellers_get` | `bestsellers.get` | Best Sellers 原始榜单 | 高；真实请求需确认 |
| `topsellers_list` | `topsellers.list` | Top Sellers 原始榜单 | 高；真实请求需确认 |
| `workflow_plan` | `workflow.plan` | 本地生成 Agent 执行图 | 低，本地计算 |
| `research_graph_merge` | `research_graph.merge` | 合并 category/products/compare/seller/deals 输出中的研究图 | 低，本地计算 |
| `research_brief_export` | `research_brief.export` | 从 merged graph 或多份 Agent payload 导出调研 brief | 低，本地计算 |
| `docs_index` | `docs.index` | 列出 zread/schema/evidence/fixture 文档资源 | 低，本地读取 |
| `docs_read` | `docs.read` | 按 URI 或 zread 页面 slug 读取文档资源 | 低，本地读取 |
| `context_policy` | `context.policy` | 读取 profile policy、roots、tool gating 与 live Keepa 安全状态 | 低，本地计算 |
| `resolve_research_target` | `research.target.resolve` | 将模糊输入解析为 ASIN、类目、seller、fixture、evidence 或关键词候选 | 低，本地计算 |
| `query_research_context` | `research.context.query` | 基于目标列出本地 schema、fixture、evidence、zread、cache 资源 | 低，本地计算 |

当前 MCP 默认只返回 `research` toolset，避免 `tools/list` 一次暴露过多 schema。可在 `tools/list.params.toolset` 中显式选择：

- `research`：context policy、target resolution、context query、产品、类目、本地 Finder scaffold、Finder、Deals、Seller、榜单、workflow plan、docs index/read、research graph merge、research brief export。
- `docs`：暴露 `docs_index`、`docs_read`、`context_policy`、`query_research_context`，用于不支持 `resources/read` 的客户端。
- `audit`：`audit_cost`、`cassettes_sanitize`、`cassettes_promote`。
- `reports`：`research_graph_merge`、`reports_build`、`browse_snapshot`、`figures_research`、`research_brief_export`，只处理本地文件。
- `tracking-readonly`：`tracking_list`、`tracking_list_names`、`tracking_get`、`tracking_notifications`、`audit_cost`，不暴露 add/remove/webhook。
- `all`：显式全量发现，用于调试和 schema 生成。

未知 toolset 会返回 JSON-RPC `Invalid toolset`，不静默回退。tracking 写操作仍不暴露给 MCP。

`tools/list.params.allow_tools` 与 `tools/list.params.exclude_tools` 可进一步收窄单次发现面。`tools/list.params.profile` 支持 `offline_fixture_only`、`dry_run_default`、`live_read_allowed`、`tracking_readonly`、`fixture_curation`；真实调研使用 `live_read_allowed`。`offline_fixture_only` 与 `dry_run_default` 下，产品、类目、Finder、Deals、榜单等研究工具仍可发现，但 `tools/call` 必须传 `fixture` 或 `dry_run`，否则返回结构化 `profile_requires_fixture_or_dry_run`。调研 Agent 建议先只暴露 `context_policy`、`resolve_research_target`、`query_research_context`、`workflow_plan`，确认目标和预算后再放开具体产品、类目、deals 或 seller 工具。

`tools/list.params.profile` 可把调研阶段显式传给 MCP server。当前 profile 包括 `offline_fixture_only`、`dry_run_default`、`live_read_allowed`、`tracking_readonly`、`fixture_curation`。返回的每个 tool 都带 `x-keepa.active` 与 `x-keepa.inactive_reason`；客户端若继续用同一 `profile` 调用 inactive tool，`tools/call` 会返回结构化 `inactive_tool`，不会进入 service 执行层。这样 Agent 可以在 fixture/dry-run 测试、真实 live read、tracking 只读和 fixture 整理阶段共享同一套工具目录，同时用执行前 guard 阻断安全 profile 下的真实请求。

## Tool 命名与参数策略

工具名使用 `<resource>_<action>`，不再带 `keepa.` 前缀；命名仍保留下划线，避免 action 再分层造成歧义。

参数只接受结构化 JSON，不接受 CLI 字符串：

```json
{
  "asin": "B0D8W1YVBX",
  "domain": "US",
  "full": true,
  "agent_view": true,
  "view": "summary",
  "history_limit": 10,
  "temporal_window_days": [7, 30, 90, 180, 365],
  "fixture": "product_agent_view_B0TEST.json"
}
```

字段命名使用 snake_case。`tools.py` 负责映射到 `run_command` 当前接受的参数别名，CLI 层继续保持 argparse 风格。

## MCP 响应形状

`tools/call` 成功响应应同时提供 `structuredContent` 和 `content`：

```json
{
  "structuredContent": {
    "ok": true,
    "command": "products.get",
    "cache_key": "products.get:4e3c...",
    "cache_hit": false,
    "budget_ledger": {
      "session_estimated": 1,
      "session_consumed": 1,
      "remaining_limit": null,
      "blocked_actions": []
    },
    "data": {}
  },
  "content": [
    {
      "type": "text",
      "text": "{\"ok\":true,\"command\":\"products.get\"}"
    }
  ],
  "isError": false
}
```

错误响应：

```json
{
  "structuredContent": {
    "ok": false,
    "command": "categories.products",
    "error": {
      "kind": "confirmation_required",
      "message": "request requires explicit confirmation"
    },
    "budget_ledger": {}
  },
  "content": [
    {
      "type": "text",
      "text": "{\"ok\":false,\"error\":{\"kind\":\"confirmation_required\"}}"
    }
  ],
  "isError": true
}
```

规则：

- `structuredContent` 保留完整 envelope、cache、ledger 和 evidence index。
- `content[0].text` 是同一结果的紧凑 JSON fallback，不加 ANSI，不加解释性自然语言。
- 大 raw body 不直接放进 `content`；优先返回 Agent view、chunk manifest 或 cache key。
- 所有 secret-like 字段继续走现有 redaction 规则。

## MCP Resources 与大响应分块

MCP resources 承载稳定文档和大响应按需读取入口，避免 `tools/list` 被文档内容污染：

| Resource URI | 内容 | 用途 |
| --- | --- | --- |
| `keepa://schema/products-agent-view` | `docs/schema/products.agent-view.schema.json` | 外部 Agent 校验产品 Agent 视图形状 |
| `keepa://schema/risk-taxonomy` | `docs/schema/risk-taxonomy.schema.json` | 外部 Agent 校验稳定风险枚举、severity 与 evidence path |
| `keepa://schema/workflow-runtime-contract` | `docs/schema/workflow-runtime-contract.schema.json` | 外部 MCP client 校验 workflow runtime contract |
| `keepa://fixtures/manifest` | `evidence/manifest.csv` | 查 fixture/evidence 是否已有离线样本 |
| `keepa://guides/cassette-promotion` | 内置 cassette promote 指南 | live 响应脱敏提升与 parity 验证流程 |
| `keepa://evidence/recent` | 最近 evidence 摘要 JSON | 快速了解近期验证与变更 |
| `keepa://context/policy` | profile policy、roots、tool gating、live Keepa 状态 | 调研 Agent 的第一读取入口 |
| `keepa://tools/index` | toolset 与 tool schema 索引 | 先发现工具，再按需读取单个 schema |
| `keepa://prompts/index` | prompt 索引 | 发现可复用 Agent 起手式 |
| `keepa://zread/wiki/current` | 当前 zread 版本与公开文档链接 | Agent 项目上手入口 |
| `keepa://zread/wiki/toc` | `.zread/wiki` 当前目录 | 按需选择 wiki 页面 |
| `keepa://zread/wiki/pages` | 紧凑页面清单与 resource URI | 避免 Agent 拼本地路径 |

资源模板用于按规则寻址本地资产：

- `keepa://schema/{name}`：按稳定名称读取 schema，支持 `products-agent-view`、`risk-taxonomy` 与 `workflow-runtime-contract`。
- `keepa://fixtures/{name}`：按文件名读取双份 fixture 中的 JSON 样本。
- `keepa://cache-key/{command}/{encoded_params}`：对 base64url JSON 参数预览 `AgentSession` cache key，不读取会话内存。
- `keepa://workflow/{encoded_params}/policy`：对 base64url JSON `workflow.plan` 参数读取紧凑执行策略，返回 `workflow_policy`、`totals` 与 `step_summary`，避免资源优先客户端为了 profile 和确认策略加载完整 plan。
- `keepa://research/{cache_key}`：读取同一 MCP session 内缓存响应的审计摘要，便于 Agent 回查 provenance、evidence、ledger 与 graph summary。
- `keepa://research/{cache_key}/brief`：读取同一 MCP session 内 `research_brief.export` 的完整 brief。
- `keepa://research/{cache_key}/graph`：读取同一 MCP session 内 `research_brief.export` 的图谱摘要与输入摘要。
- `keepa://workflow/runtime-contract`：列出支持 `resource_uri`、`artifact`、`workflow_inputs` 等 runtime 参数的 MCP tools、参数名与 `missing_inputs` 约定，并通过 `schema_resource_uri=keepa://schema/workflow-runtime-contract` 指向可校验 schema，便于外部 Agent 不加载全部 schema 也能安全接续工作流产物。
- `keepa://graphs/{root}`：按 graph root 在 session cache 和本地 fixture 中查图谱来源，便于审计合并图谱的输入与证据。
- `keepa://toolsets/{toolset}`：按 toolset 读取紧凑 manifest，包含工具名、service command、分组和单 tool 资源 URI。
- `keepa://tools/{name}`：按 MCP tool 名读取完整 input/output schema 与执行说明。
- `keepa://prompts/{name}`：按 MCP prompt 名读取 prompt 定义；无必填参数时附带渲染结果。
- `keepa://asin/{asin}/fixture`：查找文件名包含 ASIN 的本地 fixture 候选。
- `keepa://evidence/{encoded_logical_path}`：按 manifest 中的 logical path 读取 evidence task log。
- `keepa://zread/wiki/page/{slug_or_file}`：按 zread slug、标题 slug 或 markdown 文件名读取 wiki 页面。
- `keepa://chunk/<base64-path>`：由 `data.chunks[*].path` 派生，通常是产品 Agent view section JSON。
- `keepa://output/<base64-path>`：由 `output.path` 派生，通常是报告、graph 或大 body 输出。

读取限制：

- 静态资源从项目根读取。
- 动态资源只允许项目根或系统临时目录下的文件，防止 MCP 客户端任意读盘。
- 单个 resource text 读取上限为 1 MB，超出会截断并标记。

当 tool payload 包含 chunk/output 文件时，`structuredContent` 仍保持完整，`content[0].text` 会通过 `compact_payload_for_mcp()` 压缩：

```json
{
  "data": {
    "products": [
      {
        "agent_brief": {},
        "identity": {},
        "data_quality": {},
        "risk_taxonomy": {},
        "selection_signals": {},
        "next_actions": [],
        "research_graph_summary": {}
      }
    ]
  },
  "mcp_resource_manifest": {
    "strategy": "summary_with_resource_refs",
    "resource_count": 4,
    "resources": [
      {"uri": "keepa://chunk/...", "type": "chunk", "name": "identity"}
    ]
  }
}
```

这条规则让只支持 text fallback 的 Agent 也能先看摘要，再按需读取 heavy sections；支持 `structuredContent` 的客户端则直接读取完整结构化结果。

## MCP Prompts 与文档入口

MCP prompts 用来减少 Agent 启动时的路线漂移，不执行 Keepa 请求：

- `product_research`：单品研究，先 workflow plan，再 `products_get` 的低成本 full/agent view。
- `category_research`：关键词找类目、生成 Finder scaffold，并明确 `categories_products` 需要确认。
- `deal_compare`：多 ASIN deal 对比，强调 `selection_signals`、`risk_taxonomy` 与 evidence。
- `project_onboarding`：先读 zread wiki、schema 与 recent evidence，再决定修改范围。

公开文档入口分两层：

- GitHub Pages：`https://cunuo.github.io/Keepa-cli/`，稳定链接，适合 README 和 GitHub About。
- zread：`https://zread.ai/cuNuo/Keepa-cli`，可读性更强，适合架构浏览；同一份快照也通过 `keepa://zread/wiki/...` 暴露给 Agent。

## Session Cache 与 Dedupe

`AgentSession` 维护进程内缓存：

```python
cache_key = f"{command}:{sha256(normalized_params_without_runtime_flags)}"
```

归一化规则：

- 排除 `from_cache`、`yes` 等运行时控制字段。
- JSON key 排序，数组顺序保留。
- token、authorization、api key 类字段不进入 cache key 明文。

调用策略：

- 正常请求成功后，响应增加 `cache_key`，并存入 session cache。
- 请求携带 `from_cache` 时，只读取 session cache，不调用 `run_command`，并返回 `cache_hit=true`。
- 相同 command + params 在同一 session 内重复调用时可 dedupe，直接返回缓存副本并标记 `cache_hit=true`。
- fixture/dry-run 也可缓存，便于 Agent eval 稳定复用。

缓存边界：

- 第一阶段不跨进程持久化。
- 不缓存 `ok=false` 的错误响应，除非后续有明确 retry 策略。
- 不缓存含明显副作用的命令。
- 缓存返回值必须经过 redaction，不能保留明文 token。

## Token Ledger

`AgentSession` 同时维护本轮预算账本：

```json
{
  "budget_ledger": {
    "session_estimated": 57,
    "session_consumed": 51,
    "remaining_limit": 199,
    "blocked_actions": []
  }
}
```

字段语义：

- `session_estimated`：本会话累计 estimated tokens。
- `session_consumed`：从真实响应 token bucket 或 fixture 模拟值累计的 consumed tokens；没有真实值时保守使用 estimated。
- `remaining_limit`：若配置了会话上限则返回剩余预算，否则为 `null`。
- `blocked_actions`：因确认、预算或副作用策略被阻断的 action 摘要。

账本更新顺序：

1. 调用前用 `estimate_request_budget` 记录 estimated/worst-case。
2. 若需要确认且未确认，写入 `blocked_actions`，不调用 service。
3. 调用成功后读取 `token_bucket.tokens_consumed`；缺失时使用 estimated。
4. 缓存命中不增加 consumed，可增加 `cache_hits` 统计字段。

## Confirmation Policy

MCP server 不能交互等待用户输入。需要确认时，直接返回结构化错误：

```json
{
  "kind": "confirmation_required",
  "details": {
    "resume_with": {
      "tool": "categories_products",
      "params": {"yes": true}
    },
    "estimated_tokens": 50,
    "worst_case_tokens": 50
  }
}
```

确认绕过条件与 stdio 保持一致：

- `yes=true`
- `dry_run=true`
- `fixture` 存在

高风险写操作即使传 `yes=true`，也应在 tool registry 中标记 `requires_explicit_toolset=true`，第一阶段不暴露。

## Evidence 与 Provenance

MCP 输出必须延续现有 Agent profile：

- `agent_brief`
- `data_quality`
- `selection_signals`
- `risk_taxonomy`
- `research_graph`
- `next_actions`
- `evidence_index`
- `provenance`

`risk_taxonomy` 使用稳定枚举，当前已知 code 为 `data_missing`、`price_unstable`、`rank_declining`、`low_review_count`、`offer_competition_high`、`buybox_missing`、`category_mismatch`。每个 item 必须给出 `severity`、`reason`、`evidence_path`，可补充 `metric` 与 `follow_up`，让 Agent 能做确定性断言而不是解析自然语言。MCP resource `keepa://schema/risk-taxonomy` 暴露同一契约，外部 Agent 可以按 schema 校验 compare rows、brief 和下游报告中的风险语义。

`research_graph` 使用轻量实体关系结构：产品命令的 `nodes` 包含 `product`、`brand`、`manufacturer`、`category`、`seller`、`variation` 等类型；category/finder/deals/seller/ranking 命令还会输出 `search_term`、`selection`、`deal_set`、`deal`、`seller_request`、`seller_ranking`。`products.compare` 会额外输出合并后的 `research_graph` 与 `risk_summary`；`categories.search/products`、`finder.query`、`deals.query`、`sellers.get`、`bestsellers.get`、`topsellers.list` 都提供同名字段，便于跨命令拼接实体记忆。

`research_graph.merge` / `research_graph_merge` 负责把多条命令结果合并为单个研究图。它支持文件输入和 inline graph/payload 输入，递归抽取所有 `research_graph`，合并时去重节点/边，添加 `research_graph` root 节点与 `includes_graph` 边，并返回 `summary.entity_counts`、`sources`、`diagnostics`、`diff`、`data_quality` 和 `evidence_index`。`sources` 给出 `source_weight/confidence`，`diagnostics` 记录重复节点、孤立节点、label/type 冲突和 source weight 范围。`diff` 给出冲突节点的 variant 列表与 resolution；`--prefer-source` / `prefer_source` 可指定 source index 或 source root，帮助 Agent 在多来源 label/type 不一致时做确定性选择。典型链路是 `categories.search -> categories.products -> products.compare -> sellers.get`。

`research_brief.export` / `research_brief_export` 直接消费 merged graph JSON、多个 Agent payload 文件或 inline payload。它输出 `view=research_brief_export`，核心字段包括 `decision_summary`、`risk_summary`、`entity_graph_summary`、`follow_up_plan`、`evidence_links`、`data_quality` 和 `recommended_read_order`。MCP tool 调用成功后会进入同一 `AgentSession` cache，调研 Agent 可用 `keepa://research/{cache_key}/brief` 回读完整 brief，用 `keepa://research/{cache_key}/graph` 只回读图谱摘要，避免把所有原始 payload 再塞进上下文。

`reports.build` 直接消费 merged graph JSON：Markdown 输出追加 SVG figure、实体和关系表，JSON 输出增加 `figures` 与 `research_graph_report`。这让 Agent 可以先用 `research_graph.merge` 固化实体图，再用 `research_brief.export` 固化机器可读 handoff，最后按需要用报告工具生成面向人类或下游系统的证据摘要；审计时通过 `keepa://graphs/{root}` 查图谱来源，通过 `keepa://research/{cache_key}` 查同一 MCP session 的缓存结果和 budget ledger。`keepa://research/{cache_key}/figures` 会从 session cache 生成完整 SVG manifest；`keepa://research/{cache_key}/figures/{figure_set}` 可只生成 `history`、`compare` 或 `audit` 图表组；SVG 本体继续以 `keepa://output/...` 暴露，避免把大图直接塞进 tools/list 或普通文本 content。

新增 MCP 层 provenance：

```json
{
  "mcp": {
    "server": "keepa",
    "tool": "products_get",
    "transport": "stdio",
    "session_cache_key": "products.get:4e3c...",
    "cache_hit": false
  }
}
```

CLI fallback 仍保留在 `next_actions.cli`，但 Agent 优先执行 `tool + params`。

## 与 CLI / stdio 的关系

三种入口共享同一 service：

```text
CLI argparse  -> run_command -> envelope
stdio JSONL   -> AgentSession -> run_command -> events
MCP JSON-RPC  -> AgentSession -> run_command -> tool result
```

约束：

- CLI 是人类和 CI 入口。
- stdio 是轻量 Agent 长会话入口。
- MCP 是跨 Agent 工具入口。
- 三者不得复制 Keepa API request 构造逻辑。

## 测试矩阵

新增测试应覆盖行为，而不只是命令成功：

- `tests/test_mcp.py`
  - `initialize` 返回 server info 和 protocol version。
  - `tools/list` 默认只返回 research，并能按 `audit/business/reports/tracking-readonly/all` 过滤。
  - `tools/call categories_search` 使用 fixture 返回 `category_candidates`。
  - `tools/call categories_finder_selection` 本地生成 Finder scaffold，不累计 token。
  - `tools/call deals_query` 使用 fixture 返回 deal/product `research_graph`。
  - `tools/call products_compare` 使用 fixture 返回风险汇总与合并图谱。
  - `tools/call research_graph_merge` 合并 inline graph/payload。
  - `tools/call research_brief_export` 导出 decision/risk/graph/follow-up/evidence brief。
  - `resources/list/read` 暴露 schema、manifest、cassette 指南和最近 evidence。
  - `resources/templates/list` 暴露 schema、fixture、workflow policy、chunk 和 output resource URI 模板。
  - 大响应 chunk tool 调用在 text fallback 中返回 `mcp_resource_manifest`。
  - 未知 tool 返回 JSON-RPC error。
  - 高成本 tool 无 `yes` 且无 fixture 时返回 `confirmation_required`。
- `tests/test_agent_session.py`
  - 同 params 生成稳定 `cache_key`。
  - 第二次相同调用命中 cache，不重复累计 consumed。
  - `from_cache` 可直接复用上一响应。
  - ledger 累计 estimated/consumed/blocked_actions。
- `tests/agent_eval_fixtures/`
  - 关键词找类目并给候选。
  - 比较 3 个 ASIN 的 deal view。
  - 判断是否需要补 offers。
  - 从 category 生成 finder scaffold。
  - 合并 category/compare/seller research graph。
  - MCP resources、chunk resource manifest、长链路 budget ledger。
  - `next_actions` 的 `tool + params` 可被 service 或 MCP registry 校验。

所有测试默认 fixture/dry-run，不访问真实 Keepa API。

## Client 示例

`scripts/mcp_example_support.py` 提供面向外部 Agent 的最小 MCP client helper，只依赖 Python 标准库。示例脚本启动 `python -m keepa_cli --mcp`，保持同一 stdio 进程以复用 `AgentSession` cache 和 `budget_ledger`。

`scripts/mcp_agent_workflow_example.py` 按以下顺序执行：

1. `initialize` 与收窄后的 `tools/list`。
2. `tools/call workflow_plan` 读取执行图、预算和 resource templates。
3. `resources/read keepa://schema/risk-taxonomy` 获取风险枚举与 required fields。
4. `tools/call categories_products` 使用 fixture 生成候选 ASIN 与 `cache_key`。
5. `tools/call products_compare` 传入 `keepa://research/{cache_key}`，由 workflow resolver 推导 ASIN。
6. client 侧校验 compare payload 中的 `risk_taxonomy.codes/items/severity/evidence_path`。
7. `tools/call research_graph_merge` 传入 `keepa://research/{compare_cache_key}/graph`。
8. `tools/call research_brief_export` 与 `reports_build` 传入 merged graph 的 research resource。

`scripts/mcp_tracking_audit_example.py` 演示 `tracking-audit` 计划的只读边界：

1. 使用 `tools/list toolset=tracking-readonly profile=tracking_readonly`。
2. 调用 `workflow_plan name=tracking-audit`，确认 recommended toolset/profile 与 confirmation steps。
3. 用 fixture 调用 `tracking_list`，再把 `keepa://research/{cache_key}` 传给 `tracking_get` 与 `audit_cost`，让 resolver 推导 tracked ASIN。
4. 验证 `tracking_add` 这类写工具在 MCP 中是 unknown tool，说明写路径没有暴露。

`scripts/mcp_report_research_example.py` 演示 `report-research` 计划的纯本地报告链路：

1. 使用 `tools/list toolset=reports profile=offline_fixture_only`。
2. 调用 `workflow_plan name=report-research`，确认 0 token 本地链路。
3. 从本地 compare fixture 调用 `research_graph_merge` 并写入临时 graph JSON。
4. 通过 merged graph 的 `resource_uri` 导出 `research_brief_export` 和 `browse_snapshot`。
5. 调用 `figures_research`，读取 MCP text fallback 里的 `mcp_resource_manifest.resources[]`，把 `image/svg+xml` 的 `keepa://output/...` 作为报告图片资源。
6. 通过 `workflow_context.steps/outputs` 把 graph artifact 交给 `reports_build`，展示 Agent 常见状态容器如何被 resolver 接续。

运行：

```powershell
.\.venv\Scripts\python.exe scripts\mcp_agent_workflow_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_tracking_audit_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json
.\.venv\Scripts\python.exe scripts\mcp_report_research_example.py --json --save-summary evidence\runtime\mcp-report-summary.json
```

三个示例统一支持 `--save-summary <path>`；评测与示例共用 `keepa_cli.risk_schema`，避免 `risk_taxonomy` schema 子集校验在不同入口漂移。

输出只保留 tool names、cache/resource URI、风险校验结果、graph counts、brief one-line、report graph counts 与最终 ledger，适合作为 Agent 或自研 MCP 客户端的接入样板。

## 实施顺序

1. 新增 `agent/tools.py`，冻结初始 5 个 MCP tool schema。（已完成）
2. 新增 `agent/session.py`，实现 cache key、dedupe、ledger。（已完成）
3. 改造 `agent/stdio.py`，让 stdio 复用 `AgentSession`，保持旧输出兼容。（已完成）
4. 新增 `agent/mcp.py`，实现最小 JSON-RPC stdio server。（已完成）
5. 在 `cli.py` 增加 `--mcp` 入口，避免扩展过多 argparse 子树。（已完成）
6. 更新 `capabilities`，暴露 MCP server 启动方式和 tool schema 版本。（已完成）
7. 补测试、README、`docs/agent-contract.md`。（已完成）
8. 落地 `research_graph`、统一 `risk_taxonomy`，并让 evaluation specs 断言 Agent 语义质量。（已完成）
9. 落地 cassette promote workflow：真实响应 -> sanitize -> 双份 fixture -> manifest。（已完成）
10. 落地 `cassettes.promote_and_verify` / `cassettes_promote_and_verify`：promote 后检查 fixture parity，并可选运行 Agent eval fixtures。（已完成）
11. 落地 MCP toolset 动态过滤：`research/audit/business/reports/tracking-readonly/all`。（已完成）
12. 把 `research_graph` 扩展到 category/finder/deals/seller/ranking 输出。（已完成）
13. 落地 `research_graph.merge` 与 `research_graph_merge`，合并 category -> products -> compare -> seller 研究图。（已完成）
14. 落地 `research_brief.export` 与 `research_brief_export`，把 merged graph 或多 payload 汇总为调研 Agent handoff。（已完成）
15. 落地 MCP resources 与 chunk/output resource manifest，大响应 text fallback 只返回摘要和资源引用。（已完成）
16. 扩展 Agent eval，断言 graph merge、risk taxonomy、next_actions 可执行性和长链路 budget ledger。（已完成）
17. 将 session profile 与 `workflow.plan` 联动，输出 recommended profile、inactive tools、profile switch points、确认策略和 budget ledger seed。（已完成）
18. 落地 `keepa://workflow/{encoded_params}/policy`，让资源优先客户端用 base64url JSON 计划参数读取紧凑 `workflow_policy` 与步骤摘要。（已完成）
19. 扩展 `workflow.plan` 到 `report-research` 与 `tracking-audit`，让本地报告链路和 tracking-readonly 审计链路也输出 profile/toolset/ledger 策略。（已完成）
20. 扩展 `workflow.plan` 的结构化输入/产物契约：新增 `workflow_inputs`、`artifacts`、`resource_templates`、step `input_refs` 与 `artifact_refs`，并用 resource-first Agent eval 固化 `context policy -> resolve target -> workflow policy resource -> tools/list filtered -> execute` 起手链路。（已完成）
21. 落地 workflow artifact resolver：MCP `tools/call` 可用 `resource_uri`、`resource_uris`、`artifact`、`artifacts`、`workflow_inputs` 与 `workflow_context` 把 `keepa://research/{cache_key}`、graph resource、output path、`artifact.output.path`、`workflow_context.steps/outputs/results` 或 inline artifact 自动解析为下游工具参数；缺依赖时返回结构化 `missing_inputs`，成功时返回 `data.workflow_resolution` 供 Agent 审计来源；`keepa://workflow/runtime-contract` 暴露 resolver tool 清单与参数契约。（已完成）

## 迁移风险

- MCP 客户端对 `structuredContent` 支持不一致：用 JSON text fallback 降级。
- tool schema 太大导致上下文污染：默认只暴露 `research` toolset，审计、报告、tracking 只读工具需要显式选择。
- session cache 意外缓存 live raw body：第一阶段只进程内、只缓存 redacted envelope。
- CLI 与 MCP 参数别名漂移：所有映射集中在 `agent/tools.py`，测试直接验证 tool params 到 service command。
- 预算账本和真实 token 消耗不一致：真实响应优先，缺失时显式标记 `consumed_source=estimated_fallback`。

## 后续最佳方向

当前最适合继续完善的是：

1. 为 `reports` 与 `tracking-readonly` 增加 Agent evaluation fixtures，断言本地文件输出、只读 tracking 参数和 ledger。（已完成）
2. 继续扩展 MCP resource templates，例如按 `cache_key`、ASIN、graph root 与 workflow 参数查询缓存命中、图谱摘要和执行策略。（cache-key/ASIN/evidence/graph root/session research/workflow policy 已完成）
3. 给 `research_graph.merge` 增加图谱 diff 视图和可选 source preference，帮助 Agent 在冲突来源中做确定性选择。（已完成）
4. session profile 已与 `workflow.plan` 联动：`workflow_policy` 输出 recommended profile、allowed/inactive tools、profile switch points、确认策略、cache policy 和 budget ledger seed。
5. workflow policy resource template 已完成，资源优先客户端可不加载完整 plan 先读取执行策略。
6. `workflow.plan` 覆盖 `category-research`、`product-research`、`report-research`、`tracking-audit`、`inventory-audit`、`velocity-research` 与 `market-opportunity`；其中 report 计划固定走 `reports` + `offline_fixture_only`，tracking 计划固定走 `tracking-readonly` + `tracking_readonly`，business 计划固定走 `business` + `offline_fixture_only`。
7. `workflow.plan` 已输出 `workflow_inputs`、`artifacts` 与 step 输入/产物引用，Agent 不需要再解析 CLI 字符串来连接图谱、brief、报告和 tracking 只读产物。
8. MCP workflow resolver 已能把 session cache/resource/path/inline artifact/output.path 以及嵌套 `workflow_context.steps/outputs/results` 转为实际工具参数，并用 `missing_inputs` 明确提示缺失依赖。
9. 后续按需增加远程 MCP transport 或官方 Python SDK 适配。

这样协议层、证据沉淀和语义图谱已经分层稳定，后续扩展不会继续推高 `service.py` 和 MCP registry 的耦合。
