"""
keepa_cli/commands/tracking.py
文件说明：tracking 命令族 service 路由。
主要职责：构建 Keepa tracking 请求、确认高成本动作并脱敏 webhook。
依赖边界：不处理 argparse，真实请求统一委托 KeepaClient。
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from keepa_cli.commands.common import bool_option, bool_param, client, confirmation_required, live_cache_options, param
from keepa_cli.envelope import error_envelope
from keepa_cli.high_value import attach_output_if_requested


TRACKING_COMMANDS = {
    "tracking.list",
    "tracking.list-names",
    "tracking.get",
    "tracking.add",
    "tracking.remove",
    "tracking.remove-all",
    "tracking.notifications",
    "tracking.webhook",
}


def can_handle(command: str) -> bool:
    return command in TRACKING_COMMANDS


def handle_tracking_command(command: str, params: Mapping[str, Any], *, fixture_dir: Path | str | None = None) -> dict[str, Any]:
    action = command.split(".", 1)[1]
    request_params: dict[str, Any] = {}
    method = "GET"
    json_body: list[dict[str, Any]] | None = None

    if action in {"list", "list-names"}:
        request_params["type"] = "list"
        if bool_option(params, "asins_only", "asins-only"):
            request_params["asins-only"] = "1"
        if action == "list-names":
            request_params["asins-only"] = "1"
    elif action == "get":
        asin = str(param(params, "asin", default="")).strip()
        if not asin:
            return error_envelope(command=command, kind="invalid_argument", message="tracking.get requires an ASIN")
        request_params.update({"type": "get", "asin": asin})
    elif action == "add":
        method = "POST"
        request_params["type"] = "add"
        json_body = tracking_body(params)
    elif action == "remove":
        asin = str(param(params, "asin", default="")).strip()
        if not asin:
            return error_envelope(command=command, kind="invalid_argument", message="tracking.remove requires an ASIN")
        request_params.update({"type": "remove", "asin": asin})
    elif action == "remove-all":
        request_params["type"] = "removeAll"
    elif action == "notifications":
        request_params.update(
            {
                "type": "notification",
                "since": str(param(params, "since", default=0)),
                "revise": bool_param(param(params, "revise", default=False)),
            }
        )
    elif action == "webhook":
        url = str(param(params, "url", default="")).strip()
        if not url:
            return error_envelope(command=command, kind="invalid_argument", message="tracking.webhook requires a URL")
        request_params.update({"type": "webhook", "url": url})
    else:
        return error_envelope(command=command, kind="unsupported_command", message=f"unsupported tracking action: {action}")

    confirmation = confirmation_required(command, {**dict(params), **request_params})
    if confirmation is not None:
        return confirmation

    payload = client(fixture_dir).request(
        command=command,
        method=method,
        path="/tracking",
        params=request_params,
        json_body=json_body,
        dry_run=bool_option(params, "dry_run", "dry-run"),
        fixture=params.get("fixture"),
        **live_cache_options(params),
    )
    if action == "webhook":
        payload = sanitize_webhook_payload(payload)
    return attach_output_if_requested(payload, param(params, "out", "output"))


def tracking_body(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_value = param(params, "tracking", "trackings")
    tracking_file = param(params, "tracking_file", "tracking-file")
    if tracking_file is not None:
        path = Path(str(tracking_file))
        if not path.is_file():
            raise ValueError(f"tracking file not found: {tracking_file}")
        raw_value = json.loads(path.read_text(encoding="utf-8"))
    elif isinstance(raw_value, str):
        raw_value = json.loads(raw_value)

    if isinstance(raw_value, Mapping):
        return [dict(raw_value)]
    if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes, bytearray)):
        result: list[dict[str, Any]] = []
        for item in raw_value:
            if not isinstance(item, Mapping):
                raise ValueError("tracking list items must be JSON objects")
            result.append(dict(item))
        return result
    raise ValueError("tracking.add requires tracking JSON object/list or tracking_file")


def redact_url_query_secrets(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = []
    for key, value in query:
        if key.lower() in {"key", "api_key", "apikey", "token", "authorization"}:
            redacted_query.append((key, "[REDACTED]"))
        else:
            redacted_query.append((key, value))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(redacted_query),
            parsed.fragment,
        )
    )


def sanitize_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if not isinstance(request, dict):
        return payload
    params_redacted = request.get("params_redacted")
    if not isinstance(params_redacted, dict):
        return payload
    url = params_redacted.get("url")
    if isinstance(url, str):
        params_redacted["url"] = redact_url_query_secrets(url)
    return payload
