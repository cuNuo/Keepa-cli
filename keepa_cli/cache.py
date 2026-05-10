"""
keepa_cli/cache.py
文件说明：生成可审计 provenance，并提供 SQLite 响应缓存后端。
主要职责：为 Agent 输出 endpoint、参数哈希、来源、fixture 与缓存状态，缓存成功的只读 live JSON 响应。
依赖边界：仅使用标准库 SQLite；不缓存 API key、authorization 或其他明文凭据。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping


SECRET_PARAM_NAMES = {"key", "api_key", "apikey", "token", "authorization"}
DEFAULT_CACHE_TTL_SECONDS = 3600
CACHE_PATH_ENV = "KEEPA_CLI_CACHE_PATH"
CACHE_TTL_ENV = "KEEPA_CLI_CACHE_TTL_SECONDS"
CACHE_DISABLE_ENV = "KEEPA_CLI_NO_CACHE"


def _is_secret_name(name: str) -> bool:
    return name.lower().replace("-", "_") in SECRET_PARAM_NAMES


def _cache_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): ("[REDACTED]" if _is_secret_name(str(key)) else _cache_safe_value(item))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_cache_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_cache_safe_value(item) for item in value]
    return value


def _stable_params_hash(params: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _cache_safe_value(dict(params)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_json_hash(value: Any) -> str:
    encoded = json.dumps(_cache_safe_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def default_cache_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    explicit_path = env.get(CACHE_PATH_ENV)
    if explicit_path:
        return Path(explicit_path)

    appdata = env.get("APPDATA")
    if appdata:
        return Path(appdata) / "keepa-cli" / "response-cache.sqlite"

    xdg_cache_home = env.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "keepa-cli" / "response-cache.sqlite"

    return Path.home() / ".cache" / "keepa-cli" / "response-cache.sqlite"


def parse_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_cache_ttl_seconds(
    config: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    explicit_ttl: int | None = None,
) -> int:
    if explicit_ttl is not None:
        return max(0, int(explicit_ttl))
    env = os.environ if env is None else env
    if env.get(CACHE_TTL_ENV):
        return max(0, int(str(env[CACHE_TTL_ENV]).strip()))
    if config and config.get("cache_ttl_seconds") is not None:
        return max(0, int(config["cache_ttl_seconds"]))
    return DEFAULT_CACHE_TTL_SECONDS


def build_response_cache_key(
    *,
    method: str,
    endpoint: str,
    params: Mapping[str, Any],
    json_body: Any = None,
) -> str:
    payload = {
        "method": method.upper(),
        "endpoint": endpoint,
        "params": _cache_safe_value(dict(params)),
        "json_body": _cache_safe_value(json_body),
    }
    return "sqlite:" + _stable_json_hash(payload)


def explain_response_cache_key(
    *,
    method: str,
    endpoint: str,
    params: Mapping[str, Any],
    json_body: Any = None,
) -> dict[str, Any]:
    safe_params = _cache_safe_value(dict(params))
    safe_body = _cache_safe_value(json_body)
    payload = {
        "method": method.upper(),
        "endpoint": endpoint,
        "params": safe_params,
        "json_body": safe_body,
    }
    return {
        "backend": "sqlite",
        "cache_key": "sqlite:" + _stable_json_hash(payload),
        "method": method.upper(),
        "endpoint": endpoint,
        "params": safe_params,
        "params_hash": _stable_params_hash(params),
        "json_body": safe_body,
        "request_hash": _stable_json_hash(payload),
        "notes": [
            "cache_key is deterministic for method, endpoint, sanitized params, and sanitized json_body.",
            "secret-like parameter names are redacted before hashing and output.",
        ],
    }


def build_cache_provenance(
    *,
    endpoint: str,
    params: Mapping[str, Any],
    source: str,
    fixture: str | None = None,
    out: str | None = None,
    cache_hit: bool = False,
    cache_key: str | None = None,
    cache_path: str | None = None,
    created_at: int | None = None,
    expires_at: int | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "source": source,
        "endpoint": endpoint,
        "params_hash": _stable_params_hash(params),
        "cache_hit": cache_hit,
    }
    if cache_key:
        provenance["cache_key"] = cache_key
    if cache_path:
        provenance["cache_path"] = cache_path
    if created_at is not None:
        provenance["created_at"] = created_at
    if expires_at is not None:
        provenance["expires_at"] = expires_at
    if fixture:
        provenance["fixture"] = fixture
    if out:
        provenance["out"] = out
    return provenance


class SQLiteResponseCache:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                cache_key TEXT PRIMARY KEY,
                method TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                params_hash TEXT NOT NULL,
                request_json TEXT NOT NULL,
                body_json TEXT NOT NULL,
                token_bucket_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_responses_expires_at ON responses(expires_at)")
        return connection

    def get(self, cache_key: str, *, now: int | None = None) -> dict[str, Any] | None:
        now = int(time.time()) if now is None else now
        if not self.path.is_file():
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT request_json, body_json, token_bucket_json, created_at, expires_at, size_bytes
                FROM responses
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            request_json, body_json, token_bucket_json, created_at, expires_at, size_bytes = row
            if int(expires_at) <= now:
                connection.execute("DELETE FROM responses WHERE cache_key = ?", (cache_key,))
                connection.commit()
                return None
        return {
            "cache_key": cache_key,
            "request": json.loads(request_json),
            "body": json.loads(body_json),
            "token_bucket": json.loads(token_bucket_json),
            "created_at": int(created_at),
            "expires_at": int(expires_at),
            "size_bytes": int(size_bytes),
        }

    def set(
        self,
        *,
        cache_key: str,
        method: str,
        endpoint: str,
        params: Mapping[str, Any],
        request: Mapping[str, Any],
        body: Mapping[str, Any] | list[Any],
        token_bucket: Mapping[str, Any],
        ttl_seconds: int,
        now: int | None = None,
    ) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        expires_at = now + max(0, int(ttl_seconds))
        body_json = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        request_json = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        token_bucket_json = json.dumps(token_bucket, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO responses (
                    cache_key, method, endpoint, params_hash, request_json, body_json,
                    token_bucket_json, created_at, expires_at, size_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    method=excluded.method,
                    endpoint=excluded.endpoint,
                    params_hash=excluded.params_hash,
                    request_json=excluded.request_json,
                    body_json=excluded.body_json,
                    token_bucket_json=excluded.token_bucket_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    size_bytes=excluded.size_bytes
                """,
                (
                    cache_key,
                    method.upper(),
                    endpoint,
                    _stable_params_hash(params),
                    request_json,
                    body_json,
                    token_bucket_json,
                    now,
                    expires_at,
                    len(body_json.encode("utf-8")),
                ),
            )
            connection.commit()
        return {"cache_key": cache_key, "created_at": now, "expires_at": expires_at, "size_bytes": len(body_json)}

    def stats(self, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        if not self.path.is_file():
            return {
                "backend": "sqlite",
                "persistent_cache_enabled": True,
                "path": str(self.path),
                "entries": 0,
                "expired_entries": 0,
                "bytes": 0,
            }
        with closing(self._connect()) as connection:
            total = connection.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM responses").fetchone()
            expired = connection.execute("SELECT COUNT(*) FROM responses WHERE expires_at <= ?", (now,)).fetchone()
            bounds = connection.execute("SELECT MIN(created_at), MAX(created_at), MIN(expires_at) FROM responses").fetchone()
        return {
            "backend": "sqlite",
            "persistent_cache_enabled": True,
            "path": str(self.path),
            "entries": int(total[0]),
            "expired_entries": int(expired[0]),
            "bytes": int(total[1]),
            "oldest_created_at": bounds[0],
            "newest_created_at": bounds[1],
            "next_expires_at": bounds[2],
        }

    def inspect(self, cache_key: str, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        if not self.path.is_file():
            return {
                "backend": "sqlite",
                "persistent_cache_enabled": True,
                "path": str(self.path),
                "found": False,
                "cache_key": cache_key,
            }
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT method, endpoint, params_hash, created_at, expires_at, size_bytes
                FROM responses
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
        if row is None:
            return {
                "backend": "sqlite",
                "persistent_cache_enabled": True,
                "path": str(self.path),
                "found": False,
                "cache_key": cache_key,
            }
        method, endpoint, params_hash, created_at, expires_at, size_bytes = row
        return {
            "backend": "sqlite",
            "persistent_cache_enabled": True,
            "path": str(self.path),
            "found": True,
            "cache_key": cache_key,
            "method": method,
            "endpoint": endpoint,
            "params_hash": params_hash,
            "created_at": int(created_at),
            "expires_at": int(expires_at),
            "expired": int(expires_at) <= now,
            "size_bytes": int(size_bytes),
        }

    def prune_expired(self, *, dry_run: bool, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        if not self.path.is_file():
            return {
                "backend": "sqlite",
                "persistent_cache_enabled": True,
                "path": str(self.path),
                "dry_run": dry_run,
                "pruned": False,
                "expired_entries_removed": 0,
                "bytes_removed": 0,
            }
        with closing(self._connect()) as connection:
            expired = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM responses WHERE expires_at <= ?",
                (now,),
            ).fetchone()
            if not dry_run:
                connection.execute("DELETE FROM responses WHERE expires_at <= ?", (now,))
                connection.commit()
        return {
            "backend": "sqlite",
            "persistent_cache_enabled": True,
            "path": str(self.path),
            "dry_run": dry_run,
            "pruned": not dry_run,
            "expired_entries_removed": int(expired[0]),
            "bytes_removed": int(expired[1]),
        }

    def clear(self, *, dry_run: bool, now: int | None = None) -> dict[str, Any]:
        stats_before = self.stats(now=now)
        if not dry_run and self.path.is_file():
            with closing(self._connect()) as connection:
                connection.execute("DELETE FROM responses")
                connection.commit()
        return {
            "backend": "sqlite",
            "persistent_cache_enabled": True,
            "path": str(self.path),
            "dry_run": dry_run,
            "cleared": not dry_run,
            "entries_removed": int(stats_before["entries"]),
            "bytes_removed": int(stats_before["bytes"]),
        }
