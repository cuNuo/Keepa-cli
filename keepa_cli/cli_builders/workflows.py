"""
keepa_cli/cli_builders/workflows.py
文件说明：本地 workflow 命令族 argparse 构造与分发。
主要职责：注册 browse、batch、templates、reports、cache、audit 子命令并转换为 service 参数。
依赖边界：只处理 CLI 参数，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from keepa_cli.envelope import error_envelope
from keepa_cli.service import run_command


def add_workflow_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    browse = subparsers.add_parser("browse", help="生成本地 Web 浏览快照。")
    browse_subparsers = browse.add_subparsers(dest="browse_command")
    browse_snapshot = browse_subparsers.add_parser("snapshot", help="从离线 JSON 生成静态 HTML 快照。")
    browse_snapshot.add_argument("--input", help="Keepa JSON envelope、fixture 或报告输入。")
    browse_snapshot.add_argument("--out-dir", default="keepa-browse", help="输出目录。")
    browse_snapshot.add_argument("--title", default="Keepa Local Browse", help="页面标题。")

    batch = subparsers.add_parser("batch", help="批处理计划命令。")
    batch_subparsers = batch.add_subparsers(dest="batch_command")
    batch_asins = batch_subparsers.add_parser("asins", help="从 ASIN 文件生成产品查询批处理计划。")
    batch_asins.add_argument("asin_file", help="ASIN 列表文件；支持空行和 # 注释。")
    batch_asins.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    batch_asins.add_argument("--fixture", help="为每个任务指定离线 fixture。")
    batch_asins.add_argument("--out", help="写入批处理计划 JSON。")
    batch_asins.add_argument("--dry-run", action="store_true", help="生成 dry-run 计划，不访问 API。")

    templates = subparsers.add_parser("templates", help="内置工作流模板。")
    templates_subparsers = templates.add_subparsers(dest="templates_command")
    templates_subparsers.add_parser("list", help="列出内置模板。")
    templates_show = templates_subparsers.add_parser("show", help="显示一个模板。")
    templates_show.add_argument("name", help="模板名。")
    templates_show.add_argument("--out", help="把模板写入 JSON 文件。")

    reports = subparsers.add_parser("reports", help="本地报告生成命令。")
    reports_subparsers = reports.add_subparsers(dest="reports_command")
    reports_build = reports_subparsers.add_parser("build", help="从批处理或 fixture JSON 生成报告。")
    reports_build.add_argument("--input", required=True, help="输入 JSON 文件。")
    reports_build.add_argument("--format", choices=("markdown", "json", "csv"), default="markdown", help="报告格式。")
    reports_build.add_argument("--out", help="写入报告文件。")
    reports_build.add_argument("--out-dir", help="未提供 --out 时写入可提交报告目录。")
    reports_build.add_argument("--title", default="Keepa Report", help="报告标题。")
    reports_build.add_argument("--figure", help="嵌入已有 SVG/图片路径；未提供时 markdown/json 报告会本地生成 SVG。")
    reports_build.add_argument("--figures-dir", help="自动生成 SVG 的输出目录。")
    reports_build.add_argument("--figure-set", choices=("all", "history", "compare", "audit"), default="all", help="自动生成图表组：all、history、compare 或 audit。")
    reports_build.add_argument("--no-figures", action="store_true", help="不自动生成或嵌入图表。")

    figures = subparsers.add_parser("figures", help="生成 Agent 报告可插入的本地 SVG 图。")
    figures_subparsers = figures.add_subparsers(dest="figures_command")
    figures_research = figures_subparsers.add_parser("research", help="从产品/图谱 JSON 生成多面板 SVG。")
    figures_research.add_argument("--input", required=True, help="输入 JSON 文件。")
    figures_research.add_argument("--out-dir", default="keepa-figures", help="输出目录。")
    figures_research.add_argument("--title", default="Keepa Agent Research Figures", help="图标题。")
    figures_research.add_argument("--figure-set", choices=("all", "history", "compare", "audit"), default="all", help="只生成指定图表组，减少 Agent resource 噪声。")

    audit = subparsers.add_parser("audit", help="本地成本审计命令。")
    audit_subparsers = audit.add_subparsers(dest="audit_command")
    audit_cost = audit_subparsers.add_parser("cost", help="估算一个命令或命令清单的 Keepa token 成本。")
    audit_cost.add_argument("target_command", nargs="?", help="命令名，例如 products.get。")
    audit_cost.add_argument("--spec-file", help="JSON 文件，形如 [{\"command\":\"products.get\",\"params\":{...}}]。")
    audit_cost.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="命令参数，可重复。")

    workflow = subparsers.add_parser("workflow", help="Agent 工作流规划命令。")
    workflow_subparsers = workflow.add_subparsers(dest="workflow_command")
    workflow_plan = workflow_subparsers.add_parser("plan", help="生成不耗 token 的 Agent 执行图。")
    workflow_plan.add_argument(
        "name",
        choices=(
            "category-research",
            "product-research",
            "report-research",
            "tracking-audit",
            "inventory-audit",
            "velocity-research",
            "market-opportunity",
        ),
        help="工作流名称。",
    )
    workflow_plan.add_argument("--term", help="category-research 使用的关键词。")
    workflow_plan.add_argument("--asin", help="product-research 使用的 ASIN。")
    workflow_plan.add_argument("--domain", default="US", help="Keepa domain，例如 US、1、com。")
    workflow_plan.add_argument("--goal", default="research", choices=("research", "deal"), help="产品研究目标。")
    workflow_plan.add_argument("--hydrate-top", type=int, default=0, help="category-research 中显式规划 hydrate 前 N 个商品。")


def maybe_run_workflow_command(
    args: argparse.Namespace,
    *,
    parse_params: Any,
) -> tuple[int, dict[str, Any] | str] | None:
    if args.command == "browse" and args.browse_command == "snapshot":
        payload = run_command(
            "browse.snapshot",
            {"input": args.input, "out_dir": args.out_dir, "title": args.title},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "batch" and args.batch_command == "asins":
        payload = run_command(
            "batch.asins",
            {
                "asin_file": args.asin_file,
                "domain": args.domain,
                "fixture": args.fixture,
                "out": args.out,
                "dry_run": bool(args.dry_run),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "templates" and args.templates_command == "list":
        payload = run_command("templates.list")
        return 0 if payload["ok"] else 1, payload

    if args.command == "templates" and args.templates_command == "show":
        payload = run_command("templates.show", {"name": args.name, "out": args.out})
        return 0 if payload["ok"] else 1, payload

    if args.command == "reports" and args.reports_command == "build":
        payload = run_command(
            "reports.build",
            {
                "input": args.input,
                "format": args.format,
                "out": args.out,
                "out_dir": args.out_dir,
                "title": args.title,
                "figure": args.figure,
                "figures_dir": args.figures_dir,
                "figure_set": args.figure_set,
                "no_figures": bool(args.no_figures),
            },
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "figures" and args.figures_command == "research":
        payload = run_command(
            "figures.research",
            {"input": args.input, "out_dir": args.out_dir, "title": args.title, "figure_set": args.figure_set},
        )
        return 0 if payload["ok"] else 1, payload

    if args.command == "audit" and args.audit_command == "cost":
        try:
            parsed_params = parse_params(args.param)
            if args.spec_file:
                with open(args.spec_file, "r", encoding="utf-8") as handle:
                    specs = json.load(handle)
                payload = run_command("audit.cost", {"commands": specs})
            else:
                payload = run_command("audit.cost", {"target_command": args.target_command or "", "params": parsed_params})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return 2, error_envelope(command="audit.cost", kind="invalid_argument", message=str(exc))
        return 0 if payload["ok"] else 1, payload

    if args.command == "workflow" and args.workflow_command == "plan":
        payload = run_command(
            "workflow.plan",
            {
                "name": args.name,
                "term": args.term,
                "asin": args.asin,
                "domain": args.domain,
                "goal": args.goal,
                "hydrate_top": args.hydrate_top,
            },
        )
        return 0 if payload["ok"] else 1, payload

    return None
