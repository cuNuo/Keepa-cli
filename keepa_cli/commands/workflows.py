"""
keepa_cli/commands/workflows.py
文件说明：本地 workflow 命令族 service 路由。
主要职责：把 browse、batch、templates、reports、cache、audit 命令封装为稳定 envelope。
依赖边界：不访问真实 Keepa API，不处理 argparse。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from keepa_cli.envelope import success_envelope
from keepa_cli.workflows import (
    audit_cost,
    build_batch_asins,
    build_browse_snapshot,
    build_workflow_plan,
    build_report,
    list_templates,
    show_template,
)
from keepa_cli.figures import build_research_figures


WORKFLOW_COMMANDS = {
    "browse.snapshot",
    "batch.asins",
    "templates.list",
    "templates.show",
    "reports.build",
    "audit.cost",
    "figures.research",
    "workflow.plan",
}


def _param(params: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


def _bool_option(params: Mapping[str, Any], *names: str) -> bool:
    value = _param(params, *names)
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def can_handle(command: str) -> bool:
    return command in WORKFLOW_COMMANDS


def handle_workflow_command(command: str, params: Mapping[str, Any]) -> dict[str, Any]:
    if command == "browse.snapshot":
        data = build_browse_snapshot(
            input_path=_param(params, "input", "input_path"),
            out_dir=str(_param(params, "out_dir", "out-dir", default="keepa-browse")),
            title=str(_param(params, "title", default="Keepa Local Browse")),
        )
    elif command == "batch.asins":
        data = build_batch_asins(
            asin_file=str(_param(params, "asin_file", "asin-file", default="")),
            domain=str(_param(params, "domain", default="US")),
            dry_run=_bool_option(params, "dry_run", "dry-run"),
            fixture=_param(params, "fixture"),
            out=_param(params, "out", "output"),
        )
    elif command == "templates.list":
        data = list_templates()
    elif command == "templates.show":
        data = show_template(str(_param(params, "name", default="")), _param(params, "out", "output"))
    elif command == "reports.build":
        data = build_report(
            input_path=str(_param(params, "input", "input_path", default="")),
            output_format=str(_param(params, "format", default="markdown")),
            out=_param(params, "out", "output"),
            title=str(_param(params, "title", default="Keepa Report")),
        )
    elif command == "audit.cost":
        specs = params.get("commands")
        if not isinstance(specs, Sequence) or isinstance(specs, (str, bytes, bytearray)):
            specs = [
                {
                    "command": str(_param(params, "target_command", "command", default="")),
                    "params": dict(params.get("params") or {}),
                }
            ]
        data = audit_cost([dict(item) for item in specs if isinstance(item, Mapping)])
    elif command == "figures.research":
        data = build_research_figures(
            input_path=str(_param(params, "input", "input_path", default="")),
            out_dir=str(_param(params, "out_dir", "out-dir", default="keepa-figures")),
            title=str(_param(params, "title", default="Keepa Agent Research Figures")),
        )
    elif command == "workflow.plan":
        data = build_workflow_plan(
            name=str(_param(params, "name", "workflow", default="")),
            term=_param(params, "term"),
            asin=_param(params, "asin"),
            domain=str(_param(params, "domain", default="US")),
            goal=str(_param(params, "goal", default="research")),
            hydrate_top=int(_param(params, "hydrate_top", "hydrate-top", default=0) or 0),
        )
    else:
        raise ValueError(f"unsupported workflow command: {command}")

    return success_envelope(
        command=command,
        data=data,
        request={"transport": "service"},
        token_bucket={},
    )
