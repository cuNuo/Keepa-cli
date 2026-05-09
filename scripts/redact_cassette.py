"""
scripts/redact_cassette.py
文件说明：脱敏 Keepa live cassette JSON。
主要职责：清理 URL query、header 与 JSON body 中的 secret 字段。
依赖边界：纯本地 JSON 转换，不访问网络。
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
from pathlib import Path
from typing import Any


SECRET_NAMES = {"key", "api_key", "apikey", "token", "authorization"}


def _redact_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.query:
        return value
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_pairs = [(key, "[REDACTED]" if key.lower() in SECRET_NAMES else item) for key, item in pairs]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(redacted_pairs), parsed.fragment)
    )


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


def main() -> int:
    parser = argparse.ArgumentParser(description="脱敏 Keepa cassette JSON 文件。")
    parser.add_argument("input", help="输入 JSON 文件。")
    parser.add_argument("--out", required=True, help="输出脱敏 JSON 文件。")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.out)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    redacted = redact_cassette_payload(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(redacted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote redacted cassette: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
