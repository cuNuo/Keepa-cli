"""
keepa_cli/cassettes.py
文件说明：处理 Keepa cassette 脱敏与本地文件工作流。
主要职责：清理 URL query、header 与 JSON body 中的 secret 字段，并返回可审计元数据。
依赖边界：纯本地 JSON 转换，不访问网络。
"""

from __future__ import annotations

import json
import csv
import urllib.parse
from pathlib import Path
from typing import Any


SECRET_NAMES = {"key", "api_key", "apikey", "token", "authorization"}


def redact_cassette_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SECRET_NAMES:
                result[key_text] = "[REDACTED]"
            elif key_text.lower() == "url" and isinstance(item, str):
                result[key_text] = _redact_url(item)
            else:
                result[key_text] = redact_cassette_payload(item)
        return result
    if isinstance(value, list):
        return [redact_cassette_payload(item) for item in value]
    return value


def sanitize_cassette_file(input_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    source = Path(input_path)
    target = Path(output_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    redacted = redact_cassette_payload(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "input": str(source),
        "output": str(target),
        "format": "json",
        "size_bytes": target.stat().st_size,
        "redacted_secret_names": sorted(SECRET_NAMES),
    }


def promote_cassette_fixture(
    input_path: Path | str,
    *,
    name: str,
    tests_dir: Path | str = "tests/fixtures",
    package_dir: Path | str = "keepa_cli/fixtures",
    manifest_path: Path | str | None = "evidence/manifest.csv",
    title: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    fixture_name = _fixture_name(name)
    source = Path(input_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    redacted = redact_cassette_payload(payload)
    targets = [Path(tests_dir) / fixture_name, Path(package_dir) / fixture_name]
    content = json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not dry_run:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        if manifest_path:
            _append_manifest_entry(Path(manifest_path), targets[0], title or fixture_name)
    return {
        "input": str(source),
        "fixture_name": fixture_name,
        "targets": [{"path": str(target), "exists": target.exists(), "size_bytes": target.stat().st_size if target.exists() else len(content.encode("utf-8"))} for target in targets],
        "manifest": str(manifest_path) if manifest_path else None,
        "manifest_updated": bool(manifest_path and not dry_run),
        "dry_run": dry_run,
        "format": "json",
        "redacted_secret_names": sorted(SECRET_NAMES),
    }


def _fixture_name(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError("fixture name is required")
    if any(part in name for part in ("..", "/", "\\")):
        raise ValueError("fixture name must not contain path separators")
    return name if name.endswith(".json") else f"{name}.json"


def _append_manifest_entry(manifest_path: Path, fixture_path: Path, title: str) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    logical_path = fixture_path.as_posix()
    existing = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    if logical_path in existing:
        return
    write_header = not existing.strip()
    with manifest_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if write_header:
            writer.writerow(["logical_path", "title", "status", "updated_at", "summary"])
        writer.writerow(
            [
                logical_path,
                title,
                "active",
                "2026-05-10",
                "Promoted sanitized Keepa cassette fixture for offline regression.",
            ]
        )


def _redact_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.query:
        return value
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_pairs = [(key, "[REDACTED]" if key.lower() in SECRET_NAMES else item) for key, item in pairs]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(redacted_pairs), parsed.fragment)
    )
