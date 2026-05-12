# MCP Python SDK adapter 对照

## 结论

Keepa-cli 当前应继续保留手写 JSON-RPC stdio transport 作为生产入口，同时把官方 Python MCP SDK adapter 作为受控 spike，并在共享 tool registry 调用层补强 JSON Schema 入参校验。原因是现有实现已经围绕 `run_command`、`AgentSession`、toolset/profile gating、MCP resources/templates、prompts、chunk/output resources 和 budget ledger 形成稳定契约；直接切换 FastMCP 会带来依赖、协议形状和 session cache 迁移风险。

## 对照范围

- 当前生产入口：`keepa_cli/agent/mcp.py`，通过 `python -m keepa_cli --mcp` 或 `kc --mcp` 暴露 stdio JSON-RPC。
- 当前业务入口：`keepa_cli/service.py::run_command`，CLI、stdio 与 MCP 都复用它。
- 官方 SDK 参考：Model Context Protocol Python SDK 的 FastMCP server、tool/resource/prompt decorator、stdio 运行方式和 Inspector 调试链路。
- 本轮不新增 `mcp` 运行时依赖，不改包安装依赖；公共 MCP tool/prompt 名已破坏性移除 `keepa.` 前缀。

## 能力映射

| 现有 Keepa-cli 能力 | 官方 Python SDK / FastMCP 对应 | 迁移判断 |
| --- | --- | --- |
| `initialize` / `ping` / JSON-RPC 错误 | SDK transport 自动处理 | 可迁移，但需要确认 `serverInfo`、协议版本和错误 data 是否完全可控。 |
| `tools/list` schema、`outputSchema`、annotations、`title` | `@mcp.tool`、schema 推导、annotations | 可迁移，但 Keepa-cli 动态 toolset/profile/filter/pagination 需要额外 adapter 层。 |
| `tools/call` 返回 `structuredContent` 与 text fallback | SDK tool result / structured output | 可迁移，但必须保留 `cache_key`、`cache_hit`、`budget_ledger` 和 compact text manifest。 |
| `resources/list/read` 与 `resources/templates/list` | `@mcp.resource` / resource templates | 可迁移，但当前动态 URI（cache key、encoded path、research graph）需要自定义 resolver。 |
| `prompts/list/get` | `@mcp.prompt` | 可迁移，风险较低。 |
| `AgentSession` cache、budget ledger、profile gating | 无直接内置业务语义 | 必须保留项目自有 session 层，SDK 只能做 transport/registration 外壳。 |
| 离线 fixture、dry-run、确认门禁 | 业务层逻辑 | 不应迁移到 SDK；继续留在 service/session。 |
| `tools/list` cursor 分页与 `limit` 调试参数 | 协议层 list pagination | 可迁移，但需要验证 SDK 对 list pagination 和自定义 `_meta` 的支持边界。 |

## 推荐 adapter 形状

若后续做官方 SDK spike，建议新增隔离模块，不替换当前 `--mcp`：

```text
keepa_cli/
  agent/
    mcp.py              # 现有生产 stdio JSON-RPC，继续保留
    mcp_sdk_adapter.py  # 可选实验入口，只做 SDK adapter
```

adapter 原则：

1. 不复制业务逻辑，仍通过 `get_tool_definition()`、`tool_params_to_command_params()`、`AgentSession.execute()` 调用现有服务核。
2. 不重新发明 schema，直接复用 `ToolDefinition.to_mcp_tool()` 生成的 `inputSchema`、`outputSchema` 和 annotations。
3. 不默认暴露全部工具，仍支持 toolset/profile 的 discover-first 流程；如果 SDK 无法动态分页，应通过 resource-first 文档引导客户端读取 `keepa://tools/index`。
4. 不让 SDK adapter 访问真实 Keepa API；所有 live 行为仍由 `yes`、`fixture`、`dry_run` 和 token budget 门禁控制。
5. 不在包默认依赖中引入 SDK，除非 Inspector 和至少两个真实 MCP client 的兼容性验证通过。

## Spike 验收标准

官方 SDK adapter 只有同时满足以下条件，才考虑进入生产入口：

- `initialize` 返回的 `serverInfo.name`、`title`、`protocolVersion` 与当前契约兼容，或迁移文档明确说明差异。
- `tools/list` 能保留 `title`、`inputSchema`、`outputSchema`、`annotations`、`x-keepa` metadata，且不会一次强制塞入不需要的 toolsets。
- `tools/list` 与 `prompts/list` 必须补齐生产入口的过滤与分页 parity：`toolset`、`profile`、`allow_tools`、`exclude_tools`、`limit`、`cursor` 的语义和错误映射要与 raw stdio 一致，不能只依赖 SDK typed API 的标准 cursor。
- `tools/call` 能返回 `structuredContent`、compact text fallback、`isError`，并保留 `invalid_arguments` / `inactive_tool` 等工具错误语义。
- `resources/templates/list` 能暴露当前 dynamic URI templates，`resources/read` 能处理 session cache 与 encoded local output path。
- Inspector smoke fixture、`tests.test_mcp`、Agent eval fixtures、`npm pack --dry-run --json` 全部通过。
- 不破坏 `kc --mcp` 与现有 MCP client examples。

## 失败回退

如果 SDK adapter 无法稳定表达动态 toolset/profile/pagination/resource templates，保持当前手写 stdio transport。该方案不是技术债本身：它已经足够薄，只负责 MCP JSON-RPC 协议边界，业务逻辑仍在统一 service/session 层。

## 2026-05-12 隔离 adapter 状态

- 已新增 `keepa_cli/agent/mcp_sdk_adapter.py`，作为官方 Python MCP SDK adapter 的隔离边界；生产入口仍是 `python -m keepa_cli --mcp`。
- `adapter_status()` 会报告 `sdk_available`、`server_info_name=keepa_mcp`、生产入口未替换、业务核心仍为 `AgentSession -> run_command`，并公开 SDK typed client 的默认 starter page 策略。
- `python -m keepa_cli.agent.mcp_sdk_adapter --stdio` 会启动官方 Python MCP SDK low-level `Server`，注册 tools/resources/resource templates/prompts，并继续复用现有 registry、session cache、workflow resolver 与 budget ledger。
- `create_fastmcp_readonly_spike()` 只保留为 FastMCP decorator 形态的只读样例；生产级 SDK adapter 采用 low-level Server，以便保留当前无前缀 tool 名、`structuredContent`、resource templates 和分页。
- `scripts/compare_mcp_sdk_adapter_fixture.py` 使用 `tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json` 对比当前 `--mcp` handler 与隔离 adapter 输出；`tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json` 额外覆盖 `toolset/profile/allow_tools/exclude_tools/limit/cursor` parity，包含动态复用上一页 `nextCursor` 的场景；release gate 通过 `scripts/check_mcp_quality_gate.py` 纳入这些检查。
- `scripts/smoke_mcp_sdk_adapter_client.py` 使用官方 `ClientSession` 连接 SDK stdio adapter，验证 `initialize`、分页 `list_tools`、`list_resources`、`list_resource_templates`、`list_prompts`、`call_tool context_policy` 与 `read_resource keepa://context/policy`。
- `scripts/check_mcp_sdk_adapter_typed_fixture.py` 把 `tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json` 的每个 step 映射成官方 SDK typed client 调用；SDK 不支持的 Keepa 扩展 `toolset/limit` 会记录为 mapping limitation，并继续验证完整分页、错误结构与 `ping`。
- `scripts/export_mcp_inspector_snapshot.py --check` 会通过官方 typed client 导出并校验可复现 Inspector snapshot，覆盖 serverInfo、list_* 首页、分页、错误映射和 ping。
- `scripts/check_mcp_quality_gate.py --require-sdk` 聚合 Agent eval fixture、outputSchema 离线校验、MCP performance gate、adapter fixture 等价、adapter filter parity、SDK typed smoke、typed Inspector fixture 与 snapshot 校验；远端 `mcp-sdk-adapter` job 安装 `.[mcp-sdk]` 后运行该门禁。该脚本的 `--json` 成功与失败输出都保持单一 JSON payload，失败步骤的 stdout/stderr 只进入 `steps[].*_tail`，便于 Agent 和 CI 解析。CI 会通过 `--performance-out artifacts/mcp-performance/...` 上传完整 performance JSON；后续用 `scripts/summarize_mcp_performance_history.py` 汇总多轮真实 p95 历史，再收紧 `scripts/check_mcp_performance_gate.py` 的 `THRESHOLDS`。
- 当前 fixture 对比覆盖 `initialize`、分页 `tools/list`、`resources/list`、`prompts/list`、`resources/templates/list`、非法 `tools/call` 与 `ping`，要求兼容 handler 响应 JSON 完全等价。raw cursor 已升级为不透明 payload，包含 collection、offset、filter fingerprint 与 schema version；客户端不能解析或跨过滤条件复用。官方 `ClientSession` 的 `list_*` 只支持标准 cursor 参数，不支持 Keepa 扩展的 `toolset/limit` 参数；因此 SDK adapter 以显式 `toolset=all limit=100` 从 raw registry 拉取完整工具全集，再默认压缩 tools/resources/resource templates/prompts 首页，分别以 `context_policy`、`keepa://context/policy`、`keepa://toolsets/{toolset}` 与 `product_research` 起手，避免一次性读取全部 schema。
- 2026-05-12 已在 `keepa_cli.agent.tools.validate_tool_arguments()` 前置统一 JSON Schema 校验，覆盖 `type`、`enum`、`minimum`、`oneOf`、`anyOf`、`additionalProperties` 和 array `items`。失败统一映射到 `tools/call` 的 `isError=true` / `invalid_arguments`，因此当前 raw stdio handler 与官方 SDK adapter 都共享同一校验结果。
- 负向覆盖已固定到 `tests/agent_eval_fixtures/mcp_schema_validation_negative.json` 与 `tests.test_mcp`，分别覆盖错误类型、非法 enum、越界 integer 和 array item 类型错误；`scripts/smoke_mcp_sdk_adapter_client.py` 也会通过官方 `ClientSession` 验证 SDK adapter 的 schema 错误映射。
- 本轮评估后暂不把 SDK adapter 提升为生产入口。官方 FastMCP 支持显式 `name=` 注册工具名，技术上可以表达当前无前缀 tool 名；但 toolset/profile/filter 分页 parity 和动态 resource templates 都依赖现有契约。为保证现有服务完全正常，本轮直接移除 `keepa.` 旧工具名前缀，不保留旧名 alias，也不向现有工具名叠加额外前缀；外部客户端迁移只文档化并使用当前无前缀新名。

## Streamable HTTP 边界

如果后续增加 Streamable HTTP，只允许新增协议 adapter：

- 保持 `AgentSession`、`run_command`、tool registry、resource registry、prompt registry、workflow resolver 与 budget ledger 不复制。
- HTTP adapter 只处理请求解码、session id、Origin/localhost 防护、请求级 timeout、响应编码、错误码映射和 SDK/ASGI 生命周期。
- 任何 HTTP 输出都必须先通过当前 Inspector fixture 或等价 fixture；不能为了适配 HTTP 改动无前缀 tool schema 或 service command 参数。
- `tests/agent_eval_fixtures/mcp_streamable_http_boundary_fixture.json` 已固定 Origin allowlist/reject、`MCP-Session-Id` 缺失/过期/DELETE、请求级 timeout 默认值/范围/超时映射、parse/invalid request、notification 202 与 application JSON-RPC error 的 HTTP status 映射；后续 HTTP adapter 必须先复用该 fixture 做红线回归。
- 本地桌面 Agent 和 CLI 文档默认仍推荐 stdio；HTTP 只作为远程或浏览器型 MCP client 的可选入口。

## 后续动作

- P1：如需人工复核 Inspector UI，再连接 `python -m keepa_cli.agent.mcp_sdk_adapter --stdio`，并把展示差异与 `scripts/export_mcp_inspector_snapshot.py` 的 typed 快照对照记录到 evidence。
- P1 已完成基础 fixture：`tests/mcp_fixtures/mcp_sdk_adapter_filter_parity.json` 已固定 `toolset/profile/allow_tools/exclude_tools/limit/cursor` 过滤与分页 parity；但 SDK adapter 仍未替换生产入口，后续提升前还要持续通过全量质量门禁和真实客户端验证。
- P1：把 SDK adapter 扩展到 Streamable HTTP 前，先让 `scripts/check_mcp_quality_gate.py --require-sdk` 与 HTTP boundary fixture 保持通过。
- P2：若差异可控，再评估 Streamable HTTP adapter；本地桌面和 Agent client 默认仍使用 stdio。

## 当前待完善清单

- P0 已完成：CI 新增 `mcp-sdk-adapter` job，安装 `.[mcp-sdk]` 后运行 SDK adapter 单测与 `scripts/check_mcp_quality_gate.py --require-sdk`。
- P0 已完成：SDK adapter 的 `list_tools` 保留 `toolset=all` 全集，但默认分页并优先展示 `context_policy`、docs index、workflow plan 和 agent profile；`list_resources`、`list_resource_templates` 与 `list_prompts` 也已压缩首页并通过 `nextCursor` 暴露全集，避免 Agent 起手上下文过大。
- P0 已完成：`scripts/check_mcp_performance_gate.py` 固化 initialize、`tools/list research`、`tools/list all limit=8`、`resources/list`、`prompts/list`、`context_policy` 与 fixture `products_get` 基准，默认连续 30 次取 p95，并记录 JSON bytes、text fallback bytes、structuredContent bytes 与 fixture cache hit p95；`toolset=all` 无 `limit` 必须返回 starter page + `nextCursor`。
- P1 已完成：重输出工具结果在保留 `mcp_resource_manifest` text fallback 的同时追加官方 `resource_link` content block；`outputSchema` 校验只进入 `scripts/check_mcp_output_schema.py` 与质量门禁，不放在热路径。
- P1 已完成：`scripts/check_mcp_sdk_adapter_typed_fixture.py` 已把 Inspector fixture step 映射为 SDK typed client 调用，记录 `toolset/limit` 这类 SDK typed API 不支持的扩展参数。
- P1 已完成：Streamable HTTP 前置 Origin/session/timeout/error fixture 已加入 `tests/agent_eval_fixtures/mcp_streamable_http_boundary_fixture.json`，并由 `keepa_cli.agent.mcp_http_contract` 与单测验证。
- P1 已完成：`reports_build` 与 `figures_research` 已通过 `x-keepa.long_running_candidate` 标出未来 Tasks/progress 边界；当前未声明 Tasks server capability，普通 `tools/call` 仅保留离线 fixture 或小输出路径，后续远程/HTTP 生产化必须先实现 progress、timeout、可恢复结果资源。
- P1 已完成：`scripts/export_mcp_inspector_snapshot.py --check` 固化无需 UI 的 typed Inspector 快照；人工 Inspector UI 差异只在出现客户端展示问题时补充到 evidence。
- P2：FastMCP decorator 只保留只读样例；若未来希望减少样板，应先验证无前缀 tool name、resource templates、annotations 和 direct `CallToolResult` 是否能完整表达。
- P2 已完成基础流程：`scripts/manual_live_product_read.py` 默认只做 dry-run；只有显式 `--yes-live` 且存在 `KEEPA_API_KEY` 才执行单 ASIN `products.get`，输出 token budget、`tokens.status` 前后摘要、SQLite cache provenance 与脱敏结果摘要。该脚本不进入默认 CI。
