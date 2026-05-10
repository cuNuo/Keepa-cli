"""
scripts/redact_cassette.py
文件说明：脱敏 Keepa live cassette JSON。
主要职责：清理 URL query、header 与 JSON body 中的 secret 字段。
依赖边界：纯本地 JSON 转换，不访问网络。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from keepa_cli.cassettes import redact_cassette_payload, sanitize_cassette_file


def main() -> int:
    parser = argparse.ArgumentParser(description="脱敏 Keepa cassette JSON 文件。")
    parser.add_argument("input", help="输入 JSON 文件。")
    parser.add_argument("--out", required=True, help="输出脱敏 JSON 文件。")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.out)
    sanitize_cassette_file(input_path, output_path)
    print(f"wrote redacted cassette: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
