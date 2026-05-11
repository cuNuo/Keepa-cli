# MCP Python SDK adapter 对照

## 结论

Keepa-cli 当前应继续保留手写 JSON-RPC stdio transport 作为生产入口，同时把官方 Python MCP SDK adapter 作为受控 spike。原因是现有实现已经围绕 `run_command`、`AgentSession`、toolset/profile gating、MCP resources/templates、prompts、chunk/output resources 和 budget ledger 形成稳定契约；直接切换 FastMCP 会带来依赖、协议形状和 session cache 迁移风险。

## 对照范围

- 当前生产入口：`keepa_cli/agent/mcp.py`，通过 `python -m keepa_cli --mcp` 或 `kc --mcp` 暴露 stdio JSON-RPC。
- 当前业务入口：`keepa_cli/service.py::run_command`，CLI、stdio 与 MCP 都复用它。
- 官方 SDK 参考：Model Context Protocol Python SDK 的 FastMCP server、tool/resource/prompt decorator、stdio 运行方式和 Inspector 调试链路。
- 本轮不新增 `mcp` 运行时依赖，不改包安装依赖，不改变已发布 MCP tool 名。

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
- `tools/call` 能返回 `structuredContent`、compact text fallback、`isError`，并保留 `invalid_arguments` / `inactive_tool` 等工具错误语义。
- `resources/templates/list` 能暴露当前 dynamic URI templates，`resources/read` 能处理 session cache 与 encoded local output path。
- Inspector smoke fixture、`tests.test_mcp`、Agent eval fixtures、`npm pack --dry-run --json` 全部通过。
- 不破坏 `kc --mcp` 与现有 MCP client examples。

## 失败回退

如果 SDK adapter 无法稳定表达动态 toolset/profile/pagination/resource templates，保持当前手写 stdio transport。该方案不是技术债本身：它已经足够薄，只负责 MCP JSON-RPC 协议边界，业务逻辑仍在统一 service/session 层。

## 2026-05-12 隔离 spike 状态

- 已新增 `keepa_cli/agent/mcp_sdk_adapter.py`，作为官方 Python MCP SDK adapter 的隔离边界；生产入口仍是 `python -m keepa_cli --mcp`。
- `adapter_status()` 会报告 `sdk_available`、`server_info_name=keepa_mcp`、生产入口未替换、业务核心仍为 `AgentSession -> run_command`。
- `create_fastmcp_readonly_spike()` 只在安装可选依赖 `keepa-cli[mcp-sdk]` 后创建 FastMCP 只读样例，证明 SDK 层可复用 session/service；它不是生产 server，不承诺 `keepa.*` tool 名或完整分页/resource templates 等价。
- `scripts/compare_mcp_sdk_adapter_fixture.py` 使用 `tests/agent_eval_fixtures/mcp_inspector_protocol_fixture.json` 对比当前 `--mcp` handler 与隔离 adapter 输出；release gate 已纳入该检查。
- 当前 fixture 对比覆盖 `initialize`、分页 `tools/list`、`resources/list`、`prompts/list`、`resources/templates/list`、非法 `tools/call` 与 `ping`，要求响应 JSON 完全等价。

## Streamable HTTP 边界

如果后续增加 Streamable HTTP，只允许新增协议 adapter：

- 保持 `AgentSession`、`run_command`、tool registry、resource registry、prompt registry、workflow resolver 与 budget ledger 不复制。
- HTTP adapter 只处理请求解码、session id、Origin/localhost 防护、响应编码、错误码映射和 SDK/ASGI 生命周期。
- 任何 HTTP 输出都必须先通过当前 Inspector fixture 或等价 fixture；不能为了适配 HTTP 改动 `keepa.*` tool schema 或 service command 参数。
- 本地桌面 Agent 和 CLI 文档默认仍推荐 stdio；HTTP 只作为远程或浏览器型 MCP client 的可选入口。

## 后续动作

- P1：用真实 SDK/Inspector 手工连接 `create_fastmcp_readonly_spike()`，记录 FastMCP 默认 tool 命名、structured output 和资源/提示词能力差异。
- P1：把 SDK adapter 从只读样例扩展到完整 protocol adapter 前，先让 `scripts/compare_mcp_sdk_adapter_fixture.py` 对新增 fixture 保持通过。
- P2：若差异可控，再评估 Streamable HTTP adapter；本地桌面和 Agent client 默认仍使用 stdio。
