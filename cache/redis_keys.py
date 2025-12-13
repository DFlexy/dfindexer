"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import hashlib
from typing import Optional


def url_hash(url: str) -> str:
    # Gera hash MD5 de uma URL para usar como chave Redis
    return hashlib.md5(url.encode('utf-8')).hexdigest()


# ============================================================================
# 📁 html: - Cache de HTML (cache/html_cache.py)
# ============================================================================

def html_long_key(url: str) -> str:
    # Chave Redis para HTML de longa duração (12h TTL)
    return f"html:long:{url_hash(url)}"


def html_short_key(url: str) -> str:
    # Chave Redis para HTML de curta duração (10m TTL)
    return f"html:short:{url_hash(url)}"


def html_failure_key(url: str) -> str:
    # Chave Redis para cache de falhas de HTML (5m TTL)
    return f"html:failure:{url_hash(url)}"


# ============================================================================
# 📁 metadata: - Metadata de torrents (magnet/metadata.py)
# ============================================================================

def metadata_key(info_hash: str) -> str:
    # Chave Redis para metadata principal (7d TTL)
    return f"metadata:data:{info_hash.lower()}"


def metadata_failure_key(info_hash: str) -> str:
    # Chave Redis para cache de falhas genéricas de metadata (1m TTL)
    return f"metadata:failure:{info_hash.lower()}"


def metadata_failure503_key(info_hash: str) -> str:
    # Chave Redis para cache de falhas 503 de metadata (5m TTL)
    return f"metadata:failure503:{info_hash.lower()}"


# ============================================================================
# 📁 tracker: - Dados de trackers (tracker/service.py)
# ============================================================================

def tracker_key(info_hash: str) -> str:
    # Chave Redis para tracker por info_hash (24h TTL, Hash)
    return f"tracker:data:{info_hash.lower()}"


def tracker_list_key() -> str:
    # Chave Redis para lista de trackers (24h TTL)
    return "tracker:list:"


# ============================================================================
# 📁 imdb: - Cache de IMDB (utils/text/text_processing.py)
# ============================================================================

def imdb_key(info_hash: str) -> str:
    # Chave Redis para IMDB ID por info_hash (7d TTL)
    return f"imdb:hash:{info_hash.lower()}"


def imdb_title_key(base_title: str) -> str:
    # Chave Redis para IMDB ID por base_title normalizado (7d TTL)
    import hashlib
    # Normaliza o título (lowercase, remove espaços extras) e cria hash
    normalized = base_title.lower().strip()
    normalized = ' '.join(normalized.split())  # Remove espaços extras
    title_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
    return f"imdb:title:{title_hash}"


# ============================================================================
# 📁 release: - Release titles (utils/text/text_processing.py)
# ============================================================================

def release_title_key(info_hash: str) -> str:
    # Chave Redis para release_title_magnet por info_hash (7d TTL)
    return f"release:title:{info_hash.lower()}"


# ============================================================================
# 📁 cross: - Dados cruzados entre scrapers (utils/text/cross_data.py)
# ============================================================================

def torrent_cross_data_key(info_hash: str) -> str:
    # Chave Redis Hash para dados cruzados de torrent por info_hash (30d TTL padrão, 24h se tiver tracker)
    # Armazena: original_title_html, release_title_magnet, translated_title_html, imdb, missing_dn, origem_audio_tag, tracker_seed, tracker_leech, size
    return f"cross:torrent:{info_hash.lower()}"


# ============================================================================
# 📁 link: - Links resolvidos (utils/parsing/link_resolver.py)
# ============================================================================

def protlink_key(url: str) -> str:
    # Chave Redis para link protegido resolvido (7d TTL)
    return f"link:protected:{url_hash(url)}"


# ============================================================================
# 📁 circuit: - Circuit breakers (magnet/metadata.py, tracker/service.py)
# ============================================================================

def circuit_metadata_key() -> str:
    # Chave Redis para circuit breaker de metadata (1m TTL, Hash)
    return "circuit:metadata"


def circuit_tracker_key() -> str:
    # Chave Redis para circuit breaker de tracker (1m TTL, Hash)
    return "circuit:tracker"


# ============================================================================
# 📁 flaresolverr: - Sessões FlareSolverr (utils/http/flaresolverr.py)
# ============================================================================

def flaresolverr_session_key(base_url: str) -> str:
    # Chave Redis para sessão FlareSolverr (4h TTL)
    return f"flaresolverr:session:{base_url}"


def flaresolverr_created_key(base_url: str) -> str:
    # Chave Redis para timestamp de criação de sessão FlareSolverr (4h TTL)
    return f"flaresolverr:created:{base_url}"


def flaresolverr_failure_key(url: str) -> str:
    # Chave Redis para cache de falhas do FlareSolverr por URL (5m TTL)
    return f"flaresolverr:failure:{url_hash(url)}"


def flaresolverr_session_creation_failure_key(base_url: str) -> str:
    # Chave Redis para cache de falhas de criação de sessão FlareSolverr (2m TTL)
    # Usado para evitar tentativas repetidas muito rápidas quando o FlareSolverr está com problemas
    return f"flaresolverr:session_creation_failure:{base_url}"