# Keepa 官方 API 约束摘记

更新时间：2026-05-09 20:55 +08:00

本文件只记录本轮实现用到的官方约束，避免把 Keepa CLI 的信息流测试做成凭空假设。

## 来源

- Keepa API Overview：`https://discuss.keepa.com/t/how-to-make-requests/767.json`
- Product Request：`https://discuss.keepa.com/t/products/110.json`
- Category Lookup：`https://discuss.keepa.com/t/category-lookup/113.json`
- Category Searches：`https://discuss.keepa.com/t/category-searches/114.json`

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

## 本仓库信息流测试策略

当前仓库不接真实 Keepa API，所有 live-like 行为都通过离线机制验证：

- `keepa_cli/fixtures/*.json`：随 Python 包发布的官方形状示例响应。
- `tests/fixtures/*.json`：测试用固定响应。
- `RecordingOpener` / `ReplayOpener`：为未来手动 live smoke 留 record/replay 接口。
- fake opener：在内存中模拟 gzip、429、500，不访问 `https://api.keepa.com/`。

未来如开启真实 live smoke，应使用手动触发 workflow 和 GitHub Secret `KEEPA_API_KEY`，并把录制后的 cassette 脱敏后再用于回归测试。
