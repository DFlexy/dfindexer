"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import hashlib
from typing import Optional


def url_hash(url: str) -> str:
    # Gera hash MD5 de uma URL para usar como chave Redis
    return hashlib.md5(url.encode('utf-8')).hexdigest()


def html_long_key(url: str) -> str:
    # Chave Redis para HTML de longa duração
    return f"html:long:{url_hash(url)}"


def html_short_key(url: str) -> str:
    # Chave Redis para HTML de curta duração
    return f"html:short:{url_hash(url)}"


def metadata_key(info_hash: str) -> str:
    # Chave Redis para metadata principal (Hash)
    return f"metadata:data:{info_hash.lower()}"


def metadata_failure_key(info_hash: str) -> str:
    # Chave Redis para cache de falhas de metadata
    return f"metadata:failure:{info_hash.lower()}"


def metadata_failure503_key(info_hash: str) -> str:
    # Chave Redis para cache de falhas 503 de metadata
    return f"metadata:failure503:{info_hash.lower()}"


def tracker_key(info_hash: str) -> str:
    # Chave Redis para tracker (Hash)
    return f"tracker:{info_hash.lower()}"


def tracker_list_key() -> str:
    # Chave Redis para lista de trackers
    return "tracker:list"


def protlink_key(url: str) -> str:
    # Chave Redis para link protegido resolvido
    return f"protlink:{url_hash(url)}"


def circuit_metadata_key() -> str:
    # Chave Redis para circuit breaker de metadata (Hash)
    return "circuit:metadata"


def circuit_tracker_key() -> str:
    # Chave Redis para circuit breaker de tracker (Hash)
    return "circuit:tracker"


def flaresolverr_session_key(base_url: str) -> str:
    # Chave Redis para sessão FlareSolverr
    return f"flaresolverr:session:{base_url}"


def flaresolverr_created_key(base_url: str) -> str:
    # Chave Redis para timestamp de criação de sessão FlareSolverr
    return f"flaresolverr:created:{base_url}"


def imdb_key(info_hash: str) -> str:
    # Chave Redis para IMDB ID por info_hash
    return f"imdb:{info_hash.lower()}"


def imdb_title_key(base_title: str) -> str:
    # Chave Redis para IMDB ID por base_title normalizado
    import hashlib
    # Normaliza o título (lowercase, remove espaços extras) e cria hash
    normalized = base_title.lower().strip()
    normalized = ' '.join(normalized.split())  # Remove espaços extras
    title_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
    return f"imdb:title:{title_hash}"


def release_title_key(info_hash: str) -> str:
    # Chave Redis para release_title_magnet por info_hash
    return f"release_title:{info_hash.lower()}"


def torrent_cross_data_key(info_hash: str) -> str:
    # Chave Redis Hash para dados cruzados de torrent por info_hash
    # Armazena: original_title_html, release_title_magnet, translated_title_html, imdb, missing_dn, origem_audio_tag
    return f"torrent:cross:{info_hash.lower()}"