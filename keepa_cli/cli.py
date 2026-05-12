"""
keepa_cli/cli.py
文件说明：提供 keepa-cli 与 kc 共用的命令行入口。
主要职责：解析参数、输出 JSON envelope，并把业务调用委托给 Agent-safe service。
依赖边界：仅依赖包内稳定模块和 Python 标准库，不直接保存凭据。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from keepa_cli import __version__
from keepa_cli.agent.mcp import iter_mcp_stream
from keepa_cli.agent.mcp_http import DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT, serve_mcp_http
from keepa_cli.agent.stdio import iter_stdio_output
from keepa_cli.cli_builders.business import add_business_parser, maybe_run_business_command
from keepa_cli.cli_builders.cache import add_cache_parser, maybe_run_cache_command
from keepa_cli.cli_builders.categories import add_categories_parser, maybe_run_categories_command
from keepa_cli.cli_builders.common import add_live_cache_options, live_cache_params
from keepa_cli.cli_builders.deals import add_deals_parser, maybe_run_deals_command
from keepa_cli.cli_builders.finder import add_finder_parser, maybe_run_finder_command
from keepa_cli.cli_builders.history import add_history_parser, maybe_run_history_command
from keepa_cli.cli_builders.products import add_products_parser, maybe_run_products_command
from keepa_cli.cli_builders.raw import add_raw_request_parser, maybe_run_raw_request_command
from keepa_cli.cli_builders.research_graph import add_research_graph_parser, maybe_run_research_graph_command
from keepa_cli.cli_builders.tracking import add_tracking_parser, maybe_run_tracking_command
from keepa_cli.cli_builders.workflows import add_workflow_parsers, maybe_run_workflow_command
from keepa_cli.envelope import error_envelope, success_envelope
from keepa_cli.service import run_command
from keepa_cli.ui.modern_tui import build_tui_metadata, run_modern_tui
from keepa_cli.ui.tui import run_interactive_tui


def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keepa-cli",
        description="Agent-first Keepa API CLI. kc is an equivalent short entry point.",
    )
    parser.add_argument("--version", action="version", version=f"keepa-cli {__version__}")
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON envelope，供 Agent 调用。")
    parser.add_argument("--stdio", action="store_true", help="启用 JSON Lines 长会话协议。")
    parser.add_argument("--mcp", action="store_true", help="启用 MCP JSON-RPC stdio server。")
    parser.add_argument("--mcp-http", action="store_true", help="启用 MCP Streamable HTTP server。")
    parser.add_argument("--mcp-http-host", default=DEFAULT_HTTP_HOST, help="MCP HTTP 监听地址，默认 127.0.0.1。")
    parser.add_argument("--mcp-http-port", type=int, default=DEFAULT_HTTP_PORT, help="MCP HTTP 监听端口，默认 8765。")
    parser.add_argument(
        "--mcp-http-origin",
        action="append",
        default=[],
        help="允许的浏览器 Origin，可重复；默认允许本机 MCP Inspector 常用 Origin。",
    )
    parser.add_argument("--yes", action="store_true", help="确认执行可能消耗较高 token 的请求。")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="检查认证、fixture/offline 与双入口配置。")
    subparsers.add_parser("capabilities", help="输出 Agent 能力发现协议。")
    tui = subparsers.add_parser("tui", help="启动人类 TUI；默认优先 prompt_toolkit，缺失时回退标准库界面。")
    tui.add_argument("--classic", action="store_true", help="强制使用标准库 TUI。")

    config = subparsers.add_parser("config", help="查看或初始化本地配置。")
    config_subparsers = config.add_subparsers(dest="config_command")
    config_show = config_subparsers.add_parser("show", help="显示当前有效配置。")
    config_show.add_argument("--path", help="指定配置文件路径。")
    config_init = config_subparsers.add_parser("init", help="生成默认配置文件。")
    config_init.add_argument("--path", help="指定配置文件路径。")
    config_init.add_argument("--dry-run", action="store_true", help="只输出将写入的配置，不落盘。")
    config_token = config_subparsers.add_parser("set-token", help="写入本地 Keepa API token。")
    config_token.add_argument("token", help="Keepa API token；输出会自动打码。")
    config_token.add_argument("--path", help="指定配置文件路径。")
    config_token.add_argument("--dry-run", action="store_true", help="只输出打码后的写入结果，不落盘。")
    config_language = config_subparsers.add_parser("set-language", help="设置界面语言。")
    config_language.add_argument("language", choices=("en", "zh"), help="默认英文；可设置 zh 使用中文 TUI。")
    config_language.add_argument("--path", help="指定配置文件路径。")
    config_language.add_argument("--dry-run", action="store_true", help="只输出将写入的语言配置，不落盘。")
    config_budget = config_subparsers.add_parser("set-max-tokens", help="设置单次请求 token 预算上限提示。")
    config_budget.add_argument("max_tokens", help="正整数；高订阅可设置更宽。")
    config_budget.add_argument("--path", help="指定配置文件路径。")
    config_budget.add_argument("--dry-run", action="store_true", help="只输出将写入的预算配置，不落盘。")

    domains = subparsers.add_parser("domains", help="Keepa domain 发现命令。")
    domains_subparsers = domains.add_subparsers(dest="domains_command")
    domains_subparsers.add_parser("list", help="列出 Keepa 支持的 Amazon domain。")

    docs = subparsers.add_parser("docs", help="读取本地 Agent 文档和 MCP resource。")
    docs_subparsers = docs.add_subparsers(dest="docs_command")
    docs_subparsers.add_parser("index", help="列出 zread、schema、evidence 与 MCP resources。")
    docs_read = docs_subparsers.add_parser("read", help="读取本地 MCP resource 或 zread 页面。")
    docs_read.add_argument("--uri", help="MCP resource URI，例如 keepa://context/policy。")
    docs_read.add_argument("--page", help="zread 页面 slug 或 markdown 文件名。")

    research = subparsers.add_parser("research", help="调研 Agent 本地上下文命令。")
    research_subparsers = research.add_subparsers(dest="research_command")
    research_subparsers.add_parser("policy", help="输出 offline-first Agent policy 与 roots。")
    target = research_subparsers.add_parser("resolve-target", help="本地解析 ASIN、类目、seller、fixture、evidence 或关键词目标。")
    target.add_argument("query", help="调研输入，例如 ASIN、类目词、seller id、fixture 名或 evidence 关键词。")
    target.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    target.add_argument("--hint-type", choices=("asin", "code", "seller", "category", "keyword", "fixture", "evidence"), help="可选目标类型提示。")
    context = research_subparsers.add_parser("context", help="按目标或问题列出本地上下文资源。")
    context.add_argument("--query", help="未解析的调研输入或问题。")
    context.add_argument("--question", help="需要从本地资源回答的问题。")
    context.add_argument("--target-type", choices=("asin", "code", "seller", "category", "keyword", "fixture", "evidence"), help="已解析目标类型。")
    context.add_argument("--target-id", help="已解析目标 id。")
    brief = research_subparsers.add_parser("brief", help="从本地 JSON payload 或 research_graph 导出调研 brief。")
    brief.add_argument("input", nargs="+", help="一个或多个 Keepa CLI JSON 输出文件。")
    brief.add_argument("--title", default="Keepa research brief", help="brief 标题。")
    brief.add_argument("--id", help="稳定 brief id；默认使用 graph root 或标题 slug。")
    brief.add_argument("--out", help="把 brief 写入 JSON 文件。")

    add_cache_parser(subparsers)
    add_business_parser(subparsers)
    add_workflow_parsers(subparsers)
    add_products_parser(subparsers)
    add_categories_parser(subparsers)
    add_history_parser(subparsers)
    add_finder_parser(subparsers)
    add_deals_parser(subparsers)

    sellers = subparsers.add_parser("sellers", help="卖家查询命令。")
    sellers_subparsers = sellers.add_subparsers(dest="sellers_command")
    sellers_get = sellers_subparsers.add_parser("get", help="按 seller id 查询卖家。")
    sellers_get.add_argument("seller", nargs="+", help="一个或多个 seller id。")
    sellers_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    sellers_get.add_argument("--storefront", action="store_true", help="请求卖家 storefront ASIN 列表。")
    sellers_get.add_argument("--update", help="刷新阈值小时。")
    sellers_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    sellers_get.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    sellers_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(sellers_get)

    bestsellers = subparsers.add_parser("bestsellers", help="Best Sellers 榜单命令。")
    bestsellers_subparsers = bestsellers.add_subparsers(dest="bestsellers_command")
    bestsellers_get = bestsellers_subparsers.add_parser("get", help="按 category id 查询 Best Sellers。")
    bestsellers_get.add_argument("category", help="Keepa category id。")
    bestsellers_get.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    bestsellers_get.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    bestsellers_get.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    bestsellers_get.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(bestsellers_get)

    topsellers = subparsers.add_parser("topsellers", help="Top Sellers 榜单命令。")
    topsellers_subparsers = topsellers.add_subparsers(dest="topsellers_command")
    topsellers_list = topsellers_subparsers.add_parser("list", help="查询 Most Rated Sellers 列表。")
    topsellers_list.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    topsellers_list.add_argument("--category", help="可选 Keepa category id。")
    topsellers_list.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    topsellers_list.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    topsellers_list.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(topsellers_list)

    tokens = subparsers.add_parser("tokens", help="Token bucket 状态命令。")
    tokens_subparsers = tokens.add_subparsers(dest="tokens_command")
    tokens_status = tokens_subparsers.add_parser("status", help="查询当前 Keepa token bucket 状态。")
    tokens_status.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    tokens_status.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(tokens_status)

    graphs = subparsers.add_parser("graphs", help="Keepa 图像链路命令。")
    graphs_subparsers = graphs.add_subparsers(dest="graphs_command")
    graphs_image = graphs_subparsers.add_parser("image", help="构建 Graph Image API 请求规格。")
    graphs_image.add_argument("asin", help="一个 ASIN。")
    graphs_image.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    graphs_image.add_argument("--width", type=int, help="图像宽度。")
    graphs_image.add_argument("--height", type=int, help="图像高度。")
    graphs_image.add_argument("--range", type=int, help="历史天数范围。")
    graphs_image.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    graphs_image.add_argument("--out", help="写入 PNG 文件路径；真实 graphimage 请求必须提供。")
    graphs_image.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    graphs_image.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="添加 Graph Image API 参数，可重复，例如 amazon=1。",
    )

    lightningdeals = subparsers.add_parser("lightningdeals", help="Lightning Deals 查询命令。")
    lightningdeals_subparsers = lightningdeals.add_subparsers(dest="lightningdeals_command")
    lightningdeals_list = lightningdeals_subparsers.add_parser("list", help="查询当前或指定 ASIN 的 Lightning Deals。")
    lightningdeals_list.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    lightningdeals_list.add_argument("--asin", help="可选 ASIN；不提供则请求完整列表。")
    lightningdeals_list.add_argument("--fixture", help="使用 tests/fixtures 下的离线响应文件。")
    lightningdeals_list.add_argument("--out", help="把大响应 body 写入 JSON 文件。")
    lightningdeals_list.add_argument("--dry-run", action="store_true", help="只输出请求规格，不访问 API。")
    add_live_cache_options(lightningdeals_list)

    add_tracking_parser(subparsers)

    schema = subparsers.add_parser("schema", help="Agent schema 文档命令。")
    schema_subparsers = schema.add_subparsers(dest="schema_command")
    schema_generate = schema_subparsers.add_parser("generate", help="从 snapshot 生成产品 Agent 视图 schema 文档。")
    schema_generate.add_argument("--snapshot", default="tests/snapshots/agent_schema_snapshot.json", help="输入 snapshot 路径。")
    schema_generate.add_argument("--out", default="docs/schema/products.agent-view.schema.json", help="输出 schema 文档路径。")

    cassettes = subparsers.add_parser("cassettes", help="Keepa cassette 本地处理命令。")
    cassettes_subparsers = cassettes.add_subparsers(dest="cassettes_command")
    cassettes_sanitize = cassettes_subparsers.add_parser("sanitize", help="脱敏真实 Keepa cassette JSON。")
    cassettes_sanitize.add_argument("input", help="输入 cassette JSON 文件。")
    cassettes_sanitize.add_argument("--out", required=True, help="输出脱敏 JSON 文件。")
    cassettes_promote = cassettes_subparsers.add_parser("promote", help="脱敏并提升 cassette 为双份 fixture。")
    cassettes_promote.add_argument("input", help="输入真实或已脱敏 cassette JSON 文件。")
    cassettes_promote.add_argument("--name", required=True, help="fixture 文件名，不含路径；可省略 .json。")
    cassettes_promote.add_argument("--tests-dir", default="tests/fixtures", help="测试 fixture 目录。")
    cassettes_promote.add_argument("--package-dir", default="keepa_cli/fixtures", help="包内 fixture 目录。")
    cassettes_promote.add_argument("--manifest", default="evidence/manifest.csv", help="evidence manifest 路径。")
    cassettes_promote.add_argument("--title", help="manifest 标题。")
    cassettes_promote.add_argument("--no-manifest", action="store_true", help="不更新 evidence manifest。")
    cassettes_promote.add_argument("--dry-run", action="store_true", help="只返回计划，不写文件。")
    cassettes_promote_verify = cassettes_subparsers.add_parser("promote-and-verify", help="提升 cassette 并验证 fixture/eval 一致性。")
    cassettes_promote_verify.add_argument("input", help="输入真实或已脱敏 cassette JSON 文件。")
    cassettes_promote_verify.add_argument("--name", required=True, help="fixture 文件名，不含路径；可省略 .json。")
    cassettes_promote_verify.add_argument("--tests-dir", default="tests/fixtures", help="测试 fixture 目录。")
    cassettes_promote_verify.add_argument("--package-dir", default="keepa_cli/fixtures", help="包内 fixture 目录。")
    cassettes_promote_verify.add_argument("--eval-dir", default="tests/agent_eval_fixtures", help="Agent eval 规格目录。")
    cassettes_promote_verify.add_argument("--manifest", default="evidence/manifest.csv", help="evidence manifest 路径。")
    cassettes_promote_verify.add_argument("--title", help="manifest 标题。")
    cassettes_promote_verify.add_argument("--no-manifest", action="store_true", help="不更新 evidence manifest。")
    cassettes_promote_verify.add_argument("--run-eval", action="store_true", help="提升后运行 Agent eval fixtures。")
    cassettes_promote_verify.add_argument("--dry-run", action="store_true", help="只返回计划，不写文件或验证。")

    add_research_graph_parser(subparsers)
    add_raw_request_parser(subparsers)

    return parser


def _parse_params(raw_params: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for raw in raw_params:
        key, separator, value = raw.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid --param, expected KEY=VALUE: {raw}")
        params[key.strip()] = value
    return params


def _run_command(args: argparse.Namespace) -> tuple[int, dict[str, Any] | str]:
    if args.command == "doctor":
        payload = run_command("doctor")
        return 0 if payload["ok"] else 1, payload

    if args.command == "capabilities":
        payload = run_command("capabilities")
        return 0 if payload["ok"] else 1, payload

    if args.command == "tui":
        selected_runtime = "classic" if getattr(args, "classic", False) else None
        return 0, success_envelope(
            command="tui",
            data=build_tui_metadata(selected_runtime=selected_runtime),
            request={"transport": "cli"},
            token_bucket={},
        )

    if args.command == "domains" and args.domains_command == "list":
        payload = run_command("domains.list")
        return 0 if payload["ok"] else 1, payload

    if args.command == "docs" and args.docs_command == "index":
        payload = run_command("docs.index")
        return 0 if payload["ok"] else 1, payload

    if args.command == "docs" and args.docs_command == "read":
        payload = run_command("docs.read", {"uri": args.uri, "page": args.page})
        return 0 if payload["ok"] else 1, payload

    if args.command == "research" and args.research_command == "policy":
        payload = run_command("context.policy")
        return 0 if payload["ok"] else 1, payload

    if args.command == "research" and args.research_command == "resolve-target":
        payload = run_command(
            "research.target.resolve",
            {"query": args.query, "domain": args.domain, "hint_type": args.hint_type},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "research" and args.research_command == "context":
        payload = run_command(
            "research.context.query",
            {
                "query": args.query,
                "question": args.question,
                "target_type": args.target_type,
                "target_id": args.target_id,
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "research" and args.research_command == "brief":
        payload = run_command(
            "research_brief.export",
            {"input": list(args.input), "title": args.title, "id": args.id, "out": args.out},
        )
        return 0 if payload["ok"] else 1, payload

    cache_result = maybe_run_cache_command(args)
    if cache_result is not None:
        return cache_result

    business_result = maybe_run_business_command(args)
    if business_result is not None:
        return business_result

    workflow_result = maybe_run_workflow_command(args, parse_params=_parse_params)
    if workflow_result is not None:
        return workflow_result

    products_result = maybe_run_products_command(args)
    if products_result is not None:
        return products_result

    categories_result = maybe_run_categories_command(args)
    if categories_result is not None:
        return categories_result

    history_result = maybe_run_history_command(args)
    if history_result is not None:
        return history_result

    finder_result = maybe_run_finder_command(args)
    if finder_result is not None:
        return finder_result

    deals_result = maybe_run_deals_command(args)
    if deals_result is not None:
        return deals_result

    tracking_result = maybe_run_tracking_command(args)
    if tracking_result is not None:
        return tracking_result

    if args.command == "config" and args.config_command == "show":
        payload = run_command("config.show", {"path": args.path})
        return 0 if payload["ok"] else 1, payload

    if args.command == "config" and args.config_command == "init":
        payload = run_command("config.init", {"path": args.path, "dry_run": bool(args.dry_run)})
        return 0 if payload["ok"] else 1, payload

    if args.command == "config" and args.config_command == "set-token":
        payload = run_command(
            "config.set-token",
            {"path": args.path, "token": args.token, "dry_run": bool(args.dry_run)},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "config" and args.config_command == "set-language":
        payload = run_command(
            "config.set-language",
            {"path": args.path, "language": args.language, "dry_run": bool(args.dry_run)},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "config" and args.config_command == "set-max-tokens":
        payload = run_command(
            "config.set-max-tokens",
            {"path": args.path, "max_tokens": args.max_tokens, "dry_run": bool(args.dry_run)},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "sellers" and args.sellers_command == "get":
        payload = run_command(
            "sellers.get",
            {
                "seller": args.seller,
                "domain": args.domain,
                "storefront": bool(args.storefront),
                "update": args.update,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "bestsellers" and args.bestsellers_command == "get":
        payload = run_command(
            "bestsellers.get",
            {
                "category": args.category,
                "domain": args.domain,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "topsellers" and args.topsellers_command == "list":
        payload = run_command(
            "topsellers.list",
            {
                "domain": args.domain,
                "category": args.category,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                "yes": bool(args.yes),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "tokens" and args.tokens_command == "status":
        payload = run_command(
            "tokens.status",
            {
                "fixture": args.fixture,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "graphs" and args.graphs_command == "image":
        try:
            extra_params = _parse_params(args.param)
        except ValueError as exc:
            return 2, error_envelope(command="graphs.image", kind="invalid_argument", message=str(exc))
        payload = run_command(
            "graphs.image",
            {
                "asin": args.asin,
                "domain": args.domain,
                "width": args.width,
                "height": args.height,
                "range": args.range,
                "extra_params": extra_params,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "lightningdeals" and args.lightningdeals_command == "list":
        payload = run_command(
            "lightningdeals.list",
            {
                "domain": args.domain,
                "asin": args.asin,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
                **live_cache_params(args),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "schema" and args.schema_command == "generate":
        payload = run_command(
            "schema.generate",
            {"snapshot": args.snapshot, "out": args.out},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "cassettes" and args.cassettes_command == "sanitize":
        payload = run_command(
            "cassettes.sanitize",
            {"input": args.input, "out": args.out},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "cassettes" and args.cassettes_command == "promote":
        payload = run_command(
            "cassettes.promote",
            {
                "input": args.input,
                "name": args.name,
                "tests_dir": args.tests_dir,
                "package_dir": args.package_dir,
                "manifest": args.manifest,
                "title": args.title,
                "no_manifest": bool(args.no_manifest),
                "dry_run": bool(args.dry_run),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "cassettes" and args.cassettes_command == "promote-and-verify":
        payload = run_command(
            "cassettes.promote_and_verify",
            {
                "input": args.input,
                "name": args.name,
                "tests_dir": args.tests_dir,
                "package_dir": args.package_dir,
                "eval_dir": args.eval_dir,
                "manifest": args.manifest,
                "title": args.title,
                "no_manifest": bool(args.no_manifest),
                "run_eval": bool(args.run_eval),
                "dry_run": bool(args.dry_run),
            },
        )
        return 0 if payload["ok"] else 1, payload

    research_graph_result = maybe_run_research_graph_command(args)
    if research_graph_result is not None:
        return research_graph_result

    raw_request_result = maybe_run_raw_request_command(args, parse_params=_parse_params)
    if raw_request_result is not None:
        return raw_request_result

    return 2, error_envelope(
        command=args.command or "cli",
        kind="unsupported_command",
        message="unsupported or incomplete command",
    )


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.stdio:
        input_text = sys.stdin.read()
        for line in iter_stdio_output(input_text, env=os.environ):
            sys.stdout.write(line + "\n")
        return 0

    if args.mcp:
        for line in iter_mcp_stream(sys.stdin, env=os.environ):
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        return 0

    if args.mcp_http:
        allowed_origins = tuple(args.mcp_http_origin) if args.mcp_http_origin else None
        return serve_mcp_http(
            host=args.mcp_http_host,
            port=args.mcp_http_port,
            allowed_origins=allowed_origins,
            env=os.environ,
        )

    if args.command is None:
        if args.json:
            _write_json(
                error_envelope(
                    command="cli",
                    kind="missing_command",
                    message="a command is required in --json mode",
                )
            )
            return 2
        if not sys.stdin.isatty():
            return run_interactive_tui(env=os.environ)
        return run_modern_tui(env=os.environ)

    if args.command == "tui" and not args.json:
        if getattr(args, "classic", False):
            return run_interactive_tui(env=os.environ)
        return run_modern_tui(env=os.environ)

    exit_code, payload = _run_command(args)
    if args.json:
        if isinstance(payload, str):
            payload = success_envelope(command=args.command, data={"message": payload})
        _write_json(payload)
        return exit_code

    if isinstance(payload, str):
        sys.stdout.write(payload + "\n")
    elif payload.get("ok"):
        sys.stdout.write(json.dumps(payload["data"], ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stderr.write(payload["error"]["message"] + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
