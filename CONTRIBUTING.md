# 贡献指南

## 本地环境

- 使用 Python 3.11+。
- 必须使用项目 `.venv`，不要向基础环境安装依赖。
- 真实 Keepa API 不进入默认测试；默认使用 dry-run、fixture 或 fake opener。

## 常用命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\release_gate.py --skip-npm-install
git diff --check
```

## 新增命令要求

- 同时接入 service、CLI、stdio 和 capabilities。
- 增加 fixture 或 fake opener 测试，不依赖真实 Keepa API。
- 高成本或有副作用请求必须要求 `--yes` 或返回 `confirmation_required`。
- 输出必须使用稳定 JSON envelope，并对 secret 字段脱敏。

## 发布前检查

- 运行 `scripts/release_gate.py`。
- 确认 `npm pack --dry-run --json` 只包含发布所需文件。
- 若录制 live cassette，必须先运行 `scripts/redact_cassette.py` 脱敏。
