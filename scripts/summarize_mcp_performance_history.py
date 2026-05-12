"""
scripts/summarize_mcp_performance_history.py
文件说明：汇总 MCP 性能门禁历史结果并给出阈值收紧建议。
主要职责：读取多轮 CI artifact / 本地性能 JSON，用真实 p95 历史生成下一轮 THRESHOLDS 建议。
依赖边界：只读取本地 JSON 文件，不访问 GitHub API，不访问真实 Keepa API。
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_mcp_performance_gate import THRESHOLDS


METRIC_SOURCES: dict[str, str] = {
    "p95_ms": "p95_ms",
    "json_bytes": "json_bytes",
    "text_bytes": "text_fallback_bytes",
    "structured_bytes": "structured_content_bytes",
    "cache_hit_p95_ms": "cache_hit_p95_ms",
}


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _has_glob(value: str) -> bool:
    return any(char in value for char in "*?[]")


def _expand_inputs(inputs: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        if _has_glob(raw):
            paths.extend(Path(match) for match in glob.glob(raw, recursive=True))
            continue
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.json")))
        else:
            paths.append(path)
    unique: dict[str, Path] = {}
    for path in paths:
        if path.is_file():
            unique[str(path.resolve())] = path
    return [unique[key] for key in sorted(unique)]


def _load_reports(paths: Sequence[Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping) and isinstance(payload.get("benchmarks"), list):
            item = dict(payload)
            item["_source_path"] = str(path)
            reports.append(item)
    return reports


def _metric_values(reports: Sequence[Mapping[str, Any]], label: str, metric: str) -> list[float]:
    source = METRIC_SOURCES[metric]
    values: list[float] = []
    for report in reports:
        for benchmark in report.get("benchmarks") or []:
            if isinstance(benchmark, Mapping) and benchmark.get("label") == label and benchmark.get(source) is not None:
                values.append(float(benchmark[source]))
    return values


def _observed_value(metric: str, values: Sequence[float]) -> float:
    if metric in {"json_bytes", "text_bytes", "structured_bytes"}:
        return max(values) if values else 0.0
    return _p95(values)


def _recommended_threshold(
    metric: str,
    observed: float,
    *,
    latency_factor: float,
    cache_hit_factor: float,
    bytes_factor: float,
    min_latency_ms: float,
    min_bytes: int,
) -> float | int:
    if metric in {"json_bytes", "text_bytes", "structured_bytes"}:
        return max(min_bytes, int(math.ceil(observed * bytes_factor)))
    factor = cache_hit_factor if metric == "cache_hit_p95_ms" else latency_factor
    return round(max(min_latency_ms, observed * factor), 3)


def summarize_history(
    reports: Sequence[Mapping[str, Any]],
    *,
    min_samples: int = 3,
    latency_factor: float = 1.5,
    cache_hit_factor: float = 1.5,
    bytes_factor: float = 1.2,
    min_latency_ms: float = 10.0,
    min_bytes: int = 1024,
) -> dict[str, Any]:
    suggestions: dict[str, dict[str, float | int]] = {}
    decisions: list[dict[str, Any]] = []
    for label, current_thresholds in THRESHOLDS.items():
        for metric in current_thresholds:
            values = _metric_values(reports, label, metric)
            if not values:
                continue
            observed = _observed_value(metric, values)
            recommended = _recommended_threshold(
                metric,
                observed,
                latency_factor=latency_factor,
                cache_hit_factor=cache_hit_factor,
                bytes_factor=bytes_factor,
                min_latency_ms=min_latency_ms,
                min_bytes=min_bytes,
            )
            current = current_thresholds[metric]
            if float(recommended) < float(current):
                change = "tighten"
            elif float(recommended) > float(current):
                change = "watch_regression"
            else:
                change = "keep"
            suggestions.setdefault(label, {})[metric] = recommended
            decisions.append(
                {
                    "label": label,
                    "metric": metric,
                    "sample_count": len(values),
                    "observed": round(observed, 3),
                    "current_threshold": current,
                    "suggested_threshold": recommended,
                    "change": change,
                }
            )

    ready = len(reports) >= min_samples
    return {
        "ok": True,
        "report_count": len(reports),
        "min_samples": min_samples,
        "ready_to_tighten": ready,
        "policy": {
            "latency_factor": latency_factor,
            "cache_hit_factor": cache_hit_factor,
            "bytes_factor": bytes_factor,
            "min_latency_ms": min_latency_ms,
            "min_bytes": min_bytes,
        },
        "current_thresholds": THRESHOLDS,
        "suggested_thresholds": suggestions,
        "decisions": decisions,
        "next_actions": [
            "先累计至少 min_samples 份 CI performance artifact，再把 change=tighten 的 suggested_thresholds 回写到 check_mcp_performance_gate.py。",
            "若 change=watch_regression，先查看对应 CI run 的原始 JSON 与代码变更，不直接放宽门禁。",
            "收紧后继续保留 --out artifact，下一轮再用真实历史复核。",
        ],
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="汇总 MCP performance gate 历史 JSON 并输出阈值收紧建议。")
    parser.add_argument("inputs", nargs="+", help="performance JSON 文件、目录或 glob。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    parser.add_argument("--out", type=Path, help="把汇总 JSON 写入指定路径。")
    parser.add_argument("--min-samples", type=int, default=3, help="建议收紧阈值前至少需要的历史报告数量。")
    parser.add_argument("--latency-factor", type=float, default=1.5, help="p95 latency 建议阈值倍率。")
    parser.add_argument("--cache-hit-factor", type=float, default=1.5, help="cache hit p95 建议阈值倍率。")
    parser.add_argument("--bytes-factor", type=float, default=1.2, help="响应体积建议阈值倍率。")
    parser.add_argument("--min-latency-ms", type=float, default=10.0, help="延迟阈值最低保底，避免过度收紧。")
    parser.add_argument("--min-bytes", type=int, default=1024, help="响应体积阈值最低保底，避免过度收紧。")
    args = parser.parse_args(argv)

    paths = _expand_inputs(args.inputs)
    reports = _load_reports(paths)
    if not reports:
        print("no valid MCP performance reports found", file=sys.stderr)
        return 1
    payload = summarize_history(
        reports,
        min_samples=args.min_samples,
        latency_factor=args.latency_factor,
        cache_hit_factor=args.cache_hit_factor,
        bytes_factor=args.bytes_factor,
        min_latency_ms=args.min_latency_ms,
        min_bytes=args.min_bytes,
    )
    payload["input_files"] = [str(path) for path in paths]
    if args.out:
        _write_json(args.out, payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"mcp performance history: {payload['report_count']} reports, ready_to_tighten={payload['ready_to_tighten']}")
        for decision in payload["decisions"]:
            if decision["change"] != "tighten":
                continue
            print(
                f"{decision['label']} {decision['metric']}: "
                f"{decision['current_threshold']} -> {decision['suggested_threshold']} "
                f"(observed {decision['observed']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
