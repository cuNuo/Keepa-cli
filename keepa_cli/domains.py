"""
keepa_cli/domains.py
文件说明：维护 Keepa domain 与 Amazon locale 的归一化表。
主要职责：支持 Agent 将 US、1、com 等输入解析为稳定 domain 信息。
依赖边界：纯本地静态数据，不访问网络或配置文件。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DomainInfo:
    code: str
    domain_id: int
    locale: str
    amazon_host: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


DOMAINS: tuple[DomainInfo, ...] = (
    DomainInfo("US", 1, "com", "amazon.com"),
    DomainInfo("GB", 2, "co.uk", "amazon.co.uk"),
    DomainInfo("DE", 3, "de", "amazon.de"),
    DomainInfo("FR", 4, "fr", "amazon.fr"),
    DomainInfo("JP", 5, "co.jp", "amazon.co.jp"),
    DomainInfo("CA", 6, "ca", "amazon.ca"),
    DomainInfo("IT", 8, "it", "amazon.it"),
    DomainInfo("ES", 9, "es", "amazon.es"),
    DomainInfo("IN", 10, "in", "amazon.in"),
    DomainInfo("MX", 11, "com.mx", "amazon.com.mx"),
    DomainInfo("BR", 12, "com.br", "amazon.com.br"),
)


def _build_aliases() -> dict[str, DomainInfo]:
    aliases: dict[str, DomainInfo] = {}
    for domain in DOMAINS:
        aliases[domain.code.upper()] = domain
        aliases[str(domain.domain_id)] = domain
        aliases[domain.locale.lower()] = domain
        aliases[domain.amazon_host.lower()] = domain
    return aliases


DOMAIN_ALIASES = _build_aliases()


def resolve_domain(value: str | int) -> DomainInfo:
    key = str(value).strip()
    if not key:
        raise ValueError("unknown Keepa domain: empty")

    domain = DOMAIN_ALIASES.get(key.upper()) or DOMAIN_ALIASES.get(key.lower())
    if domain is None:
        raise ValueError(f"unknown Keepa domain: {value}")
    return domain


def list_domains() -> list[dict[str, object]]:
    return [domain.to_dict() for domain in DOMAINS]
