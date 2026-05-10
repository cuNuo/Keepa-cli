# Keepa CLI Agent 协议契约

更新时间：2026-05-09 20:20 +08:00

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

## 4. 当前支持命令

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

每个 Agent 视图会先生成 `agent_brief`，用于下游 Agent 的第一屏消费：`read_order` 指示建议读取顺序，`one_line` 合并 ASIN、标题、价格、销量、评分和风险，`key_facts` 提供可直接入库的核心事实，`temporal_takeaways` 提供价格、Buy Box、rank、review、rating、offer 等时序摘要，`missing_data` 和 `recommended_next_actions` 让 Agent 明确是否需要补请求。`evidence_index` 是轻量证据目录，给出 `pricing.current`、`temporal_features`、`history_summary`、`data_quality` 等 JSON path、建议 section 与 `--view` 加载提示，避免 Agent 在完整 `research` 视图中盲扫字段。

`temporal_features` 从原始 `csv` 全量序列直接计算 Agent 可消费的时序特征，覆盖 `new`、`sales_rank`、`buy_box_shipping`、`new_fba`、`new_offer_count`、`new_fba_offer_count`、`rating`、`review_count` 等常用序列。默认窗口为 7/30/90/180/365 天，也可用 `--temporal-window-days` 重复指定或传逗号列表。每个序列包含首末变化、上一点变化、多窗口变化、均值、极值、range、波动系数、斜率、采样密度、分位数、最新 z-score、IQR/MAD、方向变化、离群点、最大回撤/反弹、最长上升/下降段和趋势方向。

`--fields` 会覆盖 profile，只返回指定 product section；`--chunks-dir` 会把 agent_brief、identity、pricing、demand、rating、offers、media、aplus、selection_signals、evidence_index、history_summary、temporal_features 等 section 写成独立 JSON chunk，并在 `data.chunks` 返回路径。每个 product 都会包含 `agent_brief`、`data_quality`、`next_actions`、`temporal_features` 和 `selection_signals`，用于 Agent 判断是否需要补 `--offers 20`、`--rating 1`、`--aplus 1` 或 `--history 1`。

`products.compare` 复用 `/product`，返回 `view=products_compare`，用统一 rows 暴露 `asin/title/brand/new_price/buy_box_price/sales_rank/monthly_sold/rating/review_count/coupon/offer/media/aplus/selection_signals/risk_flags/data_quality`，适合 Agent 做多 ASIN 横向比较。

### categories get/search

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json categories get 0 --domain US --parents --fixture category_roots_US.json
.\.venv\Scripts\python.exe -m keepa_cli --json categories search "home kitchen" --domain US --fixture category_search_home.json
```

`categories.get` 按官方 Category Lookup 映射到 `/category`，支持最多 10 个 category id，`0` 表示 root categories。`categories.search` 映射到 `/search` 并设置 `type=category`。

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
```

`schema.generate` 从 `tests/snapshots/agent_schema_snapshot.json` 导出产品 Agent 视图 schema 文档。`cassettes.sanitize` 只做本地 JSON 脱敏，清理 URL query、header 与 body 中的 `key/api_key/apikey/token/authorization`，用于把真实响应录制后安全转成 fixture。

### finder/deals/sellers/bestsellers/topsellers

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
.\.venv\Scripts\python.exe -m keepa_cli --json deals query --selection-file keepa_cli/fixtures/deals_selection.json --domain US --fixture deals_home.json --out deals.json
.\.venv\Scripts\python.exe -m keepa_cli --json sellers get A2L77EE7U53NWQ --domain US --storefront --fixture seller_A2L77EE7U53NWQ.json
.\.venv\Scripts\python.exe -m keepa_cli --json bestsellers get 172282 --domain US --dry-run
.\.venv\Scripts\python.exe -m keepa_cli --json topsellers list --domain US --fixture topsellers_US.json --out topsellers.json
```

`finder.query` 映射到 `/query`，`deals.query` 映射到 `/deal`，二者读取 selection JSON 并作为 `selection` 参数发送。`sellers.get` 映射到 `/seller`。`bestsellers.get` 映射到 `/bestsellers`，`topsellers.list` 映射到 `/topseller`。`finder.query`、`bestsellers.get`、`topsellers.list` 会在预算里标记 `requires_confirmation=true`；真实请求必须显式 `--yes`，dry-run 与 fixture 不消耗 token。大结果命令支持 `--out` 把响应 body 写入 JSON 文件。

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

## 5. Fixture

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

## 6. TUI 边界

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

## 7. 后续冻结项

Phase 6 之后如要扩展 TUI、缓存或真实 API 调用，应保持以下不变：

- `keepa-cli` 与 `kc` 继续共用同一入口。
- TUI 只调用 Agent-safe command service，不复制 Keepa API 逻辑。
- `--json` 和 `--stdio` 的 stdout 继续保持纯机器协议。
- 新增命令先补 Agent schema 与 fixture 测试，再接入人类界面。

## 8. Schema Snapshot

Agent 契约通过 `tests/snapshots/agent_schema_snapshot.json` 冻结。该 snapshot 只记录字段与类型形状，不锁定完整业务数据，避免 Product Object 字段扩展造成无意义噪音。

覆盖对象：

- `doctor`
- `products.get`
- `categories.search`
- `history.trend`
- `finder.query`
- `bestsellers.get`
- `sellers.get`
- `tokens.status`
- `graphs.image`
- `lightningdeals.list`
- `tracking.list`
- `tracking.add`
- `stdio products.get` 事件流

更新规则：

- 任何输出字段新增、删除或类型变化都必须先确认 Agent 兼容性。
- 确认兼容后再更新 snapshot。
- 不能为了让测试通过而删除 schema 字段；要先说明迁移影响。

## 9. Record/Replay Transport

`keepa_cli.transport` 提供未来真实 live smoke 的接口：

- `RecordingOpener`：包装真实或 fake opener，写入脱敏 cassette。
- `ReplayOpener`：从 cassette 回放 HTTP 响应。

当前测试只使用 fake opener，不请求真实 Keepa API。cassette 中会把 query 参数里的 `key`、`api_key`、`apikey`、`token` 替换为 `[REDACTED]`。

## 10. npm Wrapper

开源发布目标支持 npm 全局安装：

```powershell
npm install -g @cunuo/keepa-cli
keepa-cli --json doctor
kc --json doctor
```

npm wrapper 位于 `bin/keepa-cli.js` 与 `bin/kc.js`。二者只负责寻找 Python 3.11+ 并执行 `python -m keepa_cli`。可通过 `KEEPA_CLI_PYTHON` 指定解释器。
