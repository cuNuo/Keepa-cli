# Keepa CLI 功能完善与完整开发路线

生成时间：2026-05-09 19:23 +08:00

## 1. 目标重述

`keepa-cli` / `kc` 要做成一个双入口完全等价的 Keepa API 工具：

- 面向人类：默认打开易用的交互界面，能搜索、选择、预览 token 成本、查看详情、导出数据。
- 面向 agent：通过 `--json`、`--stdio` 和显式子命令提供稳定、无 ANSI、可解析的机器接口。
- 面向工程：可测试、可缓存、可审计、可在 GitHub Actions 中验证，且不泄露 Keepa API key。

核心原则：先形成低成本、只读、可验证闭环，再扩展高 token 成本和长期副作用能力。

## 2. 还可以继续完善的功能

### 2.1 必须补齐：双入口一致性

必须保证 `keepa-cli` 与 `kc` 都能调用所有能力：

- 默认交互界面：`keepa-cli` 与 `kc` 都进入同一个工作台。
- Agent 模式：`keepa-cli --json ...`、`kc --json ...`、`keepa-cli --stdio`、`kc --stdio` 行为一致。
- 全部子命令：查询、导出、缓存、配置、raw request、doctor 都同步可用。
- 测试门禁：每新增一个命令，必须同时测试两个入口。

技术落点：同一个 Typer app，两个 console script 指向同一入口函数；不要维护两套路由。

### 2.2 必须补齐：人类交互工作台

默认界面不应只是命令帮助页，应提供可连续操作的工作台：

- 顶部状态：认证来源、默认 domain、token bucket、缓存状态、最近请求。
- 快捷动作：产品查询、关键词搜索、分类搜索、卖家查询、Deals、历史导出、配置、doctor。
- Slash 命令：`/search`、`/product`、`/history`、`/deals`、`/seller`、`/domain`、`/cache`、`/doctor`、`/quit`。
- 高成本确认页：展示 endpoint、预计 token、最坏 token、是否 live update、是否写文件、是否缓存命中。
- 查询结果页：列表、详情、快速导出、复制 ASIN、再次查询同品牌/分类/卖家。

建议第一版用 Rich/Textual 风格的终端界面，不急着做完整 Web UI。TUI 的成本更低，也更适合 CLI。

### 2.3 必须补齐：Agent 协议

Agent 需要的是确定性接口，不是漂亮界面：

- `--json`：一次命令一次 JSON envelope。
- `--stdio`：长会话 JSON Lines，支持多次请求、事件流和错误恢复。
- `--dry-run`：只生成 endpoint、参数、method、预计 token、缓存 key，不访问 Keepa。
- `--max-tokens`：硬预算，超过就拒绝。
- `--no-cache`、`--cache-ttl`：让 agent 控制新鲜度。
- `request get/post`：官方 API 更新时的逃生口。

Agent 模式必须避免等待交互输入。需要确认时返回 `confirmation_required`，并说明可用 `--yes` 或更高 `--max-tokens` 继续。

### 2.4 应该补齐：Token 预算器

Keepa CLI 的护城河不只是请求 API，而是降低误烧 token 的概率：

- 产品查询：按 ASIN 数量估算基础成本。
- `offers`：按 offer page 上限估算最坏成本。
- Product Finder：按 selection 里的 page/perPage 或目标数量估算。
- Deals：固定 5 tokens / 请求的提示。
- Best Sellers / Top Sellers：固定 50 tokens 的强提示。
- Tracking：明确提示会降低 refill rate，不只是消耗一次 token。

预算器要输出三类值：`estimated_tokens`、`worst_case_tokens`、`requires_confirmation`。

### 2.5 应该补齐：缓存与离线模式

缓存不是优化项，而是 API 成本控制能力：

- SQLite 缓存：保存 endpoint、domain、params hash、response、token cost、created_at、ttl。
- Fixture 模式：无 API key 也能跑 demo、测试和文档示例。
- Cache explain：告诉用户本次是否命中缓存、缓存何时过期、节省了多少 token。
- 缓存绕过：`--no-cache`、`--refresh`、`update=0` 时默认高风险提示。

优先缓存只读查询，不缓存 tracking 和 raw POST。

### 2.6 应该补齐：数据转化与分析能力

Keepa 原始 JSON 很大，直接打印给人和 agent 都不理想。应提供领域化输出：

- `summary`：当前 Amazon/New/Used/Buy Box 价格、sales rank、rating、review count、更新时间。
- `history export`：把 Keepa `csv` 历史展开为 CSV/JSONL。
- `history trend`：给出 30/90/180 天均价、最低价、最高价、波动率。
- `rank trend`：销售排名趋势摘要。
- `offers summary`：FBA/FBM、Buy Box、最低价、库存/配送摘要。
- `compare`：多 ASIN 横向对比价格、排名、评分、利润相关字段。
- `watchlist analyze`：读取 ASIN 列表，批量生成机会报告。

这些功能能把 CLI 从“API wrapper”提升为“选品/监控工具”。

### 2.7 可以后续做：本地 Web UI

TUI 稳定后再做 `kc browse` / `keepa-cli browse`：

- 本地只读 Web UI 展示搜索结果、商品详情、价格曲线和导出按钮。
- 使用本地缓存作为数据源，避免页面刷新重复消耗 token。
- Web UI 不保存 API key 到前端，不暴露完整请求 URL。

Web UI 是加分项，不应阻塞 MVP。

### 2.8 可以后续做：模板化工作流

成熟后可以内置工作流模板：

- `templates retail-arbitrage`：套利选品筛选。
- `templates price-drop`：价格下降扫描。
- `templates brand-monitor`：品牌或卖家监控。
- `templates category-rank`：分类榜单采集。
- `templates deal-hunter`：Deals 筛选。

每个模板都先生成 dry-run 计划，再由用户确认执行。

### 2.9 暂缓：Tracking 写操作

Tracking 不是普通查询。它会影响 token refill rate，且有长期副作用。建议放到 v1.5 或更晚：

- 默认只读查看 tracking。
- add/remove/webhook 必须 `--dry-run`、`--yes`、预算确认三层保护。
- 文档和 TUI 均明确提示它会降低 refill rate。

## 3. 范围风险与修正建议

当前最容易踩的坑：

- 过早做完整 TUI，会拖慢 API 核心闭环。
- Product Object 全字段强类型化会被 Keepa 字段变化拖累。
- Product Finder 和 Offers 很容易超预算。
- 把 tracking 放进 MVP 会扩大风险面。
- 真实 API 测试直接进 CI 会消耗 token，并引入不稳定网络依赖。

修正策略：

- TUI 第一版只做 shell + 列表 + 详情，不做复杂布局。
- Product 原始响应先保留 dict，核心摘要用小模型提取。
- 所有高成本命令先做 dry-run 和预算器。
- CI 默认只跑 fixture，live smoke 手动触发。
- Tracking 明确延后。

## 4. 推荐开发路线

### Phase 0：项目骨架与工程基线

目标：让仓库从文档仓库变成可安装、可测试的 Python CLI 项目。

交付物：

- `pyproject.toml`
- `src/keepa_cli/`
- `tests/`
- `.github/workflows/ci.yml`
- `Makefile` 或 `justfile`
- `docs/roadmaps/` 与现有报告索引

功能：

- `keepa-cli --help`
- `kc --help`
- `keepa-cli --version`
- `kc --version`

验收：

- `uv run pytest` 通过。
- `uv run keepa-cli --help` 与 `uv run kc --help` 都可运行。
- 两个入口指向同一 app，不存在重复路由。

### Phase 1：认证、配置、doctor、domain

目标：在无 API key 的情况下也能正常诊断，形成安全配置基础。

交付物：

- `config.py`
- `auth.py`
- `domains.py`
- `commands/doctor.py`
- `commands/config.py`

功能：

- `keepa-cli --json doctor`
- `kc --json doctor`
- `keepa-cli config init`
- `kc config init`
- `keepa-cli domains list`
- `kc domains list`

验收：

- 无 key 时 `doctor` exit 0，报告 `auth_source=missing`。
- 有 `KEEPA_API_KEY` 时只显示来源，不显示明文。
- domain 支持 `US`、`1`、`com` 三种输入。

### Phase 2：HTTP 客户端、响应 envelope、raw request

目标：统一 Keepa 请求、错误、token bucket、重试与 redaction。

交付物：

- `client.py`
- `request_spec.py`
- `envelope.py`
- `errors.py`
- `commands/request.py`

功能：

- `kc --json request get /product --param domain=1 --param asin=B001GZ6QEC --dry-run`
- `keepa-cli --json request get ...`
- 统一 JSON 成功/错误 envelope。
- 429 读取 `refillIn`，5xx/超时有限重试。

验收：

- fixture 覆盖 200、400、402、405、429、500。
- 错误与 URL 不出现 API key。
- `kc` 和 `keepa-cli` 输出字段一致。

### Phase 3：Token 预算器与缓存

目标：先防误操作，再扩展 API 能力。

交付物：

- `token_budget.py`
- `cache.py`
- `commands/cache.py`

功能：

- `--dry-run`
- `--max-tokens`
- `--cache-ttl`
- `--no-cache`
- `kc cache stats`
- `kc cache clear --dry-run`

验收：

- 超预算请求拒绝执行。
- 缓存命中不访问网络。
- agent 输出包含 `estimated_tokens`、`worst_case_tokens`、`cache_hit`。

### Phase 4：P0 查询闭环

目标：完成最常用、最低风险的只读能力。

交付物：

- `commands/products.py`
- `commands/categories.py`
- `models/summary.py`

功能：

- `products get`
- `products search`
- `products by-code`
- `categories get`
- `categories search`

验收：

- 每个命令都有 `kc` / `keepa-cli` 双入口测试。
- 每个命令支持 `--json`、`--dry-run`。
- 产品详情有 human summary 和 raw JSON 两种输出。

### Phase 5：Agent `--stdio` 协议

目标：让 agent 能建立长会话，不需要反复启动进程。

交付物：

- `agent/stdio.py`
- `agent/events.py`
- `agent/schemas.py`

功能：

- `kc --stdio`
- `keepa-cli --stdio`
- JSON Lines 输入输出。
- 事件：`started`、`budget_estimated`、`cache_hit`、`request_sent`、`response`、`written`、`done`、`error`。

验收：

- 能用 fixture 输入一条 `products.get` 请求并返回完整事件流。
- 需要确认的操作返回 `confirmation_required`，不等待 stdin 交互确认。
- 协议测试不依赖真实 Keepa key。

### Phase 6：人类 TUI 工作台 MVP

目标：让普通用户不用记参数也能完成核心查询。

交付物：

- `ui/tui.py`
- `ui/screens.py`
- `ui/slash_commands.py`

功能：

- 默认 `kc` / `keepa-cli` 打开工作台。
- `/doctor`
- `/domain`
- `/search`
- `/product`
- `/history`
- `/cache`
- `/quit`

验收：

- TUI smoke test 能启动并退出。
- 高成本命令会显示确认页。
- TUI 调用同一套 command service，不复制 API 逻辑。

### Phase 7：历史导出与分析

目标：把 Keepa 原始数据变成可用数据产品。

交付物：

- `keepa_time.py`
- `history_export.py`
- `analysis.py`
- `commands/history.py`
- `commands/compare.py`

功能：

- `history export`
- `history trend`
- `products summary`
- `compare`
- CSV/JSONL 导出

验收：

- fixture 中的 `csv` 能稳定展开。
- 导出文件返回路径、行数、字段列表。
- 空历史、缺字段、不可访问商品都有明确错误。

### Phase 8：P1 高价值 API

目标：覆盖选品、卖家、榜单与 deals。

交付物：

- `commands/finder.py`
- `commands/deals.py`
- `commands/sellers.py`
- `commands/rankings.py`

功能：

- `finder query --selection-file`
- `deals query --selection-file`
- `sellers get`
- `bestsellers get`
- `topsellers list`

验收：

- 所有高成本命令默认支持 dry-run。
- `bestsellers` / `topsellers` 必须显示 50 token 提示。
- 大结果必须支持 `--out`，避免把巨大列表直接刷屏。

### Phase 9：本地 Web UI 与图表

目标：给人类用户更直观的浏览和可视化能力。

交付物：

- `commands/browse.py`
- `ui/browser.py`
- `commands/graphs.py`

功能：

- `kc browse`
- `keepa-cli browse`
- 产品详情页
- 价格图 PNG 下载
- 缓存结果浏览

验收：

- Web UI 默认只读。
- 页面读取本地缓存，不自动重复消耗 token。
- graph image 输出文件可验证存在和大小。

### Phase 10：模板、批处理、报告

目标：支持真实选品工作流。

交付物：

- `templates/`
- `commands/batch.py`
- `commands/report.py`

功能：

- 批量 ASIN 查询。
- watchlist 分析。
- category/deal/finder 模板。
- Markdown/CSV/JSON 报告。

验收：

- 批处理有并发限制和 token 预算。
- 报告中记录数据时间、domain、请求参数、token 消耗。
- 可以从缓存重放生成报告。

### Phase 11：Tracking 与 webhook

目标：谨慎开放长期副作用能力。

交付物：

- `commands/tracking.py`
- `commands/webhook.py`

功能：

- tracking list/get
- tracking add/remove
- webhook get/set/test

验收：

- 写操作必须 `--dry-run` 先验。
- 写操作必须 `--yes` 或 TUI 确认。
- 输出明确展示 `tokenFlowReduction` 风险。

### Phase 12：发布与生态

目标：让工具可被长期维护和复用。

交付物：

- GitHub Release
- 安装文档
- Codex companion skill
- 示例 fixtures
- live smoke workflow

功能：

- `uv tool install` 安装说明。
- Windows/macOS/Linux 验证。
- `gh secret set KEEPA_API_KEY` 文档。
- companion skill 教 future agent 如何安全使用 CLI。

验收：

- 新机器按 README 可安装。
- 无 key 可跑 fixture demo。
- 有 key 可跑低成本 live smoke。

## 5. 里程碑建议

### MVP

范围：Phase 0 到 Phase 4。

完成后应具备：

- `keepa-cli` / `kc` 双入口。
- `doctor`、`config`、`domains`。
- raw request dry-run。
- products/categories 查询。
- JSON envelope。
- token 预算器初版。
- fixture 测试和 CI。

### Beta

范围：Phase 5 到 Phase 7。

完成后应具备：

- `--stdio` agent 协议。
- TUI 工作台 MVP。
- 历史导出和趋势摘要。
- 双入口 TUI 和 agent 测试。

### v1.0

范围：Phase 8 到 Phase 10。

完成后应具备：

- Finder、Deals、Seller、Best Sellers、Top Sellers。
- 本地 Web 浏览和图表。
- 批处理、模板和报告。
- 缓存 explain 与成本审计。

### v1.5

范围：Phase 11 到 Phase 12。

完成后应具备：

- Tracking 和 webhook。
- 发布流程。
- companion skill。
- 跨平台安装验证。

## 6. 推荐优先级

必须先做：

1. 双入口等价。
2. doctor/config/domain。
3. request client + envelope。
4. token 预算器。
5. product/category 查询。

做完再做：

1. `--stdio`。
2. TUI shell。
3. history export。
4. finder/deals/seller/rankings。

最后再做：

1. Web UI。
2. batch/report/templates。
3. tracking/webhook。
4. companion skill。

## 7. 决策建议

推荐路线：先完成 MVP，再做 TUI 和 `--stdio`，最后扩展高成本 API。

原因：

- MVP 可以最快验证 Keepa API、认证、预算、缓存、双入口。
- TUI 需要稳定的底层 service，否则容易变成重复逻辑。
- `--stdio` 依赖稳定 envelope 和 command service。
- 高成本 API 必须等预算器成熟后再开放。

不推荐第一阶段做完整 Web UI 或 tracking。它们不是核心闭环，且会放大维护和误操作风险。
