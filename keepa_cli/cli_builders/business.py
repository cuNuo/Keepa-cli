"""
keepa_cli/cli_builders/business.py
文件说明：构造业务别名与 Agent profile CLI 子命令。
主要职责：把 argparse 参数映射到 business service 命令。
依赖边界：不承载业务计算，不直接访问 Keepa API。
"""

from __future__ import annotations

import argparse
from typing import Any

from keepa_cli.service import run_command


def add_business_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    business = subparsers.add_parser("business", help="Agent 业务别名与本地指标命令。")
    business_subparsers = business.add_subparsers(dest="business_command")

    for command, help_text in (
        ("find-fast-movers", "从本地产品输出中筛选高 velocity 商品。"),
        ("inventory-audit", "从本地产品输出中审计库存/缺货风险。"),
        ("market-opportunity", "从本地产品输出中形成市场机会 shortlist。"),
        ("seller-metrics", "输出 seller count 与竞争指标。"),
        ("velocity", "输出 monthlySold 与 velocity 指标。"),
        ("inventory", "输出库存风险指标。"),
    ):
        parser = business_subparsers.add_parser(command, help=help_text)
        _add_metrics_args(parser)

    profile = business_subparsers.add_parser("agent-profile", help="生成 Agent MCP 客户端配置片段和推荐 profile/toolset。")
    profile.add_argument("--server-name", default="keepa", help="MCP server 名称。")
    profile.add_argument("--profile", default="dry_run_default", help="推荐 MCP profile。")
    profile.add_argument("--toolset", default="research", help="推荐 MCP toolset。")
    profile.add_argument("--python-command", help="覆盖配置片段中的 Python 命令。")


def maybe_run_business_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str] | None:
    if args.command != "business":
        return None
    command_map = {
        "find-fast-movers": "business.find-fast-movers",
        "inventory-audit": "business.inventory-audit",
        "market-opportunity": "business.market-opportunity",
        "seller-metrics": "seller-metrics.summary",
        "velocity": "velocity.research",
        "inventory": "inventory.audit",
        "agent-profile": "agent.profile.generate",
    }
    service_command = command_map.get(str(args.business_command or ""))
    if not service_command:
        return None
    if service_command == "agent.profile.generate":
        payload = run_command(
            service_command,
            {
                "server_name": args.server_name,
                "profile": args.profile,
                "toolset": args.toolset,
                "python_command": args.python_command,
            },
        )
        return 0 if payload["ok"] else 1, payload
    payload = run_command(
        service_command,
        {
            "input": args.input,
            "fixture": args.fixture,
            "threshold_monthly_sold": args.threshold_monthly_sold,
            "target_days": args.target_days,
            "max_results": args.max_results,
        },
    )
    return 0 if payload["ok"] else 1, payload


def _add_metrics_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", help="Keepa CLI JSON 输出、fixture 或 Agent view 文件。")
    parser.add_argument("--fixture", help="tests/fixtures 下的离线 JSON 文件名。")
    parser.add_argument("--threshold-monthly-sold", type=int, default=500, help="fast mover 判定阈值。")
    parser.add_argument("--target-days", type=int, default=30, help="库存风险目标天数。")
    parser.add_argument("--max-results", type=int, help="最多返回的商品数量。")
