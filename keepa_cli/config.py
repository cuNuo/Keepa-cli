"""
keepa_cli/config.py
文件说明：管理 keepa-cli 本地配置路径、默认配置与初始化内容。
主要职责：生成 Agent 可读配置报告，并提供安全的 dry-run 初始化结果。
依赖边界：不读取或写入 API key，配置内容只包含低敏默认项。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from keepa_cli.redaction import redact_value


DEFAULT_CONFIG: dict[str, Any] = {
    "default_domain": "US",
    "cache_ttl_seconds": 3600,
    "max_tokens_per_request": 20,
}


def default_config_path(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    appdata = env.get("APPDATA")
    if appdata:
        return Path(appdata) / "keepa-cli" / "config.toml"

    xdg_config_home = env.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "keepa-cli" / "config.toml"

    return Path.home() / ".config" / "keepa-cli" / "config.toml"


def render_config_toml(config: Mapping[str, Any] | None = None) -> str:
    config = dict(DEFAULT_CONFIG if config is None else config)
    return (
        f'default_domain = "{config["default_domain"]}"\n'
        f"cache_ttl_seconds = {int(config['cache_ttl_seconds'])}\n"
        f"max_tokens_per_request = {int(config['max_tokens_per_request'])}\n"
    )


def load_config(path: Path | str | None = None, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else default_config_path(env)
    if not config_path.is_file():
        return dict(DEFAULT_CONFIG)

    loaded = tomllib.loads(config_path.read_text(encoding="utf-8"))
    merged = dict(DEFAULT_CONFIG)
    merged.update(loaded)
    return merged


def build_config_report(
    path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    config_path = Path(path) if path is not None else default_config_path(env)
    config = load_config(config_path, env=env)
    return {
        "path": str(config_path),
        "exists": config_path.is_file(),
        "config": redact_value(config),
    }


def init_config(
    path: Path | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    config_path = Path(path) if path is not None else default_config_path(env)
    content = render_config_toml()
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(content, encoding="utf-8")
    return {
        "path": str(config_path),
        "written": not dry_run,
        "dry_run": dry_run,
        "content": content,
    }
