# Keepa CLI 调研与实现方案

本仓库用于沉淀基于 Keepa API 的 CLI 程序设计、实现计划与后续代码。

当前已完成调研报告：

- [Keepa CLI 实现调研与落地报告](docs/reports/2026-05-09-keepa-cli-implementation-report.md)
- [Keepa CLI 功能完善与完整开发路线](docs/roadmaps/2026-05-09-keepa-cli-development-roadmap.md)

命令入口约定：

- `keepa-cli` 和 `kc` 都必须能完整调用 CLI 的所有能力。
- 默认执行任一入口都进入人类友好的交互界面。
- `--json`、`--stdio` 和显式子命令主要用于 agent 与脚本自动化，但两个入口都必须支持。

安全约定：

- 不提交 Keepa API key、`.env`、本地缓存或临时浏览器产物。
- 后续如需 GitHub Actions 调用真实 Keepa API，使用 GitHub Secrets 保存 `KEEPA_API_KEY`。
