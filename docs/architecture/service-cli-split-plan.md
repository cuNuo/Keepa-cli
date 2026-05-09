# service.py / cli.py 拆分计划

## 当前状态

- `keepa_cli/service.py` 承载 command service、官方 API handler、历史导出、tracking、graphimage 等逻辑。
- `keepa_cli/cli.py` 承载 argparse 构造与 CLI 到 service 参数转换。
- 当前测试覆盖较完整，继续扩展命令族时单文件体积会增加理解和回归成本。

## 拆分触发条件

- 单个文件超过 1,000 行，或新增一个 API family 需要超过 3 个 handler。
- 同一命令族新增独立 fixture、预算规则、文件输出和 TUI 映射。
- 修改一个命令族时需要频繁回读无关命令族逻辑。

## 目标结构

```text
keepa_cli/
  commands/
    products.py
    categories.py
    history.py
    high_value.py
    tracking.py
    graphs.py
  cli_builders/
    products.py
    categories.py
    history.py
    high_value.py
    tracking.py
    graphs.py
```

## 迁移顺序

1. 先为目标命令族补或确认 service、CLI、stdio、capabilities 和 snapshot 测试。
2. 把纯 helper 与 handler 按命令族移动到 `keepa_cli/commands/`。
3. 保持 `run_command` 作为唯一公共调度入口，避免调用方改动。
4. 把 argparse 子命令构造移动到 `keepa_cli/cli_builders/`，`cli.py` 只保留全局参数、分发和输出。
5. 每迁移一个命令族运行完整 `unittest` 和 `scripts/release_gate.py`。

## 不做的事

- 不在功能开发中同时重命名公开 command id。
- 不改变 `keepa-cli` 与 `kc` 的等价入口。
- 不把真实 Keepa API 调用放进默认 CI。
