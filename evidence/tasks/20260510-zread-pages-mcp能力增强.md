# zread Pages 与 MCP 能力增强

## 任务目标

- 将 GitHub Pages 与 zread 公开页做成 README 中更稳定的文档入口。
- 暴露 `keepa://zread/wiki/current` 等 MCP resources，让 Agent 可以直接读取仓库内 zread wiki。
- 继续增强 MCP 能力，减少 Agent 依赖全量 `tools/list` 或手工拼 URI。

## 背景与输入

- 用户要求 zread 不应被忽略，公开仓库应有稳定文档入口，并希望 MCP 功能继续完善。
- 仓库已有 `.zread/wiki/versions/2026-05-10-215740` 快照，语言为 `zh`，页面数为 32。
- 本轮没有发起真实 Keepa API 请求，也没有读取或输出真实 token。

## 处理过程

- 新增 GitHub Pages 静态入口 `docs/index.html`，集中链接 zread public wiki、README、Agent contract、schema、zread 快照与 MCP 架构文档。
- 新增 `.github/workflows/pages.yml`，发布 `docs/` 到 GitHub Pages，并使用 Node 24 兼容的 Pages action 版本。
- README / README.zh-CN 增加 Pages badge、zread public wiki、zread 本地 browse 命令与 Agent 可读的 zread MCP resources。
- 新增 `keepa_cli/agent/prompts.py`，支持 `prompts/list` 和 `prompts/get`，提供 product research、category research、deal compare、project onboarding 起手式。
- 扩展 `keepa_cli/agent/resources.py`：
  - 静态资源：`keepa://zread/wiki/current`、`keepa://zread/wiki/toc`、`keepa://zread/wiki/pages`。
  - zread 页面模板：`keepa://zread/wiki/page/{slug_or_file}`。
  - schema-first 发现资源：`keepa://tools/index`、`keepa://prompts/index`。
  - tool/prompt 模板：`keepa://toolsets/{toolset}`、`keepa://tools/{name}`、`keepa://prompts/{name}`。
- 新增 `keepa_cli/commands/docs.py`，提供 `docs.index` / `docs.read`，给不支持 MCP `resources/read` 的客户端使用。
- 扩展 `keepa_cli/agent/tools.py` 的 `docs` toolset，新增 `keepa.docs_index` 与 `keepa.docs_read`。
- 更新 `capabilities`、`docs/agent-contract.md`、`docs/architecture/mcp-agent-tools.md` 与测试。

## 验证结果

- `.\.venv\Scripts\python.exe -m unittest tests.test_mcp tests.test_capabilities tests.test_service_commands -v`：42 tests OK。
- MCP smoke：
  - `resources/read keepa://tools/index` 返回 toolset 与 tool schema 索引。
  - `resources/read keepa://toolsets/research` 返回 research toolset manifest。
  - `resources/read keepa://tools/keepa.products_get` 返回单 tool input/output schema。
  - `resources/read keepa://zread/wiki/current` 返回当前 zread 版本、Pages URL 与 public zread URL。
- 待完整收口验证：全量 unittest、Agent eval、fixture sync、release gate、Hook、doctor、Node wrapper 与 GitHub Actions。

## 关联产物

- `.github/workflows/pages.yml`
- `docs/index.html`
- `keepa_cli/agent/prompts.py`
- `keepa_cli/commands/docs.py`
- `keepa_cli/agent/resources.py`
- `keepa_cli/agent/tools.py`
- `keepa_cli/capabilities.py`
- `tests/test_mcp.py`
- `tests/test_capabilities.py`
- `tests/test_service_commands.py`

## 风险与后续

- GitHub Pages 首次发布依赖仓库 Pages 设置和 Actions 权限；本轮会在推送后观察 Pages workflow。
- `keepa://prompts/{name}` 对带必填参数的 prompt 只返回定义，不直接渲染；客户端仍应使用 `prompts/get` 传参。
- 后续最值得增强：将 reports builder 直接消费 merged research graph，补 graph-root resource template，并继续扩展 tracking-readonly eval。

## 结论

本轮把 zread 作为一等文档资产接入 README、Pages 与 MCP resources，同时补充 schema-first MCP discovery，让 Agent 可以按需读取文档、toolset、单 tool schema 与 prompt，而不需要拉取全量工具列表。
