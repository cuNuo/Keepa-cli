# 安全说明

## Secret 处理

- 不提交 `KEEPA_API_KEY`、`.env`、本地缓存、cassette 原始录制或浏览器临时产物。
- 输出中的 `key`、`api_key`、`apikey`、`token`、`authorization` 必须脱敏。
- webhook URL query 中的 `token` 必须脱敏。

## 真实 API

- 默认 CI 不访问真实 Keepa API。
- live smoke 只能通过手动触发 workflow 运行，并依赖 GitHub Secret `KEEPA_API_KEY`。
- 录制后的 cassette 必须使用 `scripts/redact_cassette.py` 处理后才能入库。

## 报告问题

- 不要在 issue、PR 或日志中粘贴 Keepa API key。
- 如发现 secret 泄露，应立即撤销对应 key，并从 Git 历史中清理泄露内容。
