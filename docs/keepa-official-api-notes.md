# Keepa 官方 API 约束摘记

更新时间：2026-05-09 20:55 +08:00

本文件只记录本轮实现用到的官方约束，避免把 Keepa CLI 的信息流测试做成凭空假设。

## 来源

- Keepa API Overview：`https://discuss.keepa.com/t/how-to-make-requests/767.json`
- Product Request：`https://discuss.keepa.com/t/products/110.json`
- Category Lookup：`https://discuss.keepa.com/t/category-lookup/113.json`
- Category Searches：`https://discuss.keepa.com/t/category-searches/114.json`
- Keepa Python wrapper API methods：`https://keepaapi.readthedocs.io/en/stable/api_methods.html`

## 请求通用约束

- Base URL：`https://api.keepa.com/`
- 每个请求都需要 API access key 参数。
- 官方说明所有请求通过 HTTPS GET 发出，并接受 gzip 编码；应尽量复用 Keep-Alive 连接。
- 响应为 JSON，常见 token bucket 字段包括 `refillRate`、`refillIn`、`tokensLeft`、`tokensConsumed`、`tokenFlowReduction`、`processingTimeInMs` 和 `error`。
- `tokensLeft` 可能为负，因为提交请求时余额为正即可执行较大请求。
- 未使用 token 会在 60 分钟后过期。

## HTTP 状态码

- `200`：请求成功执行。
- `400`：请求 malformed 或无法执行。
- `402`：API key 没有访问权限。
- `405`：参数超出允许范围。
- `429`：token 不足。
- `500`：服务端异常。

本仓库当前不接真实 API；这些状态码通过 fake transport 和 fixture 做信息流测试。

## Product Request

路径：

```text
/product?key=<yourAccessKey>&domain=<domainId>&asin=<ASIN>
/product?key=<yourAccessKey>&domain=<domainId>&code=<productCode>
```

约束：

- 基础 token 成本为 1 / product。
- `asin` 和 `code` 不能同时使用。
- ASIN 批量为逗号分隔，最多 100。
- `code` 支持 UPC、EAN 和 ISBN-13，批量最多 100；多个 ASIN 可能匹配同一个 code。
- `history=0` 可排除历史字段，降低响应体大小。
- `stats` 无额外 token 成本。
- `update=0` 可能额外消耗 1 token。
- `offers` 官方范围 20 到 100，按找到的 offer page 计费，每页最多 10 offers，每页 6 tokens。
- Product Object 的 `csv` 字段包含价格、销量排名等历史数组；当前实现只展开常用序列：`amazon`、`new`、`used`、`sales_rank`。
- Keepa 历史时间按 Keepa minute 表示，本仓库按官方 Java helper 的 epoch 语义转换为 UTC：`0` 对应 `2011-01-01T00:00:00Z`。

当前命令：

```powershell
.\.venv\Scripts\kc.exe --json products get B001GZ6QEC --domain US --history 0 --fixture product_B001GZ6QEC.json
```

## History Export / Trend

路径仍使用 Product Request：

```text
/product?key=<yourAccessKey>&domain=<domainId>&asin=<ASIN>&history=1
```

当前命令：

```powershell
.\.venv\Scripts\kc.exe --json history export B001GZ6QEC --domain US --series amazon,new --format json --fixture product_history_B001GZ6QEC.json
.\.venv\Scripts\kc.exe --json history trend B001GZ6QEC --domain US --series amazon --window-days 30 --fixture product_history_B001GZ6QEC.json
```

实现边界：

- `history export` 展开 Product Object 的 `csv`，支持 `json`、`jsonl`、`csv`，也支持 `--out` 写文件。
- `history trend` 返回 all-time 与窗口统计，默认窗口为 30 / 90 / 180 天。
- 当前只支持 `amazon`、`new`、`used`、`sales_rank` 四个序列；其他 Keepa csv index 后续按官方字段逐步增加。
- 价格序列按分转为主币种金额；`sales_rank` 保留整数排名。
- `-1` 缺失值默认过滤，可用 `--include-missing` 保留为 `null`。

## Category Lookup

路径：

```text
/category?key=<yourAccessKey>&domain=<domainId>&category=<categoryId>&parents=<includeParents>
```

约束：

- token 成本为 1。
- `category=0` 返回 root categories。
- 批量 category id 使用逗号分隔，最多 10 个，token 成本不变。
- `parents=1` 返回到根节点的父级分类树。
- 响应包含 `categories`；使用 `parents=1` 时可包含 `categoryParents`。

当前命令：

```powershell
.\.venv\Scripts\kc.exe --json categories get 0 --domain US --parents --fixture category_roots_US.json
```

## Category Search

路径：

```text
/search?key=<yourAccessKey>&domain=<domainId>&type=category&term=<searchTerm>
```

约束：

- token 成本为 1。
- 最多返回 50 个匹配 category object。
- 多个空格分隔关键词可同时匹配；关键词最小长度为 3。
- 响应字段与 Category Lookup 的 `categories` 映射一致。

当前命令：

```powershell
.\.venv\Scripts\kc.exe --json categories search "home kitchen" --domain US --fixture category_search_home.json
```

## Phase 8 P1 高价值 API

本轮只冻结请求信息流，不接真实 API。Keepa 官方通用约束仍按 GET、API key query 参数、gzip 响应与 token bucket 字段处理；Python wrapper 文档用于交叉确认 Product Finder、deals、seller 与 best seller 类方法存在。

当前命令与路径：

```text
finder.query      -> /query
deals.query       -> /deal
sellers.get       -> /seller
bestsellers.get   -> /bestsellers
topsellers.list   -> /topseller
tokens.status     -> /token
graphs.image      -> /graphimage
lightningdeals.list -> /lightningdeal
tracking.*        -> /tracking
```

当前命令：

```powershell
.\.venv\Scripts\kc.exe --json finder query --selection-file keepa_cli/fixtures/finder_selection.json --domain US --dry-run --max-tokens 25
.\.venv\Scripts\kc.exe --json deals query --selection-file keepa_cli/fixtures/deals_selection.json --domain US --fixture deals_home.json --out deals.json
.\.venv\Scripts\kc.exe --json sellers get A2L77EE7U53NWQ --domain US --storefront --fixture seller_A2L77EE7U53NWQ.json
.\.venv\Scripts\kc.exe --json bestsellers get 172282 --domain US --dry-run
.\.venv\Scripts\kc.exe --json topsellers list --domain US --fixture topsellers_US.json --out topsellers.json
.\.venv\Scripts\kc.exe --json tokens status --fixture token_status.json
.\.venv\Scripts\kc.exe --json graphs image B09YNQCQKR --domain US --param amazon=1 --dry-run
.\.venv\Scripts\kc.exe --json lightningdeals list --domain US --fixture lightningdeals_US.json
.\.venv\Scripts\kc.exe --json tracking list-names --dry-run
```

实现边界：

- `finder.query` 与 `deals.query` 从 `--selection-file` 读取 JSON object，并以压缩 JSON 字符串放入 `selection` 参数。
- `finder.query` 的默认估算为 10 tokens，可用 `--max-tokens` 给 Agent 设置 worst-case 提示；真实请求未带 `--yes` 时返回 `confirmation_required`。
- `bestsellers.get` 与 `topsellers.list` 固定显示 50 token 预算提示；真实请求未带 `--yes` 时先返回确认错误，不先走认证错误。
- `deals.query` 估算 5 tokens；`sellers.get` 按 seller id 数估算。
- 大结果命令支持 `--out`，写入响应 body 的 JSON 文件，并在 envelope 中返回 `path`、`format`、`size_bytes` 与 `result_count`。
- fixture 与 dry-run 是当前唯一自动化验证路径；真实 live smoke 后续只能手动触发并录制脱敏 cassette。

## 官方链路补齐记录

本轮对照 Keepa 官方 Java API framework 的 `Request.java` 与 Keepa Python wrapper 文档，确认除已落地的 product/search/category/query/deal/seller/bestsellers/topseller 外，还应补齐以下高价值链路：

- `/token`：通过 `tokens.status` 读取 token bucket 状态，估算成本为 0。
- `/graphimage`：通过 `graphs.image` 构建 Graph Image API 请求；真实响应为 PNG 二进制，当前只开放 dry-run/fixture 信息流，live binary download 留给后续专用 transport。
- `/lightningdeal`：通过 `lightningdeals.list` 查询全部或指定 ASIN 的 Lightning Deals。
- `/tracking`：通过 `tracking.list`、`tracking.list-names`、`tracking.get`、`tracking.notifications` 做只读信息流；通过 `tracking.add`、`tracking.remove`、`tracking.remove-all`、`tracking.webhook` 做写类信息流。写类真实请求必须 `--yes`，避免 Agent 阻塞或误触发长期跟踪副作用。

## 本仓库信息流测试策略

当前仓库不接真实 Keepa API，所有 live-like 行为都通过离线机制验证：

- `keepa_cli/fixtures/*.json`：随 Python 包发布的官方形状示例响应。
- `tests/fixtures/*.json`：测试用固定响应。
- `RecordingOpener` / `ReplayOpener`：为未来手动 live smoke 留 record/replay 接口。
- fake opener：在内存中模拟 gzip、429、500，不访问 `https://api.keepa.com/`。

未来如开启真实 live smoke，应使用手动触发 workflow 和 GitHub Secret `KEEPA_API_KEY`，并把录制后的 cassette 脱敏后再用于回归测试。
