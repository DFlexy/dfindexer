"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import hashlib
from typing import Optional


def url_hash(url: str) -> str:
    """Gera hash MD5 de uma URL para usar como chave Redis"""
    return hashlib.md5(url.encode('utf-8')).hexdigest()


def html_long_key(url: str) -> str:
    """Chave Redis para HTML de longa duração"""
    return f"html:long:{url_hash(url)}"


def html_short_key(url: str) -> str:
    """Chave Redis para HTML de curta duração"""
    return f"html:short:{url_hash(url)}"


def metadata_key(info_hash: str) -> str:
    """Chave Redis para metadata (Hash)"""
    return f"metadata:{info_hash.lower()}"


def tracker_key(info_hash: str) -> str:
    """Chave Redis para tracker (Hash)"""
    return f"tracker:{info_hash.lower()}"


def tracker_list_key() -> str:
    """Chave Redis para lista de trackers"""
    return "tracker:list"


def protlink_key(url: str) -> str:
    """Chave Redis para link protegido resolvido"""
    return f"protlink:{url_hash(url)}"


def circuit_metadata_key() -> str:
    """Chave Redis para circuit breaker de metadata (Hash)"""
    return "circuit:metadata"


def circuit_tracker_key() -> str:
    """Chave Redis para circuit breaker de tracker (Hash)"""
    return "circuit:tracker"


def flaresolverr_session_key(base_url: str) -> str:
    """Chave Redis para sessão FlareSolverr"""
    return f"flaresolverr:session:{base_url}"


def flaresolverr_created_key(base_url: str) -> str:
    """Chave Redis para timestamp de criação de sessão FlareSolverr"""
    return f"flaresolverr:created:{base_url}"

