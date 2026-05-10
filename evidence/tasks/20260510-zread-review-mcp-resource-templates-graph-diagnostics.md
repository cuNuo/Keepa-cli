# zread 审查、MCP resource templates 与 graph diagnostics

## 任务目标

- 按用户要求调用 zread 相关 skill 尝试生成项目 wiki，并基于文档视角继续审查 Keepa-cli。
- 从 Agent/MCP 协议角度选择高价值、低副作用改进并落地。
- 完成本地验证、提交、推送，并跟踪 GitHub CI。

## 前置假设

- 本轮不访问真实 Keepa API，不消耗真实 Keepa token。
- 当前工作区已有 MCP、research graph、cassette promotion 与 Agent eval 相关未提交改动；本轮只在此基础上增量完善，不回退既有改动。
- zread 使用本机 `~/.zread/config.yaml` 中的 OpenAI 兼容端点，不在 evidence 中记录任何密钥。

## zread 调用记录

已读取 `D:\.codex\skills\zread-skill\SKILL.md` 与 `references/stdio-protocol.md`，确认应使用 `--stdio`。

执行：

```powershell
zread version --stdio
zread generate -y --stdio --draft clear --skip-failed
```

结果：

- `zread version` 返回 `0.2.12`。
- `zread generate` 未生成 `.zread/wiki/current`，也未留下 draft。
- `~/.zread/log/zread.log` 显示本地 LLM endpoint `http://127.0.0.1:55387/v1/chat/completions` 连接被拒绝。
- 已清理残留 zread 进程。

影响：本轮无法获得新的 zread wiki 页面，因此后续审查基于现有 README、Agent contract、architecture 文档、Serena memory 与代码检索完成。后续若需重新生成，需要先启动该本地 OpenAI 兼容端点或重新配置 zread LLM。

## 完成内容

1. MCP resource templates。
   - `keepa_cli/agent/resources.py` 新增 `list_mcp_resource_templates()`。
   - MCP 新增 `resources/templates/list`。
   - 模板覆盖 `keepa://schema/{name}`、`keepa://fixtures/{name}`、`keepa://chunk/{encoded_path}`、`keepa://output/{encoded_path}`。
   - `resources/read` 支持按 schema 名称和 fixture 文件名读取资源。

2. Research graph diagnostics。
   - `merge_research_graphs()` 为每个来源计算 `source_weight/confidence`。
   - 合并图新增 `diagnostics`，覆盖重复节点、孤立节点、label/type 冲突和 source weight 范围。
   - `graph_summary()` 透出 diagnostics 摘要，Agent 不需要加载完整 graph 就能先做审计。

3. Agent contract 与评测。
   - capabilities schema 升至 `2026-05-10.15`，并暴露 `resource_templates`。
   - 新增 MCP 单测覆盖 `resources/templates/list`、fixture template read、graph conflict diagnostics。
   - Agent eval 新增 `mcp_resource_templates_contract.json`，并扩展 `research_graph_merge` 断言 diagnostics/source weight。
   - 刷新 `tests/snapshots/agent_schema_snapshot.json` 与 `docs/schema/products.agent-view.schema.json`。

4. 文档。
   - README / README.zh-CN 增加 `resources/templates/list` 示例与 graph diagnostics 说明。
   - `docs/agent-contract.md` 增加 resource templates contract 与 merge diagnostics 字段说明。
   - `docs/architecture/mcp-agent-tools.md` 更新已完成项和后续方向。

## 风险与边界

- zread wiki 未成功生成，原因是本地 LLM 兼容端点未启动；该失败不影响 Keepa-cli 本地测试。
- `resources/templates/list` 目前提供静态 URI 形状；按 `cache_key`、ASIN、graph root 查询仍是后续项。
- Graph diagnostics 已覆盖重复、孤立和 label/type 冲突；尚未输出完整 graph diff 或 source preference 决策。

## GitHub CI 反馈与修复

首次推送 commit `c2fce3e` 后，GitHub Actions run `25625966938` 在所有平台的 unit tests 阶段失败。失败根因是干净 CI 环境未安装可选依赖 `prompt_toolkit`，而 `keepa_cli/ui/modern_tui.py` 的 prompt loop 在测试路径中直接导入该依赖。

已追加 commit `6b76ae6`：

- `_run_prompt_loop()` 在缺少 `prompt_toolkit` 且没有注入 session 时回退到 classic TUI。
- 测试注入 `FakePromptSession` 时提供轻量 `HTML()` / `clear()` fallback，保证无可选依赖也能覆盖 slash command loop。
- 新增单测模拟 `prompt_toolkit` 缺失，避免本地环境依赖掩盖 CI 问题。

最终 GitHub Actions run `25626082285` 已通过：

- Ubuntu Python 3.11 / 3.12：通过。
- macOS Python 3.11 / 3.12：通过。
- Windows Python 3.11 / 3.12：通过。

GitHub 仅返回 runner 层提示：`actions/checkout@v4` 与 `actions/setup-python@v5` 仍运行在 Node.js 20 action runtime，GitHub 将在 2026-06-02 默认切到 Node.js 24。该提示不影响本轮 CI 结论，但后续可增加 workflow 兼容性跟踪项。

## 后续最适合方向

1. 启动或重新配置 zread LLM endpoint 后重新生成 wiki，并把 wiki 结论转为 docs/evidence backlog。
2. 增加 reports 与 tracking-readonly Agent eval，覆盖本地文件输出、只读 tracking 参数和 session ledger。
3. 增加 `research_graph.diff` 或 merge 的 `--prefer-source`，让 Agent 在冲突来源中做可解释选择。
4. 增加 cache-key/ASIN/evidence logical path resource template，进一步减少客户端手写 URI。
