# Keepa CLI 实现调研与落地报告

生成时间：2026-05-09 18:50 +08:00
目标：结合 Keepa 官方 API，为一个可复用、可脚本化、可远程存储到 GitHub 的 CLI 程序制定实现方案。
建议二进制名：同时提供 `keepa-cli` 和缩写 `kc`。两者都是完整一等入口，必须支持同一套交互界面、`--json`、`--stdio`、配置、查询、导出和 raw request 能力；差异只在命令名长短。
推荐技术栈：Python + Typer + HTTPX + Rich + pytest + ruff。

## 1. 结论摘要

建议先做一个只读、额度安全优先、默认方便人类使用的 Keepa CLI，而不是一开始覆盖所有 API。第一版聚焦 `product`、`search`、`query`、`deal`、`category`、`seller`、`bestsellers`、`topseller`、`graphimage` 等查询类能力；`tracking` 会降低 token refill rate，建议作为第二阶段并默认要求 `--dry-run` / `--yes`。

CLI 的核心价值不是把 REST API 简单包一层，而是把 Keepa 的 token 成本、分页/批量、gzip/keep-alive、`csv` 历史数据、错误响应与缓存策略固化成可审计命令。默认模式应像 Claude Code 一样进入交互式工作台，支持搜索、选择、预览、确认、导出和历史记录；结构化参数主要服务 agent，通过 `--json`、`--stdio` 和显式子命令提供稳定机器接口。

GitHub 远程建议使用私有仓库保存初始报告与后续源码，避免误传 API key。真实 API key 不进仓库，只通过本机环境变量 `KEEPA_API_KEY`、用户配置文件或 GitHub Secrets 注入。

新增强约束：

- `keepa-cli` 与 `kc` 必须都是一等入口，不允许出现某个入口功能不全。
- 人类入口优先做交互界面；参数化命令优先服务 agent 和脚本。
- 默认交互模式不得隐藏 token 成本，高成本操作必须先预览再确认。
- agent 模式必须稳定、无 ANSI、可解析，避免依赖 TUI 屏幕抓取。

## 2. 资料来源与时效

本报告调研了以下一手或权威资料：

- Keepa API 页面：`https://keepa.com/#!api`
- Keepa 官方 API 论坛文档：`https://discuss.keepa.com/t/how-to-make-requests/767`
- Product Request：`https://discuss.keepa.com/t/products/110`
- Product Object：`https://discuss.keepa.com/t/product-object/116`
- API Plans：`https://discuss.keepa.com/t/how-our-api-plans-work/410`
- Product Finder：`https://discuss.keepa.com/t/product-finder/5473`
- Browsing Deals：`https://discuss.keepa.com/t/browsing-deals/338`
- Category Lookup：`https://discuss.keepa.com/t/category-lookup/113`
- Seller Information：`https://discuss.keepa.com/t/seller-information/790`
- Keepa 官方 Java 框架：`https://github.com/keepacom/api_backend`
- Python 第三方 Keepa 包：`https://pypi.org/project/keepa/` 与 `https://keepaapi.readthedocs.io/en/stable/`
- GitHub CLI 格式化与 `gh api`：`https://cli.github.com/manual/gh_help_formatting`、`https://cli.github.com/manual/gh_api`
- AWS CLI 输出与过滤：`https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-output-format.html`
- Stripe CLI：`https://docs.stripe.com/cli`
- Claude Code CLI reference：`https://code.claude.com/docs/en/cli-reference`
- Claude Code interactive mode：`https://code.claude.com/docs/en/interactive-mode`
- Claude Code slash commands / skills：`https://code.claude.com/docs/en/slash-commands`
- zread CLI 本机帮助：`zread --help`、`zread browse --help`、`zread generate --help`
- Typer 文档：`https://typer.tiangolo.com/`
- HTTPX 文档：`https://www.python-httpx.org/`

价格和套餐信息以 2026-05-09 访问 Keepa 页面时可见内容为准，后续实现前需要再次核验。

## 3. Keepa API 要点

### 3.1 请求协议

Keepa API 基础地址是 `https://api.keepa.com/`。官方文档要求请求通过 HTTPS 发起，携带 API access key，接受 gzip 编码，并尽量复用 Keep-Alive 连接。官方 Java 框架构造的 URL 形如：

```text
https://api.keepa.com/<path>?key=<accessKey>&...
```

官方论坛文档说所有请求必须使用 HTTPS GET；但官方 Java 框架和具体文档又对 `query`、`deal`、`tracking` 等复杂 JSON 请求支持 POST。CLI 应按端点做保守处理：简单查询用 GET，大 selection JSON 或批量 tracking 用 POST。

### 3.2 Token bucket 与响应元信息

每个 JSON 响应都会带 API 额度信息：

- `refillRate`：每分钟生成 token 数。
- `refillIn`：距离下一次补充 token 的毫秒数。
- `tokensLeft`：当前 token 余额，可能为负，因为提交时余额为正即可执行大请求。
- `tokensConsumed`：本次请求消耗 token。
- `tokenFlowReduction`：tracking 产品造成的实际 refill rate 折减。
- `error`：请求或部分批量项的错误信息。

官方计划采用 token bucket。未用 token 60 分钟后过期。常见状态码：

- `200`：成功。
- `400`：请求 malformed 或执行失败。
- `402`：API key 无访问权限或套餐不足。
- `405`：参数超出范围。
- `429`：token 不足。
- `500`：服务端异常。

CLI 必须把这些字段纳入统一 envelope，并在 429 时优先读取 `refillIn` 后等待；5xx 或网络超时最多做有限重试，避免无限烧额度。

### 3.3 Domain ID

常用 Amazon locale 映射：

| domainId | locale |
|---:|---|
| 1 | `com` |
| 2 | `co.uk` |
| 3 | `de` |
| 4 | `fr` |
| 5 | `co.jp` |
| 6 | `ca` |
| 8 | `it` |
| 9 | `es` |
| 10 | `in` |
| 11 | `com.mx` |
| 12 | `com.br` |

CLI 应允许 `--domain US`、`--domain 1`、`--domain com` 三种输入，并在 JSON 输出中规范成 `domain_id` 与 `locale`。

### 3.4 主要端点与成本

| 能力 | 端点 | 关键成本与限制 | CLI 优先级 |
|---|---|---|---|
| Product Request | `/product` | 通常 1 token / ASIN；ASIN 批量最多 100；使用 `offers` 时按 offer page 加额外成本，官方 Java 注释建议最多 20 ASIN | P0 |
| Product Search | `/search?type=product` | 10 tokens，最多 20 结果 | P0 |
| Category Search | `/search?type=category` | 1 token，最多 50 分类 | P0 |
| Product Finder | `/query` | 10 tokens + 每 100 ASIN 1 token；`stats=1` 额外较高成本 | P1 |
| Deals | `/deal` | 5 tokens，最多 150 deals | P1 |
| Category Lookup | `/category` | 1 token / category，父树另计；批量最多 10 | P0 |
| Seller Information | `/seller` | 1 token / seller，批量最多 100；`storefront` 会带更大响应和额外成本 | P1 |
| Best Sellers | `/bestsellers` | 50 tokens；root category 可达 500,000 ASIN，子分类通常 10,000，display group 可达 100,000 | P1 |
| Top Sellers | `/topseller` | 50 tokens，最多 100,000 seller IDs | P1 |
| Graph Image | `/graphimage` | 1 token / PNG；相同请求缓存 90 分钟内不再消耗 token | P2 |
| Tracking | `/tracking` | 增加 tracking 会降低 token refill rate | P3 |

### 3.5 Product Request 参数建议

第一版应覆盖：

- `asin` / `code`：二选一，code 支持 UPC、EAN、ISBN-13。
- `stats`：支持天数或日期区间。
- `history`：默认 `0`，只在用户需要完整历史 `csv` 时开启，减少流量。
- `update`：默认沿用 Keepa 默认；`0` 代表尽量实时，可能额外消耗 token；`-1` 表示不更新，适合只查历史库中已有数据。
- `offers`：高成本参数，必须先估算成本，建议要求 `--max-tokens` 或 `--yes`。
- `only-live-offers`：减少 offer 响应体。
- `buybox`、`rating`、`stock`：可选高价值字段，但要在帮助文本中写清额外成本风险。

Keepa price、rank、rating 历史数据大量放在 `csv` 二维数组里，时间使用 Keepa 自身分钟时间或相对编码。CLI 应提供轻量转换函数，例如 `history export` 把价格历史展开成普通 CSV，而不是强迫用户理解内部数组。

## 4. 成熟 CLI 模式借鉴

### 4.1 GitHub CLI

`gh` 的优秀点是普通输出适合人读，`--json` 加字段选择适合脚本，`--jq` 适合快速过滤；`gh api` 作为 raw escape hatch，复用认证、分页、缓存和 JSON 处理。Keepa CLI 应采用相同思路：高频端点有专门子命令，缺失能力通过 `request get/post` 暴露。

### 4.2 AWS CLI

AWS CLI 的 `--output json/yaml/text/table`、`--query`、profile/config 分层值得借鉴。Keepa CLI 不需要一开始支持全部格式，但至少要保证 `--json` 完整稳定，并在后续加 `--query` 或 `--jq` 风格过滤前先保持服务端过滤优先。

### 4.3 Stripe CLI

Stripe CLI 的 `listen`、`trigger`、`fixtures` 展示了产品工作流命令的价值。Keepa CLI 可以借鉴 fixture 思路：用离线 fixture 做 request builder、错误处理、JSON envelope 和历史数据转换测试，真实 API 只在用户显式提供 key 时运行。

### 4.4 Claude Code

Claude Code 的核心启发是默认进入交互会话，而不是要求用户记住大量参数。官方 CLI reference 提供 `--print/-p` 非交互模式，以及 `--output-format text|json|stream-json`、`--input-format text|stream-json` 等面向程序调用的接口；interactive mode 则提供快捷键、命令历史、slash commands、shell 前缀和可切换模式。

Keepa CLI 应采用类似分层，但 `keepa-cli` 与 `kc` 两个入口都必须支持这些层：

- `kc` / `keepa-cli`：进入交互式 Keepa 工作台。
- `kc /doctor` / `keepa-cli /doctor`：交互界面内的 slash-style 快捷命令。
- `kc -p ... --json` / `keepa-cli -p ... --json` 或显式子命令：agent/脚本使用，不启动 TUI。
- 高成本请求像权限门一样显示预计 token、缓存命中、是否触发 live update，再由用户确认。

### 4.5 zread CLI

zread 的关键经验是把人类体验和 agent 接口分开：`zread browse` 打开本地浏览器界面，`zread generate` 面向交互式生成；所有命令都支持 `--stdio`，给 agent 提供机器可读协议，而不是让 agent 解析 TUI。

Keepa CLI 应借鉴：

- 人类默认走 `kc` / `keepa-cli` / `kc browse` / `keepa-cli browse` 的 TUI 或本地 Web UI。
- agent 默认走 `kc --stdio` / `keepa-cli --stdio` 或 `kc --json <subcommand>` / `keepa-cli --json <subcommand>`。
- 长流程必须有事件流：`started`、`budget_estimated`、`cache_hit`、`request_sent`、`response_received`、`written`、`done`、`error`。
- 交互确认在 agent 模式下必须转成显式字段，例如 `requires_confirmation`，不能停在等待输入。

## 5. 技术栈比较

### 方案 A：Python Typer + HTTPX（推荐）

优点：

- 当前机器已有 Python 与 uv，启动成本最低。
- Typer 适合类型注解、子命令、自动 help 和 shell completion。
- HTTPX 支持连接池、timeout、headers、JSON POST，适合 Keepa 的 keep-alive/gzip 模式。
- Python 更适合后续做 CSV、SQLite 缓存、价格历史转换和数据分析。

缺点：

- 不是单文件二进制，发布时需要 `uv tool install` 或 wheel。

### 方案 B：基于第三方 `keepa` Python 包包装 CLI

优点：

- 可以快速复用 `query`、`product_finder`、异步客户端和部分历史数据处理。

缺点：

- 第三方包可能落后于官方最新端点和字段。
- token 成本、raw request、错误 envelope、GitHub Actions fixture 测试仍需自己封装。

建议：可以作为参考或局部复用，但 CLI 的 HTTP 层和命令契约最好自己控制。

### 方案 C：Node.js + commander/cac + undici

优点：

- 当前机器已有 Node，发布 npm 包方便。
- JSON 与命令构建直接。

缺点：

- 对价格历史 CSV、数据导出和后续分析不如 Python 顺手。

### 方案 D：Rust + clap + reqwest

优点：

- 单二进制、速度快、部署稳定。

缺点：

- 当前机器未发现 Rust 工具链；对本项目第一阶段增加 setup 摩擦。

## 6. 推荐命令面

### 6.1 双入口约定

全局约定：

```bash
kc
kc --help
kc --json doctor
kc --stdio
kc browse
keepa-cli --help
keepa-cli --json doctor
keepa-cli config init
keepa-cli domains list
```

`kc` 与 `keepa-cli` 必须完全等价。任何示例中使用 `kc` 的地方，都可以替换成 `keepa-cli` 后得到相同行为；任何示例中使用 `keepa-cli` 的地方，也可以替换成 `kc`。Python 实现时在 `pyproject.toml` 中同时配置两个 console script：

```toml
[project.scripts]
keepa-cli = "keepa_cli.cli:app"
kc = "keepa_cli.cli:app"
```

交互界面两个入口都必须支持：

```bash
kc
keepa-cli
kc /search "coffee grinder"
keepa-cli /search "coffee grinder"
kc /product B001GZ6QEC
kc /export B001GZ6QEC --price AMAZON
```

显式参数子命令两个入口也都必须支持：

```bash
kc --json doctor
keepa-cli --json doctor
kc --json products get B001GZ6QEC --domain US --history 0
keepa-cli --json products get B001GZ6QEC --domain US --history 0
kc --stdio
keepa-cli --stdio
keepa-cli --json request get /product --param domain=1 --param asin=B001GZ6QEC
```

### 6.2 人类交互界面

默认执行 `kc` 或 `keepa-cli` 都应打开终端工作台，第一屏显示：

- API key 状态：只显示来源和是否存在，不显示明文。
- token bucket：`tokensLeft`、`refillRate`、`refillIn`、`tokenFlowReduction`。
- 默认 marketplace / domain。
- 最近查询历史、缓存命中统计、常用动作。
- 快捷入口：搜索产品、查 ASIN、导出历史、查看 deals、分类浏览、卖家查询、配置、doctor。

交互界面内建议支持 slash-style 命令：

```text
/help
/doctor
/domain US
/search coffee grinder
/product B001GZ6QEC
/offers B001GZ6QEC --limit 20
/history B001GZ6QEC --price AMAZON
/deals
/cache
/config
/quit
```

搜索类交互流程：

1. 输入关键词或 ASIN。
2. 显示预计 token 成本和是否可用缓存。
3. 展示结果列表，支持上下选择、过滤、排序、打开详情。
4. 详情页显示价格、Buy Box、排名、评分、库存、历史趋势摘要。
5. 支持导出 JSON/CSV/PNG graph。

高成本流程必须先显示确认页。确认页至少包含 endpoint、domain、预计 token、最坏 token、是否 live update、是否写文件、是否命中缓存。

### 6.3 Agent 参数命令

Product：

```bash
kc --json products get B001GZ6QEC --domain US --history 0 --stats 90
kc --json products get B001GZ6QEC B08N5WRWNW --domain 1
kc --json products get B001GZ6QEC --offers 20 --only-live-offers --max-tokens 20
kc --json products search "coffee grinder" --domain US --asins-only
kc --json products by-code 9780786222728 --domain US --code-limit 5
```

Product Finder 与 Deals：

```bash
kc --json finder query --domain US --selection-file selection.json --dry-run
kc --json finder query --domain US --selection-file selection.json --max-tokens 100
kc --json deals query --selection-file deals.json
```

分类、卖家、榜单：

```bash
kc --json categories search "home kitchen" --domain US
kc --json categories get 1055398 --domain US --parents
kc --json sellers get A2L77EE7U53NWQ --domain US
kc --json sellers get A2L77EE7U53NWQ --domain US --storefront --max-tokens 50
kc --json bestsellers get 1055398 --domain US --out asins.txt
kc --json topsellers list --domain US --out sellers.txt
```

图表、历史导出、原始请求：

```bash
kc graphs image B001GZ6QEC --domain US --out graph.png
kc history export B001GZ6QEC --domain US --price-type AMAZON --out history.csv
kc --json request get /product --param domain=1 --param asin=B001GZ6QEC
kc --json request post /query --json-body selection.json
```

Tracking 第二阶段再做：

```bash
kc --json tracking add --file tracking.json --dry-run
kc --json tracking remove B001GZ6QEC --yes
```

### 6.4 `--stdio` 协议

`kc --stdio` 与 `keepa-cli --stdio` 面向 agent 长会话，使用 JSON Lines。输入示例：

```json
{"id":"1","method":"products.get","params":{"domain":"US","asin":["B001GZ6QEC"],"history":0}}
```

输出事件示例：

```json
{"id":"1","event":"budget_estimated","estimated_tokens":1,"max_tokens":1}
{"id":"1","event":"response","ok":true,"token_bucket":{"tokens_consumed":1},"data":{}}
{"id":"1","event":"done"}
```

agent 模式不得使用交互式确认；凡是需要确认的命令必须返回：

```json
{"ok":false,"error":{"kind":"confirmation_required"},"resume_with":"--yes","estimated_tokens":50}
```

## 7. JSON 输出契约

建议所有 `--json` 成功响应使用统一 envelope：

```json
{
  "ok": true,
  "command": "products.get",
  "request": {
    "endpoint": "/product",
    "domain_id": 1,
    "params_redacted": {
      "asin": "B001GZ6QEC",
      "history": 0
    }
  },
  "token_bucket": {
    "refill_rate": 20,
    "refill_in_ms": 12000,
    "tokens_left": 123,
    "tokens_consumed": 1,
    "token_flow_reduction": 0
  },
  "data": {}
}
```

错误响应：

```json
{
  "ok": false,
  "command": "products.get",
  "error": {
    "status_code": 429,
    "kind": "not_enough_token",
    "message": "token 不足",
    "retry_after_ms": 12000
  },
  "token_bucket": {
    "tokens_left": -3,
    "refill_in_ms": 12000
  }
}
```

规则：

- stdout 只输出人读文本或 JSON；进度、重试、缓存命中写 stderr。
- `--json` 下不得输出颜色、日志或 API key。
- `--stdio` 下 stdout 只输出 JSON Lines 事件；stderr 仅保留非协议级诊断。
- 成功但空结果仍 exit 0；认证、参数、网络、解析、API 错误 exit 非 0。

## 8. 认证与配置

优先级：

1. 环境变量：`KEEPA_API_KEY`。
2. 用户配置：Windows `%APPDATA%\keepa-cli\config.toml`，其他系统 `~/.config/keepa-cli/config.toml`。
3. `--api-key`：仅允许一次性测试，帮助文本提示可能进入 shell history，不推荐。

配置示例：

```toml
default_domain = "US"
cache_ttl_seconds = 3600
max_tokens_per_request = 20
```

`doctor` 默认只检查本地配置、版本、依赖和 key 是否存在，不发起耗 token 请求。`doctor --live` 才进行真实 API 探测，并在执行前明确显示预计成本。

## 9. Token 安全与缓存策略

必须实现的保护：

- 请求前做粗略成本估算，`offers`、`finder`、`bestsellers`、`topseller`、`tracking` 默认进入高成本路径。
- 提供 `--dry-run` 输出 endpoint、参数、预计 token、是否 POST、是否会写入文件。
- 提供 `--max-tokens`，超过预算直接拒绝。
- 429 时读取 `refillIn`，等待 `refillIn + 100ms` 后重试；5xx 或网络超时退避后最多重试 1 次。
- 默认缓存 product/search/category/seller 的只读响应；`update=0`、tracking、raw POST 默认不缓存。
- graphimage 相同请求可利用官方 90 分钟缓存，同时本地也可按 hash 缓存文件。

## 10. 项目结构建议

```text
Keepa-cli/
  README.md
  pyproject.toml
  src/
    keepa_cli/
      __init__.py
      cli.py
      config.py
      auth.py
      domains.py
      client.py
      envelope.py
      token_budget.py
      cache.py
      ui/
        tui.py
        slash_commands.py
        screens.py
        browser.py
      agent/
        stdio.py
        events.py
        schemas.py
      commands/
        products.py
        finder.py
        deals.py
        categories.py
        sellers.py
        rankings.py
        graphs.py
        request.py
      keepa_time.py
      history_export.py
  tests/
    fixtures/
    test_request_builders.py
    test_token_budget.py
    test_envelope.py
    test_redaction.py
    test_history_export.py
  docs/
    reports/
  evidence/
    tasks/
  .github/
    workflows/
      ci.yml
      live-keepa-smoke.yml
```

## 11. 实施路线

### 阶段 0：仓库与远程

- 初始化 Git 仓库。
- 创建私有 GitHub 仓库 `cuNuo/Keepa-cli`。
- 提交报告、README、`.gitignore`。
- 添加 GitHub Actions 基础 CI，但不放真实 API key。

### 阶段 1：CLI 骨架

- 创建 `pyproject.toml`，同时配置 console script `keepa-cli=keepa_cli.cli:app` 与 `kc=keepa_cli.cli:app`。
- 加 `typer`、`httpx`、`rich`、`platformdirs`、`pydantic` 或轻量 dataclass。
- 实现 `--help`、`--version`、`doctor`、`config init`、`domains list`。
- 实现默认 `kc` / `keepa-cli` 交互工作台骨架，至少包含 doctor、domain、search、product、cache、quit。
- 实现 `kc --json ...`、`keepa-cli --json ...`、`kc --stdio`、`keepa-cli --stdio` 的无 ANSI agent 通道。

### 阶段 2：HTTP 客户端与请求构造

- `KeepaClient` 统一 base URL、gzip、keep-alive、timeout、User-Agent。
- `RequestSpec` 负责 endpoint、method、params、json_body、estimated_tokens。
- `ResponseEnvelope` 负责 token bucket、错误映射和输出。
- 测试 key redaction，确保 URL 和错误中不出现明文 key。

### 阶段 3：P0 查询命令

- `products get`
- `products search`
- `products by-code`
- `categories get`
- `categories search`
- `request get/post`

每个命令都要有 fixture 测试和 `--dry-run` 测试。

### 阶段 4：P1 高价值命令

- `finder query`
- `deals query`
- `sellers get`
- `bestsellers get`
- `topsellers list`

这些命令默认要求预算约束，避免一次请求让 token 余额变负。

### 阶段 5：导出与缓存

- SQLite 或文件缓存，key 由 endpoint + domain + params hash 组成。
- `history export` 展开 Keepa `csv` 历史。
- `graphs image` 下载 PNG 并返回文件路径、大小、缓存状态。

### 阶段 6：可选 tracking

- 只在用户明确需要时实现。
- 所有新增、删除、webhook 更新都要求 `--dry-run` 先验和 `--yes` 确认。
- 在文档里解释 tracking 会降低 `refillRate`，不是普通查询。

## 12. 测试与质量门禁

最小本地验证：

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run keepa-cli --help
uv run kc --help
uv run keepa-cli --json doctor
uv run kc --json doctor
```

无 key 情况必须通过：

- `doctor` 报告 `auth_source=missing`，exit 0。
- `keepa-cli` 与 `kc` 两个入口都存在，交互界面、`--help`、`--json doctor`、`--stdio` 与所有子命令能力一致。
- 默认 `kc` 和默认 `keepa-cli` 的 TUI smoke test 都可启动并退出；CI 中用测试后端或快照，不依赖真实终端。
- `kc --stdio` 与 `keepa-cli --stdio` 都能接收一条 fixture 请求并返回 JSON Lines 事件。
- request builder 测试不访问网络。
- fixture 响应解析测试覆盖 200、400、402、405、429、500。

有 key 情况只在手动触发：

```bash
KEEPA_API_KEY=... uv run keepa-cli products get B001GZ6QEC --domain US --history 0 --json
```

GitHub Actions：

- `ci.yml`：无 secret，运行格式化、lint、unit tests。
- `live-keepa-smoke.yml`：`workflow_dispatch` 手动触发，读取 GitHub Secret `KEEPA_API_KEY`，只执行低成本 smoke test。

## 13. GitHub 远程存储方案

建议远程仓库：

```text
https://github.com/cuNuo/Keepa-cli
```

推荐初始化命令：

```bash
git init
git add README.md .gitignore docs/reports/2026-05-09-keepa-cli-implementation-report.md evidence/tasks/20260509-1850-keepa-cli调研报告.md
git commit -m "docs: add keepa cli implementation report"
gh repo create cuNuo/Keepa-cli --private --source . --remote origin --push
```

后续 secret 管理：

```bash
gh secret set KEEPA_API_KEY --repo cuNuo/Keepa-cli
```

注意：不要把 key 写入 `.env` 后提交；`.gitignore` 已忽略 `.env*`、`*.key`、本地缓存和 Playwright 临时目录。

## 14. 风险、假设与应对

风险：

- Keepa 官方论坛文档与前端页面会更新，价格与 token 成本必须在编码前复核。
- Product Object 字段很多且变化频繁，第一版不要把所有字段做成强类型模型，否则维护成本高。
- Product Finder 与 Deals 的 selection JSON 很大，命令行参数形式容易变复杂，第一版应优先 `--selection-file`。
- `tracking` 会降低 token refill rate，误操作成本高，不适合 MVP。
- `offers`、`bestsellers`、`topseller` 会明显消耗 token，需要预算保护。

假设：

- 用户已有或会购买 Keepa API 套餐。
- CLI 第一阶段以查询、导出和自动化分析为主，不需要管理 tracking。
- GitHub 远程仓库优先私有，除非明确要开源。
- 无迁移，直接新建项目骨架。

## 15. 超出当前思路的优化建议

1. 做一个 token 预算器而不仅是 API wrapper：每条命令先显示预计成本、最大成本和是否可能触发余额为负。
2. 引入离线 fixture 模式：没有 Keepa key 也能开发、测试和演示 CLI，降低调试成本。
3. 把历史数据转换作为核心卖点：提供 `history export`、`current price`、`rank trend`，而不只是打印巨大 Product JSON。
4. 设计 Codex companion skill：CLI 稳定后写一个小 skill，未来 Codex 线程可以先跑 `keepa-cli --json doctor`，再按任务自动选择查询命令。
5. 将缓存做成可解释缓存：`--cache-info` 返回缓存 key、TTL、源请求和 token 节省估计，方便审计。

## 16. 推荐下一步

下一步直接进入实现阶段：

1. 用 Python/uv 初始化项目。
2. 同时暴露 `keepa-cli` 与 `kc`，两个入口默认都启动人类交互工作台，且所有子命令完全等价。
3. 实现 `doctor`、`domains list`、`products get`、`products search`、`request get/post`。
4. 实现 `--json` 与 `--stdio` 两个 agent 通道。
5. 加 fixture 测试、TUI smoke test 和 GitHub Actions。
6. 再扩展 finder、deals、seller、bestsellers 和 graphimage。

第一版完成标准：`kc` 和 `keepa-cli` 都能启动人类友好的交互界面；`keepa-cli --json doctor` 与 `kc --json doctor` 在无 key 下可用；两个入口都能调用 `products get/search`；两个入口的 agent 通道都输出稳定 JSON 或 JSON Lines；CI 在 GitHub 上通过。
