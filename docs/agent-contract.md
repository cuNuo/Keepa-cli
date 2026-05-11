# Keepa CLI Agent 协议契约

更新时间：2026-05-10 23:30 +08:00

## 1. 入口约定

`keepa-cli` 和 `kc` 是完全等价的两个入口，均指向同一个 Python 函数：

```toml
[project.scripts]
keepa-cli = "keepa_cli.cli:main"
kc = "keepa_cli.cli:main"
```

当前 MVP 也支持模块方式调用：

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
.\.venv\Scripts\python.exe -m keepa_cli --json domains list
.\.venv\Scripts\python.exe -m keepa_cli --stdio
.\.venv\Scripts\python.exe -m keepa_cli --mcp
```

安装到本项目虚拟环境后可调用：

```powershell
.\.venv\Scripts\keepa-cli.exe --json doctor
.\.venv\Scripts\kc.exe --json doctor
```

## 2. JSON Envelope

`--json` 模式下 stdout 只输出一个 JSON envelope，不输出 ANSI、日志或明文凭据。

成功响应：

```json
{
  "ok": true,
  "command": "doctor",
  "request": {
    "transport": "cli"
  },
  "token_bucket": {},
  "data": {}
}
```

错误响应：

```json
{
  "ok": false,
  "command": "request.get",
  "error": {
    "kind": "api_error",
    "message": "failed with key=[REDACTED]"
  },
  "token_bucket": {}
}
```

规则：

- `ok=true` 代表命令级成功；空结果仍然可以成功。
- `ok=false` 时 `error.kind` 是 Agent 的主要分支字段。
- `token_bucket.estimated` 用于执行前预算；真实 API 响应会继续映射 `tokens_left`、`tokens_consumed`、`refill_rate`、`refill_in_ms`。
- 所有 `key`、`api_key`、`apikey`、`token`、`authorization` 字段必须打码。

## 3. stdio JSON Lines

`--stdio` 用于 Agent 长会话。stdin 每行一个请求 JSON，stdout 每行一个事件 JSON。

输入：

```json
{"id":"1","method":"doctor","params":{}}
```

输出事件顺序：

```json
{"id":"1","event":"started","method":"doctor"}
{"id":"1","event":"budget_estimated","estimated_tokens":0,"worst_case_tokens":0,"requires_confirmation":false,"components":[],"notes":[]}
{"id":"1","event":"response","payload":{"ok":true}}
{"id":"1","event":"done"}
```

高成本命令不得阻塞等待人工输入，必须返回结构化确认错误：

```json
{
  "id": "2",
  "event": "response",
  "payload": {
    "ok": false,
    "command": "bestsellers.get",
    "error": {
      "kind": "confirmation_required",
      "message": "request requires explicit confirmation because it may consume significant Keepa tokens",
      "details": {
        "resume_with": "--yes",
        "estimated_tokens": 50,
        "worst_case_tokens": 50
      }
    },
    "token_bucket": {}
  }
}
```

## 4. MCP JSON-RPC stdio

`--mcp` 用于 Agent 与其他 MCP 客户端。stdin 每行一个 JSON-RPC 请求，stdout 每行一个 JSON-RPC 响应。

列出工具：

```powershell
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | kc --mcp
```

调用工具：

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "keepa.products_get",
    "arguments": {
      "asin": "B001GZ6QEC",
      "domain": "US",
      "full": true,
      "agent_view": true,
      "view": "summary",
      "fixture": "product_B001GZ6QEC.json"
    }
  }
}
```

首批工具：

- `keepa.products_get` -> `products.get`
- `keepa.products_compare` -> `products.compare`
- `keepa.categories_search` -> `categories.search`
- `keepa.categories_products` -> `categories.products`
- `keepa.categories_finder_selection` -> `categories.finder-selection`
- `keepa.finder_query` -> `finder.query`
- `keepa.deals_query` -> `deals.query`
- `keepa.sellers_get` -> `sellers.get`
- `keepa.bestsellers_get` -> `bestsellers.get`
- `keepa.topsellers_list` -> `topsellers.list`
- `keepa.workflow_plan` -> `workflow.plan`
- `keepa.find_fast_movers` -> `business.find-fast-movers`
- `keepa.inventory_audit` -> `business.inventory-audit`
- `keepa.market_opportunity` -> `business.market-opportunity`
- `keepa.agent_profile_generate` -> `agent.profile.generate`
- `keepa.research_graph_merge` -> `research_graph.merge`
- `keepa.research_brief_export` -> `research_brief.export`
- `keepa.docs_index` -> `docs.index`
- `keepa.docs_read` -> `docs.read`
- `keepa.context_policy` -> `context.policy`
- `keepa.resolve_research_target` -> `research.target.resolve`
- `keepa.query_research_context` -> `research.context.query`
- `keepa.audit_cost` -> `audit.cost`

MCP tool 只接受结构化 JSON 参数，不接受 CLI 字符串。返回同时包含 `structuredContent` 和 `content[0].text` JSON fallback：

```json
{
  "structuredContent": {
    "ok": true,
    "command": "products.get",
    "cache_key": "products.get:...",
    "cache_hit": false,
    "budget_ledger": {
      "session_estimated": 1,
      "session_consumed": 1,
      "remaining_limit": null,
      "blocked_actions": [],
      "cache_hits": 0,
      "consumed_source": "token_bucket"
    },
    "data": {}
  },
  "content": [{"type": "text", "text": "{\"ok\":true}"}],
  "isError": false
}
```

同一 MCP/stdin 会话内会自动缓存成功响应。重复的 command+params 会返回 `cache_hit=true`，也可以用 `from_cache` 显式复用 `cache_key`。该层是进程内 Agent session cache，用于一次长会话内去重。

`tools/list` 支持 `profile` 参数：`offline_fixture_only`、`dry_run_default`、`live_read_allowed`、`tracking_readonly`、`fixture_curation`。返回的 tool schema 会在 `x-keepa.active` 标明当前 profile 是否允许该工具；`tools/call` 参数也可带同一 `profile`，若工具不允许，会返回 `error.kind=inactive_tool`，并在执行 service 前停止。

live GET JSON 响应另有 SQLite 持久缓存，默认路径来自平台缓存目录，可用 `KEEPA_CLI_CACHE_PATH` 或 `cache stats --cache-path <path>` 覆盖审计路径。TTL 默认读取配置里的 `cache_ttl_seconds`，也可用可缓存 live 命令的 `--cache-ttl <seconds>` 或 service 参数 `cache_ttl/cache_ttl_seconds` 显式覆盖；`--no-cache`、service 参数 `no_cache=true` 或 `KEEPA_CLI_NO_CACHE=1` 会禁用 live response cache。dry-run、fixture、binary、POST 与禁用缓存的请求不写入持久缓存。`cache explain-key --endpoint /product --param domain=1 --param asin=B001GZ6QEC` 可让 Agent 从 method、endpoint 与脱敏请求参数反查确定性的 SQLite cache key；`cache inspect <cache_key>` 只返回单条 key 元数据，不输出 cached body；`cache prune-expired --dry-run` / `cache prune-expired` 只统计或清理已过期条目。`cache stats` / `cache clear --dry-run` 只作用于 SQLite response cache，不删除 `tests/fixtures` 或进程内 session cache。release gate 会运行 `scripts/check_live_cache_options.py`，防止新增可缓存 live CLI 命令漏掉 `--cache-ttl` / `--no-cache`。

高成本请求不会交互等待确认；无 `yes=true`、`dry_run=true` 或 `fixture` 时返回 `confirmation_required`，并把阻断记录写入 `budget_ledger.blocked_actions`。

MCP resources 用于暴露稳定参考资料，避免把文档塞进 `tools/list`：

- `keepa://schema/products-agent-view`：产品 Agent 视图 schema snapshot 文档。
- `keepa://schema/risk-taxonomy`：稳定风险枚举与 risk item schema，便于外部 Agent 校验 `risk_taxonomy.codes/items/severity/evidence_path`。
- `keepa://schema/workflow-runtime-contract`：`keepa://workflow/runtime-contract` 的 JSON Schema，用于外部 MCP client 校验 runtime 参数、source shape、`missing_inputs` 与 `data.workflow_resolution` 契约。
- `keepa://fixtures/manifest`：fixture/evidence manifest。
- `keepa://guides/cassette-promotion`：真实响应脱敏并提升为 fixture 的流程。
- `keepa://guides/categories`：category ID 发现、Finder scaffold 与 category workflow 输入手册。
- `keepa://guides/marketplaces`：Keepa marketplace/domain code 与 Amazon host 对照手册。
- `keepa://guides/agent-profile`：Agent MCP 客户端配置片段、toolset/profile 选择与 business alias 入口。
- `keepa://evidence/recent`：最近 evidence 摘要。
- `keepa://context/policy`：offline-first policy、roots、tool gating 与 live Keepa 安全状态。
- `keepa://tools/index`：MCP toolset 与 tool schema 索引，适合先发现再按需读取。
- `keepa://prompts/index`：MCP prompt 索引。
- `keepa://zread/wiki/current`：当前 zread wiki 版本、公开文档链接和本地浏览命令。
- `keepa://zread/wiki/toc`：当前 `.zread/wiki` 的完整目录。
- `keepa://zread/wiki/pages`：紧凑页面清单，每页包含 `resource_uri`。

`resources/templates/list` 返回可发现的 URI 模板：

- `keepa://schema/{name}`：按 schema 稳定名读取，例如 `products-agent-view`、`risk-taxonomy` 或 `workflow-runtime-contract`。
- `keepa://fixtures/{name}`：按 JSON fixture 文件名读取已脱敏 fixture。
- `keepa://cache-key/{command}/{encoded_params}`：预览确定性的 AgentSession cache key。
- `keepa://workflow/{encoded_params}/policy`：从 base64url JSON `workflow.plan` 参数读取紧凑 `workflow_policy`、`totals` 与步骤摘要，适合资源优先客户端在调用完整计划前先拿执行策略。
- `keepa://research/{cache_key}`：读取同一 MCP session 内缓存结果的审计摘要，包含 `agent_brief`、`data_quality`、`evidence_index`、`provenance`、`budget_ledger` 与 research graph summary。
- `keepa://research/{cache_key}/brief`：读取同一 MCP session 内 `research_brief.export` 的完整 brief。
- `keepa://research/{cache_key}/graph`：读取同一 MCP session 内 `research_brief.export` 的图谱摘要与输入摘要。
- `keepa://graphs/{root}`：按 research graph root 查询同一 session cache 和本地 fixture 中的图谱来源与摘要。
- `keepa://toolsets/{toolset}`：按 toolset 读取紧凑工具 manifest，避免 `tools/list all`。
- `keepa://tools/{name}`：按 MCP tool 名读取单个完整 input/output schema。
- `keepa://prompts/{name}`：按 MCP prompt 名读取定义；无必填参数的 prompt 会附带渲染结果。
- `keepa://asin/{asin}/fixture`：按 ASIN 查找本地 fixture 候选。
- `keepa://evidence/{encoded_logical_path}`：按 manifest logical path 读取 evidence task log。
- `keepa://zread/wiki/page/{slug_or_file}`：按 zread slug 或 markdown 文件名读取页面。
- `keepa://chunk/{encoded_path}`：读取 tool fallback manifest 引用的 chunk 文件。
- `keepa://output/{encoded_path}`：读取 tool fallback manifest 引用的本地输出文件。

`resources/read` 返回 `contents[0].uri/mimeType/text`。当 tool 响应包含 `data.chunks` 或 `output.path` 时，`structuredContent` 保留完整结果，`content[0].text` 会压缩为摘要并追加：

```json
{
  "mcp_resource_manifest": {
    "strategy": "summary_with_resource_refs",
    "resources": [
      {"uri": "keepa://chunk/...", "type": "chunk", "path": "...", "mimeType": "application/json"}
    ]
  }
}
```

Agent 应优先读取 `structuredContent`；当客户端只支持 text fallback 时，再用 manifest 中的 `keepa://chunk/...` 或 `keepa://output/...` 按需调用 `resources/read`。

MCP prompts 给 Agent 提供稳定起手式，不执行任何请求：

- `keepa.product_research`：单品研究，强调先 workflow plan，再低成本 full product view。
- `keepa.category_research`：类目候选与 Finder scaffold，默认不隐式 hydrate。
- `keepa.deal_compare`：多 ASIN deal 视图对比与 selection signals 审计。
- `keepa.project_onboarding`：先读 zread/wiki 和 schema/evidence，再决定代码修改范围。
- `keepa.research_agent_start`：调研 Agent 起手式，按 policy -> target resolution -> context query -> workflow plan -> execution -> graph merge 顺序推进。
- `keepa.inventory_audit`：基于现有产品证据审计缺货、seller count 与补货风险，结论先行。
- `keepa.velocity_research`：基于 `monthlySold` 或低置信 sales-rank-drop proxy 查找 fast mover。
- `keepa.market_opportunity`：把 velocity、竞争、库存风险与现金流 proxy 组合成机会 shortlist。

不支持 `resources/read` 的 MCP 客户端可改用 `keepa.docs_index`、`keepa.docs_read`、`keepa.context_policy` 与 `keepa.query_research_context` 工具。`docs.index` 返回 GitHub Pages、zread public、zread resource、schema、fixture manifest 和 evidence 的推荐读取顺序；`docs.read` 接受 `uri` 或 `page`，默认读取 `keepa://zread/wiki/current`。

调研 Agent 应先调用 `keepa.context_policy` 或读取 `keepa://context/policy`，再用 `keepa.resolve_research_target` 将用户输入解析为 ASIN、UPC/EAN、seller、category、fixture、evidence 或 keyword 候选，随后用 `keepa.query_research_context` 查找本地资源。只有当本地资源不足时，才进入 `workflow.plan` 与 live-capable tools；真实 Keepa 请求仍需显式 `yes=true` 或 fixture/dry-run 绕过。

## 5. 当前支持命令

### doctor

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json doctor
```

返回版本、认证来源、fixture/offline 状态与双入口约束。无 `KEEPA_API_KEY` 时不失败。

### domains list

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json domains list
```

返回 Keepa domain 表，Agent 可把 `US`、`1`、`com` 归一到同一 domain。

### config show/init

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json config show
.\.venv\Scripts\python.exe -m keepa_cli --json config init --dry-run
```

`config show` 返回当前配置路径、文件是否存在、合并后的安全配置。`config init --dry-run` 返回将写入的默认 TOML 内容但不落盘，适合 Agent 先审计再决定是否写入。

### request get/post

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json request get /product --param domain=1 --param asin=B001GZ6QEC --dry-run
```

当前 MVP 先支持 dry-run request client 与 fixture/offline 客户端路径。live 请求需要 `KEEPA_API_KEY`，后续应补齐 429/5xx 重试、HTTP fixture 和更多错误映射测试。

### products get/search

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --history 0 --fixture product_B001GZ6QEC.json
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --full --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --full --out .\product-full.json
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --full --agent-view --history-limit 10 --out .\product-full.json
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --full --agent-view --view summary
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --full --agent-view --fields identity,pricing,demand,rating
.\.venv\Scripts\python.exe -m keepa_cli --json products get B001GZ6QEC --domain US --full --agent-view --view deal --chunks-dir .\agent-chunks
.\.venv\Scripts\python.exe -m keepa_cli --json products compare B001GZ6QEC B08N5WRWNW --domain US --full --view deal
.\.venv\Scripts\python.exe -m keepa_cli --json products search "coffee grinder" --domain US --fixture product_search_coffee.json
```

`products.get` 按官方 Product Request 映射到 `/product`，支持 `asin` 或 `--code`，但二者不能同时使用。`--full` 是低成本完整详情预设，会请求 `history=1`、`stats=0`、`videos=1`、`aplus=1`，其中 `stats=0` 用作全历史/最大 stats 窗口；可用 `--stats-window <days>` 覆盖。`--full` 不自动开启 `offers` 或额外 `rating=1`；Agent 可优先从网页侧补 rating，只有确实需要 Keepa 刷新评分时再显式传 `--rating 1`。CLI 也显式支持 `--days`、`--rating`、`--buybox`、`--stock`、`--historical-variations`、`--code-limit`、`--only-live-offers` 等官方 Product Request 参数。完整响应可能很大，`products.get` 支持 `--out` 把 body 写入 JSON 文件。`--agent-view` 或非 raw `--view` 会把 Product Object 转成稳定 Agent 视图：保留 identity、category、pricing、demand、rating、offers、media、aplus、content、logistics、stats_summary、history_summary 与 raw/output provenance，省略原始 `body.products[].csv` 大数组；`--history-limit` 控制每个历史序列的最近点数量，`--temporal-window-days` 控制 Agent 时序特征窗口。`products.search` 映射到 `/search` 并设置 `type=product`。当前测试默认使用 fixture/offline，不接真实 API。

产品预算会在 `token_bucket.estimated.components` 中拆分来源：`base_product=1 token * product count`；显式 `--rating`、`--buybox` 各按产品级附加成本估算；`--offers` 按官方 offer page 计费估算，即 `6 tokens * ceil(offers / 10) * product count`，并会触发显式确认；`--update 0` 记录为 worst-case live refresh，每个产品最多额外 1 token。`stats/history/days/videos/aplus` 只改变返回体形状，不作为额外 token 成本计入。

Agent 视图中 `history_summary.series` 使用 Keepa 官方 CsvType 位置命名，例如 `new`、`sales_rank`、`rating`、`review_count`、`buy_box_shipping`、`new_fba_offer_count`、`new_fbm_offer_count`。价格类字段同时保留小数 `amount/value` 与原始整数 `raw_value`，避免 Agent 在后续审计时丢失 Keepa 原始单位。若需要完整原文，必须同时传 `--out` 并读取 `data.raw.output.path`。

Agent 视图 profile：

- `summary`：极小上下文，用于批量预筛，保留身份、核心价格、需求、rating、质量与下一步建议。
- `research`：完整研究视图，包含内容、物流、variation、stats 与 history 摘要。
- `deal`：选品/交易视图，聚焦价格、rank、coupon、monthlySold、offer、Buy Box、媒体与 A+。
- `audit`：审计视图，聚焦 provenance、缺失字段、schema notes 与 raw field presence。

每个 Agent 视图会先生成 `agent_brief`，用于下游 Agent 的第一屏消费：`read_order` 指示建议读取顺序，`one_line` 合并 ASIN、标题、价格、销量、评分和风险，`key_facts` 提供可直接入库的核心事实，`decision_context` 聚合需求、竞争、价格稳定性、内容质量与数据质量，`temporal_takeaways` 以序列为中心提供 coverage、level、all_time、windows、volatility、momentum、shape 与 outliers，`temporal_by_window` 以 7/30/90/180/365 天窗口为中心横向汇总 price/rank/review/rating/offer 的变化和 `signal_summary`，`missing_data` 和 `recommended_next_actions` 让 Agent 明确是否需要补请求。`evidence_index` 是轻量证据目录，给出 `pricing.current`、`temporal_features`、`history_summary`、`data_quality` 等 JSON path、建议 section 与 `--view` 加载提示，避免 Agent 在完整 `research` 视图中盲扫字段。

`temporal_features` 从原始 `csv` 全量序列直接计算 Agent 可消费的时序特征，覆盖 `new`、`sales_rank`、`buy_box_shipping`、`new_fba`、`new_offer_count`、`new_fba_offer_count`、`rating`、`review_count` 等常用序列。默认窗口为 7/30/90/180/365 天，也可用 `--temporal-window-days` 重复指定或传逗号列表。每个序列包含首末变化、上一点变化、多窗口变化、均值、极值、range、波动系数、斜率、采样密度、分位数、最新 z-score、IQR/MAD、方向变化、离群点、最大回撤/反弹、最长上升/下降段和趋势方向。

`--fields` 会覆盖 profile，只返回指定 product section；`--chunks-dir` 会把 agent_brief、identity、pricing、demand、rating、offers、media、aplus、selection_signals、evidence_index、history_summary、temporal_features 等 section 写成独立 JSON chunk，并在 `data.chunks` 返回路径。每个 product 都会包含 `agent_brief`、`data_quality`、`next_actions`、`temporal_features` 和 `selection_signals`，用于 Agent 判断是否需要补 `--offers 20`、`--rating 1`、`--aplus 1` 或 `--history 1`。`next_actions` 保留旧的 `command` 字符串，同时新增 `tool`、`params`、`cli`、`estimated_tokens` 和 `requires_confirmation`，Agent 应优先使用 `tool+params` 执行，只有展示给人时使用 `command/cli`。

Agent 语义层：

- `risk_taxonomy`：稳定风险枚举，当前 `known_codes` 包含 `data_missing`、`price_unstable`、`rank_declining`、`low_review_count`、`offer_competition_high`、`buybox_missing`、`category_mismatch`。每个风险 item 给出 `severity`、`reason`、`evidence_path`，并尽量补充 `metric` 与 `follow_up`；外部 Agent 可读取 `keepa://schema/risk-taxonomy` 做客户端校验。
- `research_graph`：轻量实体关系图。产品视图节点类型包含 `product`、`brand`、`manufacturer`、`category`、`seller`、`variation`；非产品命令还会输出 `search_term`、`selection`、`deal_set`、`deal`、`seller_request`、`seller_ranking` 等节点。常见边类型包含 `made_by`、`manufactured_by`、`in_category`、`parent_of`、`buybox_sold_by`、`variation_of`、`has_variation`、`matched_category`、`has_candidate`、`filters_category`、`returns_product`、`contains_deal`、`for_product`、`sells_product`。
- `selection_signals.risk_codes` 与 `agent_brief.risk_codes` 会复用 `risk_taxonomy.codes`，便于批量筛选；深度审计时读取完整 `risk_taxonomy.items`。

`products.compare` 复用 `/product`，返回 `view=products_compare`，用统一 rows 暴露 `asin/title/brand/new_price/buy_box_price/sales_rank/monthly_sold/rating/review_count/coupon/offer/media/aplus/selection_signals/risk_flags/risk_taxonomy/research_graph/data_quality`，适合 Agent 做多 ASIN横向比较。顶层同时返回 `risk_summary` 与合并后的 `research_graph`，用于评测和报告阶段直接断言语义质量。

### research graph merge

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json research-graph merge .\category.json .\compare.json .\seller.json --root agent_selection_research --out .\research-graph.json
```

`research_graph.merge` 是纯本地命令，不访问 Keepa，不消耗 token。它会递归读取输入 JSON 中的 `research_graph` 字段，去重合并节点和边，添加 root 类型 `research_graph` 与 `includes_graph` 边，并返回 `view=research_graph_merge`、`summary`、`sources`、`diagnostics`、`diff`、`data_quality`、`evidence_index` 与可选 `output.path`。`sources` 包含 `source_weight/confidence`，`diagnostics` 包含重复节点、孤立节点、label/type 冲突和 source weight 范围。`diff` 包含冲突节点 variants 与 resolution；CLI 的 `--prefer-source` 和 MCP 的 `prefer_source` 可指定 source index 或 source root，让 Agent 在多来源 label/type 不一致时做确定性选择。MCP 对应工具为 `keepa.research_graph_merge`，适合把 category search -> category products -> products compare -> seller/deals 串成单个研究图。

### research brief export

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json research brief .\research-graph.json --title "Agent selection brief" --out .\brief.json
```

`research_brief.export` 是纯本地命令，不访问 Keepa，不消耗 token。它可读取 merged graph JSON、多份 Agent payload 文件或 MCP inline payload，输出 `view=research_brief_export`，核心字段为 `decision_summary`、`risk_summary`、`entity_graph_summary`、`follow_up_plan`、`evidence_links`、`data_quality` 与 `recommended_read_order`。MCP 对应工具为 `keepa.research_brief_export`；成功调用后可用 `keepa://research/{cache_key}/brief` 回读完整 brief，用 `keepa://research/{cache_key}/graph` 回读图谱摘要。

`reports.build` 可直接消费 `research_graph.merge --out` 写出的 merged graph JSON。Markdown 输出会追加 `Research Graph`、`Entities` 和 `Relationships` 小节；JSON 输出会增加 `research_graph_report`，包含 summary、entity_counts、nodes、edges、sources、diagnostics 与 diff。这样 Agent 可以把图谱合并和报告生成分成两步，并用 `keepa://graphs/{root}` 或 `keepa://research/{cache_key}` 回查来源。

### categories get/search

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json categories get 0 --domain US --parents --fixture category_roots_US.json
.\.venv\Scripts\python.exe -m keepa_cli --json categories search "home kitchen" --domain US --fixture category_search_home.json
.\.venv\Scripts\python.exe -m keepa_cli --json categories finder-selection 1055398 --domain US --out finder-category-1055398.json
.\.venv\Scripts\python.exe -m keepa_cli --json categories products 172282 --domain US --fixture bestsellers_home.json --limit 25
.\.venv\Scripts\python.exe -m keepa_cli --json categories products 172282 --domain US --limit 25 --hydrate-top 3 --yes
```

`categories.get` 按官方 Category Lookup 映射到 `/category`，支持最多 10 个 category id，`0` 表示 root categories。`categories.search` 映射到 `/search` 并设置 `type=category`，并在成功响应中派生 `view=category_search`、`category_candidates` 与结构化 `next_actions`，引导 Agent 先 dry-run `categories products` 或生成 Finder selection 草稿。`categories.finder-selection` 是纯本地 scaffold 命令，不访问 Keepa，不消耗 token，会输出 `view=finder_selection_scaffold`、`selection`、`field_notes` 与可选 `output.path`。`categories.products` 是 Agent 友好的类目商品候选入口，底层复用 `/bestsellers`，返回 `view=category_products`、候选 ASIN、rank、source category 与下一步 `products compare` / `products get --agent-view` 命令；真实请求与 `bestsellers.get` 一样属于 50 token 高成本路径，默认需要 `--yes`。`--hydrate-top N` 默认关闭，显式开启后只拉取前 N 个候选的 `products.get --full --agent-view --view summary` 摘要，并在预算中追加 `hydrate_top=N` token 组件。category、finder、deals、seller、bestsellers 与 topsellers 的 Agent-facing 响应会尽量提供统一 profile：`agent_brief`、`data_quality`、`selection_signals`、`next_actions`、`evidence_index`、`provenance`。

### workflow plan

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan category-research --term "home kitchen" --domain US
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan category-research --term "home kitchen" --domain US --hydrate-top 3
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan product-research --asin B0D8W1YVBX --domain US --goal deal
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan report-research --domain US --goal deal
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan tracking-audit --asin B0D8W1YVBX --domain US
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan inventory-audit --domain US
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan velocity-research --domain US
.\.venv\Scripts\python.exe -m keepa_cli --json workflow plan market-opportunity --domain US
```

`workflow.plan` 是本地规划入口，不访问 Keepa，不消耗 token。输出 `view=workflow_plan`、`workflow_inputs`、`artifacts`、`resource_templates`、`steps`、`totals`、`parallel_groups`、`workflow_policy`、`agent_brief`、`data_quality`、`next_actions`、`evidence_index` 与 `provenance`。每个 step 包含 `id`、`tool`、`mcp_tool`、`params`、`cli/command`、`depends_on`、`parallel_group`、`estimated_tokens`、`worst_case_tokens`、`requires_confirmation`、`fixture_replay`、`input_refs`、`artifact_refs`、`mcp` 与 `execution`，用于 Agent 先规划执行图，再按预算和确认要求逐步执行。

`workflow_policy` 是 Agent 执行阶段的第一读字段：`recommended_toolset` 与 `recommended_profile` 给出默认 `tools/list` 过滤；`allowed_tools` / `inactive_tools` 说明当前 profile 下哪些工具可调用、哪些步骤需要切换 profile；`profile_switch_points` 给出阶段切换点；`confirmation_policy` 列出必须暂停等待确认的 step；`budget_ledger_seed` 给出计划预算和初始 blocked actions；`tool_discovery.params.allow_tools` 可直接作为 MCP `tools/list` 参数复用。Agent 不应直接给高成本步骤补 `yes=true`，除非用户确认了对应 step。

`workflow_inputs` 明确区分用户已给参数、后续步骤产物和占位值；`artifacts` 给出每个中间产物的 kind、producer、路径或可用 resource template；`resource_templates` 汇总可复用的 `keepa://workflow/{encoded_params}/policy`、`keepa://research/{cache_key}`、`keepa://graphs/{root}`、`keepa://output/{encoded_path}` 等读取入口。Agent 应优先使用这些字段连接步骤，不应解析 `cli` 字符串来猜测输入和输出路径。

`scripts/mcp_example_support.py` 提供可复制的标准库 MCP client helper。`scripts/mcp_agent_workflow_example.py` 按 `workflow.plan -> keepa://schema/risk-taxonomy -> keepa://research/{cache_key} -> keepa://research/{cache_key}/graph -> brief/report` 顺序执行完整离线链路，并在 client 侧校验 `risk_taxonomy.codes/items/severity/evidence_path`。`scripts/mcp_tracking_audit_example.py` 演示 `tracking-readonly` toolset/profile 边界和写工具不暴露；`scripts/mcp_report_research_example.py` 演示本地 graph -> brief -> browse/figures/report 链路。三个示例统一支持 `--save-summary <path>`，便于 Agent pipeline 把集成摘要写入 evidence/runtime 之外的受控路径。外部 Agent 集成时可直接借用其中的 JSON-RPC stdio request/response、同进程 session cache、`resource_uri` 拼接和紧凑 summary 输出模式。

MCP `tools/call` 支持 workflow runtime 参数：`resource_uri`、`resource_uris`、`artifact`、`artifacts`、`workflow_inputs` 与 `workflow_context`。`workflow_context` 可携带顶层 artifact/resource_uri，也可携带 `steps`、`outputs`、`results`、`step_outputs`、`previous_outputs` 等客户端状态容器。这些字段不会传入业务 service，而是在执行前解析为实际参数：`keepa://research/{cache_key}` 可提供完整 cached envelope，`keepa://research/{cache_key}/graph` 可提供 graph merge 输入，`keepa://output/{encoded_path}` 可提供本地文件路径，inline artifact 可提供 `payload` 或 `graph`，`artifact.output.path` / `artifact.data.output.path` 可直接续接本地 graph -> brief -> reports 链路；`keepa://graphs/{root}` 是图谱来源审计入口，不直接替代完整 graph 输入。外部 Agent 可读取 `keepa://workflow/runtime-contract` 获取支持 runtime 参数的 tool 清单、参数名和缺参错误约定，避免遍历全部 tool schema；该 resource 的 `schema_resource_uri` 指向 `keepa://schema/workflow-runtime-contract`，可用于 MCP client 侧校验。解析成功的响应会在 `data.workflow_resolution` 记录来源、推导出的 ASIN/category、graph_count、payload_count 与临时文件；依赖不足时返回 tool error `missing_inputs`，其中 `error.details.missing_inputs` 会说明缺少的字段和可接受来源。

当前内置计划：

- `category-research`：关键词 -> category candidates -> Finder scaffold -> category products -> compare candidates；推荐 `research` toolset 与 `dry_run_default` profile，高成本 category products 需要确认。
- `product-research`：单品 Agent view -> 可选 offers detail；推荐 `research` toolset 与 `live_read_allowed` profile，可选 offers step 需要确认。
- `report-research`：merged research graph -> markdown report / Agent brief / local browse snapshot / SVG figures；推荐 `reports` toolset 与 `offline_fixture_only` profile，纯本地 0 token。
- `tracking-audit`：tracking list -> notifications / tracking detail / cost audit；推荐 `tracking-readonly` toolset 与 `tracking_readonly` profile，不暴露 tracking 写操作。
- `velocity-research` / `inventory-audit` / `market-opportunity`：基于现有产品 JSON、resource 或 artifact 运行 business alias；推荐 `business` toolset 与 `offline_fixture_only` profile，纯本地 0 token。

### business aliases 与 metrics

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json business find-fast-movers --fixture product_agent_view_B0TEST.json
.\.venv\Scripts\python.exe -m keepa_cli --json business inventory-audit --input products.json
.\.venv\Scripts\python.exe -m keepa_cli --json business market-opportunity --input compare.json
.\.venv\Scripts\python.exe -m keepa_cli --json business agent-profile --profile offline_fixture_only --toolset business
```

`business.find-fast-movers`、`business.inventory-audit`、`business.market-opportunity`、`seller-metrics.summary`、`velocity.research` 与 `inventory.audit` 都是纯本地命令，输入可为 Keepa 原始产品 JSON、Agent product view、`products.compare` rows、fixture、MCP resource/artifact 或 inline payload。输出 `view=business_metrics`，先给 `brief.decision/risk/next_actions`，再给 `summary` 和 `products[].metrics`。

所有估算字段必须带 `method`、`version`、`inputs`、`confidence` 与 `evidence_path`。当前公式模块覆盖：

- `velocity`：优先使用 `monthlySold`，缺失时只把 sales rank drops 标为低置信 proxy。
- `seller_metrics`：优先使用 `stats.totalOfferCount` / Agent `offers.total_offer_count`，再降级到 FBA/FBM 或 seller id 样本下界。
- `inventory`：基于 out-of-stock percentage、seller count 与 velocity 估算库存风险，不输出确定库存数量。
- `cashflow`：基于价格与 monthlySold 给出 GMV proxy，明确排除成本、费率、广告、退款、税与账期。

### Agent figures

`figures.research` / `keepa.figures_research` 从现有 JSON 输出生成统一 SVG 图表，不访问 Keepa API。输入可为 `products.compare`、Agent product view、`research_graph.merge` 或包含 `research_graph` 的报告输出。输出包含：

- `data.figures[].path`：SVG 文件路径。
- `data.figures[].source_data_path`：图表源数据 JSON，便于审计。
- `data.figure_set` / `data.available_figure_sets`：图表组选择；`all` 保持兼容总览，`history`、`compare`、`audit` 可让 Agent 只加载当前报告需要的 SVG。
- `mcp_resource_manifest.resources[]`：MCP text fallback 中的 `keepa://output/...` 资源；SVG MIME 为 `image/svg+xml`。

默认 `all` 会生成兼容总览 SVG 与独立单图：产品指标对比、真实 price/rank/review history 折线、窗口变化热图、多 ASIN 标准化 small multiples、风险与 research graph 审计摘要。若输入只有 compare 摘要而没有 full Agent history，图表会降级到当前指标与窗口/风险摘要，并在 source JSON 中保留 `data_basis`。

`reports.build` 对 markdown/json 输出会默认在本地生成并嵌入同一组 SVG；可用 `--figure` 复用已有 SVG，`--figure-set history|compare|audit` 限制图表组，或用 `--no-figures` 关闭自动嵌图。MCP Agent 也可读取 `keepa://research/{cache_key}/figures` 或 `keepa://research/{cache_key}/figures/{figure_set}`，从同一 session cache 生成 figure manifest，再按其中 `image/svg+xml` 的 `keepa://output/...` resource 插入报告。

### history export/trend

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json history export B001GZ6QEC --domain US --series amazon,new --format json --fixture product_history_B001GZ6QEC.json
.\.venv\Scripts\python.exe -m keepa_cli --json history trend B001GZ6QEC --domain US --series amazon --window-days 30 --fixture product_history_B001GZ6QEC.json
```

`history.export` 复用官方 Product Request `/product` 并强制 `history=1`，把 Product Object 的 `csv` 历史展开成稳定 rows；支持 `json`、`jsonl`、`csv` 和 `--out` 文件导出。`history.trend` 基于同一 rows 返回 all-time 与窗口统计。当前冻结序列为 `amazon`、`new`、`used`、`sales_rank`。

### schema/cassettes

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json schema generate --out docs/schema/products.agent-view.schema.json
.\.venv\Scripts\python.exe -m keepa_cli --json cassettes sanitize .\live-cassette.json --out .\redacted-cassette.json
.\.venv\Scripts\python.exe -m keepa_cli --json cassettes promote .\live-cassette.json --name product_B0EXAMPLE_full
.\.venv\Scripts\python.exe -m keepa_cli --json cassettes promote-and-verify .\live-cassette.json --name product_B0EXAMPLE_full --run-eval
```

`schema.generate` 从 `tests/snapshots/agent_schema_snapshot.json` 导出产品 Agent 视图 schema 文档。`cassettes.sanitize` 只做本地 JSON 脱敏，清理 URL query、header 与 body 中的 `key/api_key/apikey/token/authorization`。`cassettes.promote` 是完整 promotion workflow：读取真实或已脱敏响应 -> 再次脱敏 -> 同步写入 `tests/fixtures/<name>.json` 与 `keepa_cli/fixtures/<name>.json` -> 追加 `evidence/manifest.csv`。`cassettes.promote_and_verify` / `keepa.cassettes_promote_and_verify` 在 promote 后执行 fixture parity 检查，并可通过 `run_eval=true` / `--run-eval` 运行 Agent eval fixtures，适合把 live sample 固化为调研 Agent 回归资产。默认不访问网络，`--dry-run` 只返回目标路径和预计大小。

### finder/deals/sellers/bestsellers/topsellers

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
.\.venv\Scripts\python.exe -m keepa_cli --json deals query --selection-file keepa_cli/fixtures/deals_selection.json --domain US --fixture deals_home.json --out deals.json
.\.venv\Scripts\python.exe -m keepa_cli --json sellers get A2L77EE7U53NWQ --domain US --storefront --fixture seller_A2L77EE7U53NWQ.json
.\.venv\Scripts\python.exe -m keepa_cli --json bestsellers get 172282 --domain US --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json topsellers list --domain US --fixture topsellers_US.json --out topsellers.json
```

`finder.query` 映射到 `/query`，`deals.query` 映射到 `/deal`，二者读取 selection JSON 并作为 `selection` 参数发送。`sellers.get` 映射到 `/seller`。`bestsellers.get` 映射到 `/bestsellers`，`topsellers.list` 映射到 `/topseller`。`finder.query`、`bestsellers.get`、`topsellers.list` 会在预算里标记 `requires_confirmation=true`；真实请求必须显式 `--yes`，dry-run 与 fixture 不消耗 token。大结果命令支持 `--out` 把响应 body 写入 JSON 文件。这些命令的 Agent profile 会输出统一 `agent_brief/data_quality/selection_signals/evidence_index/provenance/research_graph`，便于 Agent 把类目、selection、deal、seller、商品候选串成同一实体图谱。

### tokens/graphs/lightningdeals/tracking

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json tokens status --fixture token_status.json
.\.venv\Scripts\python.exe -m keepa_cli --json graphs image B09YNQCQKR --domain US --width 800 --height 400 --range 365 --param amazon=1 --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json lightningdeals list --domain US --fixture lightningdeals_US.json
.\.venv\Scripts\python.exe -m keepa_cli --json tracking list --asins-only --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json tracking list-names --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json tracking get B09YNQCQKR --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json tracking notifications --since 0 --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json tracking add --tracking-json "{\"asin\":\"B09YNQCQKR\",\"domain\":1}" --dry-run
```

`tokens.status` 映射到 `/token`，用于读取 token bucket 状态。`graphs.image` 映射到 `/graphimage`，当前只冻结 dry-run/fixture 信息流；真实响应是 PNG 二进制，live 下载要等专用 binary transport。`lightningdeals.list` 映射到 `/lightningdeal`。`tracking.list`、`tracking.list-names`、`tracking.get`、`tracking.notifications` 是只读链路；`tracking.add`、`tracking.remove`、`tracking.remove-all`、`tracking.webhook` 是有副作用链路，真实请求必须显式 `--yes`，Agent 模式不能交互等待确认。

## 6. Fixture

当前 fixture：

```text
tests/fixtures/product_B001GZ6QEC.json
tests/fixtures/product_search_coffee.json
tests/fixtures/product_history_B001GZ6QEC.json
tests/fixtures/product_history_empty_B001GZ6QEC.json
tests/fixtures/category_roots_US.json
tests/fixtures/category_search_home.json
tests/fixtures/finder_selection.json
tests/fixtures/deals_selection.json
tests/fixtures/deals_home.json
tests/fixtures/seller_A2L77EE7U53NWQ.json
tests/fixtures/bestsellers_home.json
tests/fixtures/topsellers_US.json
tests/fixtures/token_status.json
tests/fixtures/lightningdeals_US.json
tests/fixtures/tracking_list.json
```

用途：

- 无 Keepa key 时验证 client 解析与 token bucket 映射。
- 为后续 `products.get`、history export、schema regression 提供稳定样本。
- 为 `products.search`、`categories.get`、`categories.search` 提供不接 API 的信息流样本。
- 为 Phase 8 高价值 API 提供 selection、seller、deals 与榜单离线样本。
- 为新增官方缺口链路提供 token、lightning deals 与 tracking 离线样本。
- CI 默认只跑 fixture，不消耗真实 Keepa token。

## 7. TUI 边界

默认无参数执行 `keepa-cli` 或 `kc` 会进入标准库 TUI 工作台。当前支持 slash 命令：

```text
/doctor
/domains
/product B001GZ6QEC --domain US --fixture product_B001GZ6QEC.json
/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json
/bestsellers 172282 --domain US --dry-run
/seller A2L77EE7U53NWQ --fixture seller_A2L77EE7U53NWQ.json
/tokens --fixture token_status.json
/graph B09YNQCQKR --domain US --param amazon=1 --dry-run
/lightningdeals --domain US --dry-run
/tracking-list --asins-only --dry-run
/category 0 --domain US --parents --fixture category_roots_US.json
/category-search home kitchen --domain US --fixture category_search_home.json
/quit
```

TUI 不直接构造 Keepa request，也不读取 API key；它只解析人类输入并调用 `keepa_cli.service.run_command`。

## 8. 后续冻结项

Phase 6 之后如要扩展 TUI、缓存或真实 API 调用，应保持以下不变：

- `keepa-cli` 与 `kc` 继续共用同一入口。
- TUI 只调用 Agent-safe command service，不复制 Keepa API 逻辑。
- `--json` 和 `--stdio` 的 stdout 继续保持纯机器协议。
- 新增命令先补 Agent schema 与 fixture 测试，再接入人类界面。

## 9. Schema Snapshot

Agent 契约通过 `tests/snapshots/agent_schema_snapshot.json` 冻结。该 snapshot 只记录字段与类型形状，不锁定完整业务数据，避免 Product Object 字段扩展造成无意义噪音。

覆盖对象：

- `doctor`
- `products.get`
- `products.compare`
- `categories.search`
- `categories.products`
- `categories.finder-selection`
- `history.trend`
- `finder.query`
- `bestsellers.get`
- `sellers.get`
- `tokens.status`
- `graphs.image`
- `lightningdeals.list`
- `tracking.list`
- `tracking.add`
- `research_graph.merge`
- `mcp resources/list`
- `mcp products.get chunk fallback`
- `stdio products.get` 事件流

更新规则：

- 任何输出字段新增、删除或类型变化都必须先确认 Agent 兼容性。
- 确认兼容后再更新 snapshot。
- 不能为了让测试通过而删除 schema 字段；要先说明迁移影响。

## 10. Record/Replay Transport

`keepa_cli.transport` 提供未来真实 live smoke 的接口：

- `RecordingOpener`：包装真实或 fake opener，写入脱敏 cassette。
- `ReplayOpener`：从 cassette 回放 HTTP 响应。

当前测试只使用 fake opener，不请求真实 Keepa API。cassette 中会把 query 参数里的 `key`、`api_key`、`apikey`、`token` 替换为 `[REDACTED]`。

## 11. npm Wrapper

开源发布目标支持 npm 全局安装：

```powershell
npm install -g @cunuo/keepa-cli
keepa-cli --json doctor
kc --json doctor
```

npm wrapper 位于 `bin/keepa-cli.js` 与 `bin/kc.js`。二者只负责寻找 Python 3.11+ 并执行 `python -m keepa_cli`。可通过 `KEEPA_CLI_PYTHON` 指定解释器。
