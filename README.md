# Keepa CLI 调研与实现方案

本仓库用于沉淀基于 Keepa API 的 CLI 程序设计、实现计划与后续代码。

当前已完成调研报告：

- [Keepa CLI 实现调研与落地报告](docs/reports/2026-05-09-keepa-cli-implementation-report.md)

安全约定：

- 不提交 Keepa API key、`.env`、本地缓存或临时浏览器产物。
- 后续如需 GitHub Actions 调用真实 Keepa API，使用 GitHub Secrets 保存 `KEEPA_API_KEY`。
