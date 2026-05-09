"""
keepa_cli/request_spec.py
文件说明：构建 Keepa API 请求规格并输出 redacted 版本。
主要职责：规范 method、endpoint、query params 与 JSON body 的 dry-run 表达。
依赖边界：不执行网络请求，只负责请求描述和敏感字段打码。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from keepa_cli.redaction import redact_value


@dataclass(frozen=True)
class RequestSpec:
    method: str
    endpoint: str
    params: dict[str, Any]
    dry_run: bool = False
    json_body: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method": self.method,
            "endpoint": self.endpoint,
            "params_redacted": redact_value(self.params),
            "dry_run": self.dry_run,
        }
        if self.json_body is not None:
            payload["json_body_redacted"] = redact_value(self.json_body)
        return payload


def build_request_spec(
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    dry_run: bool = False,
    json_body: dict[str, Any] | None = None,
) -> RequestSpec:
    endpoint = path if path.startswith("/") else f"/{path}"
    return RequestSpec(
        method=method.upper(),
        endpoint=endpoint,
        params=params or {},
        dry_run=dry_run,
        json_body=json_body,
    )
