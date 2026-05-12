"""
scripts/check_mcp_performance_gate.py
文件说明：MCP 性能与响应体积门禁。
主要职责：固定核心 MCP 调用基准，记录 p95 延迟、响应字节数、text fallback 与 structuredContent 体积。
依赖边界：只使用本地 fixture/dry-run，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.agent.mcp import handle_mcp_message
from keepa_cli.agent.session import AgentSession


DEFAULT_ITERATIONS = 30

THRESHOLDS: dict[str, dict[str, float]] = {
    "initialize": {"p95_ms": 50, "json_bytes": 50_000},
    "tools_list_research": {"p95_ms": 120, "json_bytes": 300_000},
    "tools_list_all_page": {"p95_ms": 120, "json_bytes": 180_000},
    "resources_list": {"p95_ms": 120, "json_bytes": 120_000},
    "prompts_list": {"p95_ms": 80, "json_bytes": 80_000},
    "context_policy": {"p95_ms": 120, "json_bytes": 80_000, "text_bytes": 80_000, "structured_bytes": 80_000},
    "products_get_fixture": {
        "p95_ms": 600,
        "json_bytes": 350_000,
        "text_bytes": 250_000,
        "structured_bytes": 350_000,
        "cache_hit_p95_ms": 120,
    },
}


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _text_fallback_bytes(response: Mapping[str, Any]) -> int:
    result = response.get("result")
    if not isinstance(result, Mapping):
        return 0
    total = 0
    for item in result.get("content") or []:
        if isinstance(item, Mapping) and item.get("type") == "text":
            total += len(str(item.get("text") or "").encode("utf-8"))
    return total


def _structured_bytes(response: Mapping[str, Any]) -> int:
    result = response.get("result")
    if not isinstance(result, Mapping) or "structuredContent" not in result:
        return 0
    return _json_bytes(result["structuredContent"])


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _request(method: str, params: Mapping[str, Any] | None = None, *, session: AgentSession) -> dict[str, Any]:
    response = handle_mcp_message(
        json.dumps({"jsonrpc": "2.0", "id": method, "method": method, "params": dict(params or {})}),
        env={},
        session=session,
    )
    if response is None:
        raise AssertionError(f"{method} returned notification response")
    if response.get("error"):
        raise AssertionError(f"{method} returned error: {response['error']}")
    return response


def _tool_call(name: str, arguments: Mapping[str, Any] | None, *, session: AgentSession) -> dict[str, Any]:
    return _request("tools/call", {"name": name, "arguments": dict(arguments or {})}, session=session)


def _bench(label: str, call: Callable[[], dict[str, Any]], *, iterations: int) -> dict[str, Any]:
    durations: list[float] = []
    last_response: dict[str, Any] | None = None
    for _ in range(iterations):
        start = time.perf_counter()
        last_response = call()
        durations.append((time.perf_counter() - start) * 1000)
    assert last_response is not None
    return {
        "label": label,
        "iterations": iterations,
        "p95_ms": round(_p95(durations), 3),
        "min_ms": round(min(durations), 3),
        "max_ms": round(max(durations), 3),
        "json_bytes": _json_bytes(last_response),
        "text_fallback_bytes": _text_fallback_bytes(last_response),
        "structured_content_bytes": _structured_bytes(last_response),
        "cache_hit_p95_ms": None,
    }


def _check_thresholds(item: dict[str, Any], failures: list[str]) -> None:
    thresholds = THRESHOLDS[item["label"]]
    checks = {
        "p95_ms": item["p95_ms"],
        "json_bytes": item["json_bytes"],
        "text_bytes": item["text_fallback_bytes"],
        "structured_bytes": item["structured_content_bytes"],
        "cache_hit_p95_ms": item.get("cache_hit_p95_ms"),
    }
    for key, value in checks.items():
        if value is None or key not in thresholds:
            continue
        if float(value) > thresholds[key]:
            failures.append(f"{item['label']} {key}={value} exceeds threshold {thresholds[key]}")


def run_gate(*, iterations: int = DEFAULT_ITERATIONS) -> dict[str, Any]:
    session = AgentSession(env={})
    benchmarks = [
        _bench("initialize", lambda: _request("initialize", {}, session=session), iterations=iterations),
        _bench("tools_list_research", lambda: _request("tools/list", {"toolset": "research"}, session=session), iterations=iterations),
        _bench("tools_list_all_page", lambda: _request("tools/list", {"toolset": "all", "limit": 8}, session=session), iterations=iterations),
        _bench("resources_list", lambda: _request("resources/list", {}, session=session), iterations=iterations),
        _bench("prompts_list", lambda: _request("prompts/list", {}, session=session), iterations=iterations),
        _bench("context_policy", lambda: _tool_call("context_policy", {}, session=session), iterations=iterations),
        _bench(
            "products_get_fixture",
            lambda: _tool_call(
                "products_get",
                {"asin": "B001", "domain": "US", "fixture": "product_B001GZ6QEC.json", "view": "summary"},
                session=session,
            ),
            iterations=iterations,
        ),
    ]

    cache_hit = _bench(
        "products_get_fixture_cache_hit",
        lambda: _tool_call(
            "products_get",
            {"asin": "B001", "domain": "US", "fixture": "product_B001GZ6QEC.json", "view": "summary"},
            session=session,
        ),
        iterations=iterations,
    )
    products = next(item for item in benchmarks if item["label"] == "products_get_fixture")
    products["cache_hit_p95_ms"] = cache_hit["p95_ms"]

    all_default = _request("tools/list", {"toolset": "all"}, session=session)["result"]
    all_default_names = [tool["name"] for tool in all_default.get("tools", [])]
    invariant_failures: list[str] = []
    if len(all_default_names) > 8 or not all_default.get("nextCursor"):
        invariant_failures.append("tools/list toolset=all without limit must return a paged starter set with nextCursor")
    if all_default_names[:4] != ["context_policy", "docs_index", "workflow_plan", "agent_profile_generate"]:
        invariant_failures.append(f"tools/list all starter order drifted: {all_default_names[:4]}")

    failures = list(invariant_failures)
    for item in benchmarks:
        _check_thresholds(item, failures)

    return {
        "ok": not failures,
        "iterations": iterations,
        "benchmarks": benchmarks,
        "starter_page": {
            "toolset_all_default_names": all_default_names,
            "nextCursor": all_default.get("nextCursor"),
            "_meta": all_default.get("_meta"),
        },
        "thresholds": THRESHOLDS,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 Keepa MCP 性能门禁。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS, help="每个基准项重复次数，默认 30。")
    args = parser.parse_args(argv)
    if args.iterations < 3:
        parser.error("--iterations must be at least 3")
    payload = run_gate(iterations=args.iterations)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif payload["ok"]:
        print(f"mcp performance gate ok: {args.iterations} iterations")
    else:
        for failure in payload["failures"]:
            print(failure, file=sys.stderr)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
