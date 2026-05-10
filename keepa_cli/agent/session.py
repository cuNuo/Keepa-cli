"""
keepa_cli/agent/session.py
文件说明：维护 Agent 长会话缓存、去重与 token 账本。
主要职责：为 stdio/MCP 提供统一执行入口，避免重复请求和预算失控。
依赖边界：业务执行委托 service runner；本模块不直接访问 Keepa API。
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from keepa_cli.envelope import error_envelope
from keepa_cli.service import run_command
from keepa_cli.token_budget import estimate_request_budget


Runner = Callable[[str, Mapping[str, Any]], dict[str, Any]]

RUNTIME_KEYS = {"from_cache", "yes"}
SECRET_KEY_PARTS = ("key", "api_key", "apikey", "token", "authorization", "password", "secret")


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def _safe_for_cache_key(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("[REDACTED]" if _is_secret_key(str(key)) else _safe_for_cache_key(item))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in RUNTIME_KEYS
        }
    if isinstance(value, list):
        return [_safe_for_cache_key(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_for_cache_key(item) for item in value]
    return value


def build_cache_key(command: str, params: Mapping[str, Any] | None = None) -> str:
    normalized = _safe_for_cache_key(dict(params or {}))
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{command}:{digest}"


def _bypass_confirmation(params: Mapping[str, Any]) -> bool:
    return bool(params.get("yes") or params.get("dry_run") or params.get("dry-run") or params.get("fixture"))


def _confirmation_required(command: str, budget: dict[str, Any], *, tool: str | None = None) -> dict[str, Any]:
    details: dict[str, Any] = {
        "resume_with": "--yes",
        "estimated_tokens": budget["estimated_tokens"],
        "worst_case_tokens": budget["worst_case_tokens"],
    }
    if tool:
        details["resume_with_tool"] = {"tool": tool, "params": {"yes": True}}
    return error_envelope(
        command=command,
        kind="confirmation_required",
        message="request requires explicit confirmation because it may consume significant Keepa tokens",
        details=details,
    )


def _consumed_tokens(payload: Mapping[str, Any], budget: Mapping[str, Any]) -> tuple[int, str]:
    token_bucket = payload.get("token_bucket")
    if isinstance(token_bucket, Mapping):
        consumed = token_bucket.get("tokens_consumed")
        if isinstance(consumed, int):
            return consumed, "token_bucket"
        if isinstance(consumed, str) and consumed.isdigit():
            return int(consumed), "token_bucket"
    return int(budget.get("estimated_tokens") or 0), "estimated_fallback"


@dataclass
class BudgetLedger:
    session_estimated: int = 0
    session_consumed: int = 0
    remaining_limit: int | None = None
    blocked_actions: list[dict[str, Any]] = field(default_factory=list)
    cache_hits: int = 0
    consumed_source: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_estimated": self.session_estimated,
            "session_consumed": self.session_consumed,
            "remaining_limit": self.remaining_limit,
            "blocked_actions": list(self.blocked_actions),
            "cache_hits": self.cache_hits,
            "consumed_source": self.consumed_source,
        }


@dataclass
class AgentSession:
    env: Mapping[str, str] | None = None
    max_tokens: int | None = None
    runner: Runner | None = None
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    ledger: BudgetLedger = field(default_factory=BudgetLedger)

    def __post_init__(self) -> None:
        self._runner = self.runner or (lambda command, params: run_command(command, params, env=self.env))
        self.ledger.remaining_limit = self.max_tokens

    def execute(
        self,
        command: str,
        params: Mapping[str, Any] | None = None,
        *,
        tool: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        params_dict = dict(params or {})
        from_cache = params_dict.get("from_cache")
        if from_cache:
            return self._cache_response(command, str(from_cache), tool=tool)

        cache_key = build_cache_key(command, params_dict)
        if use_cache and cache_key in self.cache:
            return self._cache_response(command, cache_key, tool=tool)

        budget = estimate_request_budget(command, params_dict).to_dict()
        self._add_estimate(budget)
        if budget["requires_confirmation"] and not _bypass_confirmation(params_dict):
            payload = _confirmation_required(command, budget, tool=tool)
            payload["cache_key"] = cache_key
            payload["cache_hit"] = False
            self.ledger.blocked_actions.append(
                {
                    "command": command,
                    "tool": tool,
                    "cache_key": cache_key,
                    "estimated_tokens": budget["estimated_tokens"],
                    "worst_case_tokens": budget["worst_case_tokens"],
                    "reason": "confirmation_required",
                }
            )
            payload["budget_ledger"] = self.ledger.to_dict()
            return payload

        payload = self._runner(command, params_dict)
        payload = copy.deepcopy(payload)
        payload["cache_key"] = cache_key
        payload["cache_hit"] = False
        self._attach_mcp_provenance(payload, tool=tool, cache_key=cache_key, cache_hit=False)
        consumed, source = _consumed_tokens(payload, budget)
        self._add_consumed(consumed, source)
        payload["budget_ledger"] = self.ledger.to_dict()
        if payload.get("ok") and use_cache:
            self.cache[cache_key] = copy.deepcopy(payload)
        return payload

    def _cache_response(self, command: str, cache_key: str, *, tool: str | None = None) -> dict[str, Any]:
        cached = self.cache.get(cache_key)
        if cached is None:
            payload = error_envelope(
                command=command,
                kind="cache_miss",
                message=f"session cache key not found: {cache_key}",
                details={"cache_key": cache_key},
            )
            payload["cache_key"] = cache_key
            payload["cache_hit"] = False
            payload["budget_ledger"] = self.ledger.to_dict()
            return payload
        payload = copy.deepcopy(cached)
        payload["cache_key"] = cache_key
        payload["cache_hit"] = True
        self.ledger.cache_hits += 1
        self._attach_mcp_provenance(payload, tool=tool, cache_key=cache_key, cache_hit=True)
        payload["budget_ledger"] = self.ledger.to_dict()
        return payload

    def _add_estimate(self, budget: Mapping[str, Any]) -> None:
        self.ledger.session_estimated += int(budget.get("estimated_tokens") or 0)
        self._refresh_remaining()

    def _add_consumed(self, tokens: int, source: str) -> None:
        self.ledger.session_consumed += int(tokens)
        self.ledger.consumed_source = source
        self._refresh_remaining()

    def _refresh_remaining(self) -> None:
        if self.max_tokens is not None:
            self.ledger.remaining_limit = max(self.max_tokens - self.ledger.session_estimated, 0)

    @staticmethod
    def _attach_mcp_provenance(
        payload: dict[str, Any],
        *,
        tool: str | None,
        cache_key: str,
        cache_hit: bool,
    ) -> None:
        if not tool:
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        provenance = data.setdefault("provenance", {})
        if isinstance(provenance, dict):
            provenance["mcp"] = {
                "server": "keepa",
                "tool": tool,
                "transport": "stdio",
                "session_cache_key": cache_key,
                "cache_hit": cache_hit,
            }
