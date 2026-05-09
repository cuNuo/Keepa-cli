"""
keepa_cli/keepa_time.py
文件说明：处理 Keepa minute 与 UTC 时间之间的转换。
主要职责：把 Keepa 历史 csv 中的分钟时间转换为 Agent 可读的 ISO 时间。
依赖边界：纯本地时间转换，不读取文件、不访问网络。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


KEEPA_EPOCH = datetime(2011, 1, 1, tzinfo=UTC)


def keepa_minutes_to_datetime(keepa_minutes: int | str) -> datetime:
    return KEEPA_EPOCH + timedelta(minutes=int(keepa_minutes))


def keepa_minutes_to_iso(keepa_minutes: int | str) -> str:
    return keepa_minutes_to_datetime(keepa_minutes).strftime("%Y-%m-%dT%H:%M:%SZ")
