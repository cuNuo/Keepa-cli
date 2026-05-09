# Keepa-cli Hook 入口

## 用途

- 本目录提供项目级 Hook 快速入口，避免每次都记忆全局 Hook 路径。
- 当前项目仍复用全局 Hook 实现，项目脚本只负责转发。

## 常用命令

```powershell
.\.venv\Scripts\python.exe hooks\run_relevant_hooks.py --changed-only
```

等价于：

```powershell
.\.venv\Scripts\python.exe D:\.codex\hooks\run_relevant_hooks.py --changed-only
```

## 边界

- 默认不访问真实 Keepa API。
- Hook 失败时先修复格式、治理入口或测试问题，再继续提交。
