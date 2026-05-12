"""
keepa_cli/agent_profile.py
文件说明：生成 Agent MCP 客户端配置片段与推荐 profile/toolset。
主要职责：把 Keepa-cli MCP stdio 入口、profile 分层和业务场景建议结构化输出。
依赖边界：纯本地计算，不读取凭据，不访问网络。
"""

from __future__ import annotations

import sys
from typing import Any

from keepa_cli import __version__


PROFILE_SCHEMA_VERSION = "2026-05-11.1"


def build_agent_profile(
    *,
    server_name: str = "keepa",
    profile: str = "dry_run_default",
    toolset: str = "research",
    python_command: str | None = None,
) -> dict[str, Any]:
    command = python_command or sys.executable or "python"
    return {
        "view": "agent_mcp_profile",
        "schema_version": PROFILE_SCHEMA_VERSION,
        "keepa_cli_version": __version__,
        "server_name": server_name,
        "mcp_config_snippet": {
            "mcpServers": {
                server_name: {
                    "command": command,
                    "args": ["-m", "keepa_cli", "--mcp"],
                }
            }
        },
        "recommended_discovery": {
            "method": "tools/list",
            "params": {"toolset": toolset, "profile": profile},
            "resource_first": [
                "keepa://context/policy",
                "keepa://guides/categories",
                "keepa://guides/marketplaces",
                "keepa://guides/agent-profile",
            ],
        },
        "recommended_profiles": [
            {
                "scenario": "offline evidence, reports, metrics, and profile generation",
                "toolset": "business",
                "profile": "offline_fixture_only",
                "why": "只运行本地资源、报告、brief、业务指标和配置生成器。",
            },
            {
                "scenario": "category or product research with dry-run defaults",
                "toolset": "research",
                "profile": "dry_run_default",
                "why": "适合先做类目、Finder、deals 与 workflow.plan，不默认执行高成本 live 步骤。",
            },
            {
                "scenario": "approved live read research",
                "toolset": "research",
                "profile": "live_read_allowed",
                "why": "只在用户确认真实 Keepa 调用后切换。",
            },
            {
                "scenario": "tracking read audit",
                "toolset": "tracking-readonly",
                "profile": "tracking_readonly",
                "why": "只暴露 tracking 只读工具。",
            },
        ],
        "business_aliases": {
            "find_fast_movers": "business.find-fast-movers",
            "inventory_audit": "business.inventory-audit",
            "market_opportunity": "business.market-opportunity",
        },
        "notes": [
            "配置片段只声明 stdio server；具体 profile/toolset 应在 tools/list 或 tools/call 参数中显式传入。",
            "默认不要把 API key 写进配置片段；真实请求仍走本地环境变量或 keepa-cli config。",
        ],
    }
