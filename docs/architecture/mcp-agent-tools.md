# MCP Agent Tools 架构设计

## 背景

Keepa-cli 已经具备 `--json`、`--stdio`、结构化 `next_actions`、Agent 视图、workflow plan 和离线 fixture。下一阶段需要给 Codex、Claude Code 和其他 Agent 暴露 MCP tools，让 Agent 直接调用强类型工具，而不是拼接 CLI 字符串。

本设计基于以下调研结论：

- MCP tool 应以 `name`、`description`、`inputSchema` 为最小契约，并可补充 `outputSchema`、`annotations`、`structuredContent`。
- 成熟 MCP server 通常暴露少量任务导向 tools，而不是把完整 REST API 或 CLI 参数表原样映射出去。
- Agent 客户端对 `structuredContent` 支持程度不完全一致，tool 响应应同时提供结构化结果和 JSON text fallback。
- 长会话里的缓存、token 账本、确认阻断和 evidence index 属于 Agent 协议层能力，应独立于 CLI argparse。
- 当前项目标准库优先，因此先实现最小 MCP stdio JSON-RPC server；后续如需要 SSE、Streamable HTTP 或 SDK 高级能力，再评估接入官方 Python SDK。

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
    session.py      # AgentSession、cache_key、dedupe、budget ledger
    stdio.py        # 复用 AgentSession 的 JSON Lines transport
    tools.py        # MCP tool registry、schema、service command mapping
```

分层职责：

- `tools.py`：定义工具名、描述、输入 schema、输出 schema 摘要、确认策略和 service command 映射。
- `session.py`：维护本进程会话状态，包括 cache、dedupe、token ledger、blocked actions。
- `mcp.py`：只处理 JSON-RPC：`initialize`、`tools/list`、`tools/call` 和协议错误。
- `stdio.py`：继续提供现有 JSON Lines 协议，但调用同一个 `AgentSession`。
- `service.py`：继续承载业务命令分发，MCP 不绕过 `run_command`。

## 初始 Tool Surface

第一阶段只暴露高价值、低歧义、Agent 常用 tools：

| MCP tool | service command | 目的 | 默认风险 |
| --- | --- | --- | --- |
| `keepa.products_get` | `products.get` | 单 ASIN/少量 ASIN 产品研究，含 `risk_taxonomy` 与 `research_graph` | 低；`offers`、`rating`、`buybox` 可能增量成本 |
| `keepa.products_compare` | `products.compare` | 多 ASIN deal/research 横向对比，含统一风险汇总与合并图谱 | 低；`offers` 可能增量成本 |
| `keepa.categories_search` | `categories.search` | 关键词找候选 category | 低 |
| `keepa.categories_products` | `categories.products` | category 生成商品候选 | 高；真实请求需确认 |
| `keepa.finder_query` | `finder.query` | Product Finder selection 查询 | 中高；真实请求需确认 |
| `keepa.audit_cost` | `audit.cost` 或预算估算包装 | 估算命令成本和确认需求 | 低，本地计算 |

后续可选 toolset：

- `research`：产品、类目、finder、workflow plan。
- `audit`：cost、cache explain、schema generate、cassette sanitize。
- `reports`：batch、report、browse。
- `tracking`：默认只读；写操作需要显式启用 toolset 和确认。

第一阶段不做 toolset 开关，但工具 registry 应预留 `groups` 字段，后续可按客户端能力动态过滤。

## Tool 命名与参数策略

工具名使用 `keepa.<resource>_<action>`，原因是部分 MCP 客户端对点号命名空间展示更清晰，同时下划线避免 action 再分层造成歧义。

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
      "tool": "keepa.categories_products",
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

`risk_taxonomy` 使用稳定枚举，当前已知 code 为 `data_missing`、`price_unstable`、`rank_declining`、`low_review_count`、`offer_competition_high`、`buybox_missing`、`category_mismatch`。每个 item 必须给出 `severity`、`reason`、`evidence_path`，可补充 `metric` 与 `follow_up`，让 Agent 能做确定性断言而不是解析自然语言。

`research_graph` 使用轻量实体关系结构：`nodes` 包含 `product`、`brand`、`manufacturer`、`category`、`seller`、`variation` 等类型；`edges` 包含 `made_by`、`manufactured_by`、`in_category`、`parent_of`、`buybox_sold_by`、`variation_of`、`has_variation`。`products.compare` 会额外输出合并后的 `research_graph` 与 `risk_summary`，便于多 ASIN 研究。

新增 MCP 层 provenance：

```json
{
  "mcp": {
    "server": "keepa",
    "tool": "keepa.products_get",
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
  - `tools/list` 包含产品、类目、finder、audit tools。
  - `tools/call keepa.categories_search` 使用 fixture 返回 `category_candidates`。
  - `tools/call keepa.products_compare` 使用 fixture 返回风险汇总与合并图谱。
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

所有测试默认 fixture/dry-run，不访问真实 Keepa API。

## 实施顺序

1. 新增 `agent/tools.py`，冻结初始 5 个 MCP tool schema。（已完成）
2. 新增 `agent/session.py`，实现 cache key、dedupe、ledger。（已完成）
3. 改造 `agent/stdio.py`，让 stdio 复用 `AgentSession`，保持旧输出兼容。（已完成）
4. 新增 `agent/mcp.py`，实现最小 JSON-RPC stdio server。（已完成）
5. 在 `cli.py` 增加 `--mcp` 入口，避免扩展过多 argparse 子树。（已完成）
6. 更新 `capabilities`，暴露 MCP server 启动方式和 tool schema 版本。（已完成）
7. 补测试、README、`docs/agent-contract.md`。（已完成）
8. 落地 `research_graph`、统一 `risk_taxonomy`，并让 evaluation specs 断言 Agent 语义质量。（已完成）
9. 再进入 P2：`fixtures promote` 与 toolset 动态过滤。

## 迁移风险

- MCP 客户端对 `structuredContent` 支持不一致：用 JSON text fallback 降级。
- tool schema 太大导致上下文污染：只暴露少量任务导向 tools，后续按 toolset 动态加载。
- session cache 意外缓存 live raw body：第一阶段只进程内、只缓存 redacted envelope。
- CLI 与 MCP 参数别名漂移：所有映射集中在 `agent/tools.py`，测试直接验证 tool params 到 service command。
- 预算账本和真实 token 消耗不一致：真实响应优先，缺失时显式标记 `consumed_source=estimated_fallback`。

## 后续最佳方向

完成本设计后，最适合的实现顺序是：

1. 做 cassette promotion workflow，把真实响应脱敏后稳定沉淀为 fixture。
2. 增加 toolset 过滤，按 `research/audit/reports/tracking` 控制 MCP 工具暴露面。
3. 后续按需增加远程 MCP transport 或官方 Python SDK 适配。

这样可以先稳定 Agent 调用边界，再增强产品研究语义，避免协议层和分析层互相耦合。
