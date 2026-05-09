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
{"id":"1","event":"budget_estimated","estimated_tokens":0,"worst_case_tokens":0,"requires_confirmation":false}
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
.\.venv\Scripts\python.exe -m keepa_cli --json products search "coffee grinder" --domain US --fixture product_search_coffee.json
```

`products.get` 按官方 Product Request 映射到 `/product`，支持 `asin` 或 `--code`，但二者不能同时使用。`products.search` 映射到 `/search` 并设置 `type=product`。当前测试默认使用 fixture/offline，不接真实 API。

### categories get/search

```powershell
.\.venv\Scripts\python.exe -m keepa_cli --json categories get 0 --domain US --parents --fixture category_roots_US.json
.\.venv\Scripts\python.exe -m keepa_cli --json categories search "home kitchen" --domain US --fixture category_search_home.json
```

`categories.get` 按官方 Category Lookup 映射到 `/category`，支持最多 10 个 category id，`0` 表示 root categories。`categories.search` 映射到 `/search` 并设置 `type=category`。

## 5. Fixture

当前 fixture：

```text
tests/fixtures/product_B001GZ6QEC.json
tests/fixtures/product_search_coffee.json
tests/fixtures/category_roots_US.json
tests/fixtures/category_search_home.json
```

用途：

- 无 Keepa key 时验证 client 解析与 token bucket 映射。
- 为后续 `products.get`、history export、schema regression 提供稳定样本。
- 为 `products.search`、`categories.get`、`categories.search` 提供不接 API 的信息流样本。
- CI 默认只跑 fixture，不消耗真实 Keepa token。

## 6. TUI 边界

默认无参数执行 `keepa-cli` 或 `kc` 会进入标准库 TUI 工作台。当前支持 slash 命令：

```text
/doctor
/domains
/product B001GZ6QEC --domain US --fixture product_B001GZ6QEC.json
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
