"""
keepa_cli/ui/tui.py
文件说明：提供标准库实现的人类可用 TUI 工作台。
主要职责：解析 slash 命令、调用 command service，并渲染简洁的人类摘要。
依赖边界：不直接构造 Keepa API 请求，不访问网络，业务能力全部委托 service。
"""

from __future__ import annotations

import shlex
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from keepa_cli.service import run_command


PANEL_WIDTH = 92


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def _fit(text: str, width: int) -> str:
    if _display_width(text) <= width:
        return text
    output = ""
    used = 0
    for char in text:
        char_width = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
        if used + char_width > width - 1:
            break
        output += char
        used += char_width
    return output + "…"


def _pad(text: str, width: int) -> str:
    fitted = _fit(text, width)
    return fitted + " " * max(width - _display_width(fitted), 0)


def _panel(title: str, lines: Iterable[str], *, width: int = PANEL_WIDTH) -> list[str]:
    inner_width = width - 4
    output = [
        "+" + "-" * (width - 2) + "+",
        "| " + _pad(title, inner_width) + " |",
        "+" + "-" * (width - 2) + "+",
    ]
    for line in lines:
        output.append("| " + _pad(line, inner_width) + " |")
    output.append("+" + "-" * (width - 2) + "+")
    return output


def _columns(left: list[str], right: list[str], *, gap: int = 2, width: int = PANEL_WIDTH) -> list[str]:
    column_width = (width - gap) // 2
    height = max(len(left), len(right))
    rows: list[str] = []
    for index in range(height):
        left_text = left[index] if index < len(left) else ""
        right_text = right[index] if index < len(right) else ""
        rows.append(_pad(left_text, column_width) + " " * gap + _pad(right_text, column_width))
    return rows


def _doctor_context(env: Mapping[str, str] | None) -> dict[str, Any]:
    payload = run_command("doctor", env=env)
    if not payload.get("ok"):
        return {"auth": "unknown", "fixture": "unknown", "version": "unknown"}

    data = payload.get("data", {})
    auth = data.get("auth", {}) if isinstance(data, dict) else {}
    offline = data.get("offline", {}) if isinstance(data, dict) else {}
    return {
        "auth": str(auth.get("source", "missing")),
        "fixture": "ready" if offline.get("fixture_available") else "missing",
        "version": str(data.get("version", "unknown")),
    }


def _welcome(env: Mapping[str, str] | None) -> list[str]:
    context = _doctor_context(env)
    status_lines = _columns(
        [
            f"Auth      {context['auth']}",
            f"Fixture   {context['fixture']}",
            f"Version   {context['version']}",
        ],
        [
            "Schema    2026-05-09.1",
            "Mode      live-aware",
            "Safety    no live token use by default",
        ],
    )
    inspect_lines = [
        "Inspect   /doctor                 /domains",
        "Catalog   /product <ASIN>          /category 0 --parents",
        "History   /history <ASIN>          /history-export <ASIN>",
        "Market    /bestsellers <CAT>       /topsellers --dry-run",
    ]
    operate_lines = [
        "Preview   /finder --selection-file <json> --dry-run",
        "Export    /deals --selection-file <json> --fixture deals_home.json",
        "Graph     /graph <ASIN> --param amazon=1 --out graph.png",
        "Track     /tracking-list --asins-only --dry-run",
        "Agent     /capabilities            /quit",
    ]
    return [
        *_panel(
            "Keepa CLI 工作台  |  KEEPA COMMAND DECK",
            [
                "Agent-first Keepa API workspace",
                "Purpose   inspect products, preview token cost, export evidence",
                "Entrypoint keepa-cli == kc; Agent lanes use --json / --stdio",
            ],
        ),
        "",
        *_panel(
            "API Radar",
            status_lines,
        ),
        "",
        *_panel(
            "Command Palette",
            [
                "Workflow  inspect -> preview -> export -> record",
                "",
                *_columns(inspect_lines, operate_lines),
            ],
        ),
    ]


def _legacy_help() -> list[str]:
    return _panel(
        "Command Reference",
        [
            "/doctor",
            "/domains",
            "/product B001GZ6QEC --domain US --fixture product_B001GZ6QEC.json",
            "/history B001GZ6QEC --series amazon --fixture product_history_B001GZ6QEC.json",
            "/bestsellers 172282 --domain US --dry-run",
            "/seller A2L77EE7U53NWQ --fixture seller_A2L77EE7U53NWQ.json",
            "/tokens --fixture token_status.json",
            "/graph B09YNQCQKR --domain US --param amazon=1 --dry-run",
            "/lightningdeals --domain US --dry-run",
            "/tracking-list --asins-only --dry-run",
            "/category 0 --domain US --parents --fixture category_roots_US.json",
            "/category-search home kitchen --domain US --fixture category_search_home.json",
            "/capabilities",
            "/quit",
        ],
    )


def _compact_help() -> list[str]:
    return [
        *_panel(
            "Quick Reference",
            [
                "Use /help for complete commands.",
                "Best first run: /doctor, then /capabilities.",
            ],
        ),
    ]


def _parse_options(tokens: list[str]) -> tuple[list[str], dict[str, Any]]:
    positional: list[str] = []
    options: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            positional.append(token)
            index += 1
            continue
        name = token[2:]
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
            value = tokens[index + 1]
            if name == "param":
                extra_params = options.setdefault("params", {})
                if isinstance(extra_params, dict):
                    key, separator, raw_value = value.partition("=")
                    if separator and key.strip():
                        extra_params[key.strip()] = raw_value
            elif name in options:
                existing = options[name]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    options[name] = [existing, value]
            else:
                options[name] = value
            index += 2
        else:
            options[name] = True
            index += 1
    return positional, options


def _slash_to_command(line: str) -> tuple[str, dict[str, Any]]:
    tokens = shlex.split(line)
    if not tokens:
        return "help", {}
    slash_command = tokens[0].lstrip("/").lower()
    positional, options = _parse_options(tokens[1:])

    if slash_command == "doctor":
        return "doctor", {}
    if slash_command == "capabilities":
        return "capabilities", {}
    if slash_command == "domains":
        return "domains.list", {}
    if slash_command == "config":
        return "config.show", options
    if slash_command in {"token", "login"}:
        return "config.set-token", {"token": positional[0] if positional else "", **options}
    if slash_command == "max-tokens":
        return "config.set-max-tokens", {"max_tokens": positional[0] if positional else "", **options}
    if slash_command == "language":
        return "config.set-language", {"language": positional[0] if positional else "", **options}
    if slash_command == "product":
        return "products.get", {"asin": positional, **options}
    if slash_command == "product-search":
        return "products.search", {"term": " ".join(positional), **options}
    if slash_command == "history":
        return "history.trend", {"asin": positional[:1], **options}
    if slash_command == "history-export":
        return "history.export", {"asin": positional[:1], **options}
    if slash_command == "finder":
        return "finder.query", options
    if slash_command == "deals":
        return "deals.query", options
    if slash_command == "seller":
        return "sellers.get", {"seller": positional, **options}
    if slash_command == "bestsellers":
        return "bestsellers.get", {"category": positional[0] if positional else "", **options}
    if slash_command == "topsellers":
        return "topsellers.list", options
    if slash_command == "tokens":
        return "tokens.status", options
    if slash_command == "graph":
        return "graphs.image", {"asin": positional[0] if positional else "", **options}
    if slash_command == "lightningdeals":
        return "lightningdeals.list", {"asin": positional[0] if positional else "", **options}
    if slash_command == "tracking-list":
        return "tracking.list", options
    if slash_command == "tracking-list-names":
        return "tracking.list-names", options
    if slash_command == "tracking-get":
        return "tracking.get", {"asin": positional[0] if positional else "", **options}
    if slash_command == "tracking-remove":
        return "tracking.remove", {"asin": positional[0] if positional else "", **options}
    if slash_command == "tracking-notifications":
        return "tracking.notifications", options
    if slash_command == "browse":
        return "browse.snapshot", {"input": options.get("input"), **options}
    if slash_command == "batch":
        asin_file = positional[0] if positional else options.get("asin_file") or options.get("asin-file", "")
        return "batch.asins", {"asin_file": asin_file, **options}
    if slash_command == "templates":
        if positional and positional[0].lower() == "show":
            return "templates.show", {"name": positional[1] if len(positional) > 1 else "", **options}
        return "templates.list", options
    if slash_command == "report":
        return "reports.build", options
    if slash_command == "cache":
        return "cache.explain", options
    if slash_command == "cost":
        return "audit.cost", {"target_command": positional[0] if positional else "", **options}
    if slash_command == "category":
        return "categories.get", {"category": positional, **options}
    if slash_command == "category-search":
        return "categories.search", {"term": " ".join(positional), **options}
    return slash_command, options


def _summarize_success(payload: dict[str, Any]) -> list[str]:
    command = str(payload.get("command", "unknown"))
    data = payload.get("data")
    lines = [f"[{command}] OK"]

    if command == "doctor" and isinstance(data, dict):
        auth = data.get("auth", {})
        offline = data.get("offline", {})
        if isinstance(auth, dict):
            lines.append(f"认证    {auth.get('source', 'unknown')}")
        if isinstance(offline, dict):
            lines.append(f"离线    fixture={'ready' if offline.get('fixture_available') else 'missing'}")
        return lines

    if command == "capabilities" and isinstance(data, dict):
        commands = data.get("commands", [])
        command_count = len(commands) if isinstance(commands, list) else 0
        lines.append(f"Schema   {data.get('schema_version', '')}")
        lines.append(f"Commands {command_count}")
        lines.append("Modes    json / stdio / TUI")
        return lines

    if isinstance(data, dict):
        if command == "browse.snapshot":
            lines.append(f"浏览    rows={data.get('row_count', 0)} dir={data.get('out_dir', '')}")
            lines.append(f"打开    {data.get('index', '')}")
            return lines
        if command == "batch.asins":
            lines.append(f"批处理  tasks={data.get('task_count', 0)} tokens={data.get('estimated_tokens', 0)}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"文件    {output.get('path', '')}")
            return lines
        if command == "templates.list":
            templates = data.get("templates", [])
            count = len(templates) if isinstance(templates, list) else 0
            names = ", ".join(str(item.get("name", "")) for item in templates[:4] if isinstance(item, dict))
            lines.append(f"模板    count={count}")
            if names:
                lines.append(f"名称    {names}")
            return lines
        if command == "templates.show":
            lines.append(f"模板    {data.get('name', '')} kind={data.get('kind', '')}")
            return lines
        if command == "reports.build":
            lines.append(f"报告    rows={data.get('row_count', 0)} format={data.get('format', '')}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"文件    {output.get('path', '')}")
            return lines
        if command == "cache.explain":
            lines.append(f"缓存    source={data.get('source', 'unknown')} hit={data.get('cache_hit', False)}")
            lines.append(f"Token   saved={data.get('estimated_tokens_saved', 0)} live={data.get('estimated_tokens_if_live', 0)}")
            return lines
        if command == "audit.cost":
            totals = data.get("totals", {})
            if isinstance(totals, dict):
                lines.append(
                    f"成本    estimated={totals.get('estimated_tokens', 0)} worst={totals.get('worst_case_tokens', 0)}"
                )
            lines.append(f"确认    {data.get('requires_confirmation', False)}")
            return lines
        if data.get("dry_run"):
            estimate = payload.get("token_bucket", {}).get("estimated", {})
            if isinstance(estimate, dict):
                lines.append(
                    "预算    "
                    f"estimated={estimate.get('estimated_tokens')} "
                    f"worst={estimate.get('worst_case_tokens')} "
                    f"confirm={estimate.get('requires_confirmation')}"
                )
            lines.append("请求    dry-run；未访问 Keepa API")
            provenance = data.get("cache_provenance")
            if isinstance(provenance, dict):
                lines.append(f"来源    {provenance.get('source')} hash={str(provenance.get('params_hash', ''))[:10]}")
            return lines
        analysis = data.get("analysis")
        if isinstance(analysis, dict):
            series_map = analysis.get("series", {})
            if isinstance(series_map, dict):
                for series, series_data in list(series_map.items())[:3]:
                    if isinstance(series_data, dict):
                        all_time = series_data.get("all_time", {})
                        if isinstance(all_time, dict):
                            latest = all_time.get("latest", {})
                            points = all_time.get("points", 0)
                            value = latest.get("value") if isinstance(latest, dict) else ""
                            lines.append(f"历史    {series} points={points} latest={value}")
                return lines
        if "row_count" in data:
            lines.append(f"导出    rows={data.get('row_count')} format={data.get('format')}")
            output = data.get("output")
            if isinstance(output, dict):
                lines.append(f"文件    {output.get('path', '')}")
            return lines
        body = data.get("body")
        provenance = data.get("cache_provenance")
        if isinstance(provenance, dict):
            source = provenance.get("source", "")
            fixture = provenance.get("fixture", "")
            lines.append(f"来源    {source} {fixture}".strip())
        if isinstance(body, dict):
            products = body.get("products")
            if isinstance(products, list) and products:
                for product in products[:3]:
                    if isinstance(product, dict):
                        asin = product.get("asin", "")
                        title = product.get("title", "")
                        lines.append(f"产品    {asin}  {title}".strip())
                return lines
            categories = body.get("categories")
            if isinstance(categories, dict) and categories:
                for category_id, item in list(categories.items())[:3]:
                    if isinstance(item, dict):
                        lines.append(f"分类    {category_id}  {item.get('name', category_id)}")
                return lines
            sellers = body.get("sellers")
            if isinstance(sellers, dict) and sellers:
                for seller_id, item in list(sellers.items())[:3]:
                    name = item.get("sellerName", seller_id) if isinstance(item, dict) else seller_id
                    lines.append(f"卖家    {seller_id}  {name}")
                return lines
            for key, label in (("deals", "Deals"), ("topSellers", "卖家榜")):
                value = body.get(key)
                if isinstance(value, list):
                    lines.append(f"{label}  count={len(value)}")
                    return lines
            bestsellers = body.get("bestSellersList")
            if isinstance(bestsellers, dict):
                asin_list = bestsellers.get("asinList")
                count = len(asin_list) if isinstance(asin_list, list) else 0
                lines.append(f"榜单    category={bestsellers.get('categoryId', '')} count={count}")
                return lines
    lines.append("完成    已收到结构化响应；Agent 可使用 --json 查看完整 envelope")
    return lines


def _summarize_payload(payload: dict[str, Any]) -> list[str]:
    command = str(payload.get("command", "unknown"))
    if payload.get("ok"):
        return _panel(f"结果 [{command}] OK", _summarize_success(payload))

    error = payload.get("error", {})
    kind = error.get("kind", "unknown") if isinstance(error, dict) else "unknown"
    message = error.get("message", "") if isinstance(error, dict) else ""
    return _panel(
        f"结果 [{command}] ERROR",
        [
            f"[{command}] ERROR",
            f"类型    {kind}",
            f"说明    {message}",
        ],
    )


def run_tui_session(input_lines: Iterable[str], *, env: Mapping[str, str] | None = None) -> list[str]:
    output = _welcome(env)
    for raw_line in input_lines:
        line = raw_line.strip()
        if not line:
            continue
        output.append("")
        output.append(f"kc> {line}")
        if line in {"/quit", "quit", "exit"}:
            output.extend(_panel("会话", ["再见"]))
            break
        if line == "/help":
            output.extend(_legacy_help())
            continue
        command, params = _slash_to_command(line)
        payload = run_command(command, params, env=env)
        output.extend(_summarize_payload(payload))
    return output


def run_interactive_tui(*, env: Mapping[str, str] | None = None) -> int:
    if not sys.stdin.isatty():
        for line in run_tui_session(sys.stdin, env=env):
            print(line)
        return 0

    for line in _welcome(env):
        print(line)
    while True:
        try:
            line = input("kc> ").strip()
        except EOFError:
            for output_line in _panel("会话", ["再见"]):
                print(output_line)
            return 0
        if line in {"/quit", "quit", "exit"}:
            for output_line in _panel("会话", ["再见"]):
                print(output_line)
            return 0
        if not line:
            continue
        if line == "/help":
            for output_line in _legacy_help():
                print(output_line)
            continue
        command, params = _slash_to_command(line)
        payload = run_command(command, params, env=env)
        for output_line in _summarize_payload(payload):
            print(output_line)
