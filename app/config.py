"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import os
from typing import Optional


# Converte duração (10m, 12h, 7d) para segundos
def _parse_duration(duration_str: str) -> int:
    duration_str = duration_str.strip().lower()
    
    if duration_str.endswith('s'):
        return int(duration_str[:-1])
    elif duration_str.endswith('m'):
        return int(duration_str[:-1]) * 60
    elif duration_str.endswith('h'):
        return int(duration_str[:-1]) * 3600
    elif duration_str.endswith('d'):
        return int(duration_str[:-1]) * 86400
    else:
        # Assume segundos se não especificado
        return int(duration_str)


class Config:
    # Servidor
    PORT: int = int(os.getenv('PORT', '7006'))
    METRICS_PORT: int = int(os.getenv('METRICS_PORT', '8081'))
    
    # Redis
    REDIS_HOST: Optional[str] = os.getenv('REDIS_HOST', None)  # None = não configurado
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    
    # Cache
    HTML_CACHE_TTL_SHORT: int = _parse_duration(
        os.getenv('HTML_CACHE_TTL_SHORT', '10m')
    )
    HTML_CACHE_TTL_LONG: int = _parse_duration(
        os.getenv('HTML_CACHE_TTL_LONG', '12h')
    )
    FLARESOLVERR_SESSION_TTL: int = _parse_duration(
        os.getenv('FLARESOLVERR_SESSION_TTL', '8h')
    )
    
    # Logging
    LOG_LEVEL: int = int(os.getenv('LOG_LEVEL', '1'))
    LOG_FORMAT: str = os.getenv('LOG_FORMAT', 'console')  # 'json' ou 'console'
    
    # FlareSolverr
    FLARESOLVERR_ADDRESS: Optional[str] = os.getenv('FLARESOLVERR_ADDRESS', None)  # Padrão: None (desabilitado)
    
    EMPTY_QUERY_MAX_LINKS: int = int(os.getenv('EMPTY_QUERY_MAX_LINKS', '16'))
    
    # Concorrência (valores fixos - não configuráveis via ENV)
    TRACKER_MAX_WORKERS: int = 30  # Workers globais para trackers
    METADATA_MAX_CONCURRENT: int = 128  # Limite global de requisições de metadata simultâneas
    FLARESOLVERR_MAX_SESSIONS: int = 15  # Limite de sessões FlareSolverr simultâneas
    SCRAPER_MAX_WORKERS: int = 16  # Workers para processamento paralelo de links
    
    # Timeouts (valores fixos - não configuráveis via ENV)
    HTTP_REQUEST_TIMEOUT: int = 45  # Timeout padrão em segundos para requisições HTTP de páginas
    
    # Connection Pool (valores fixos - não configuráveis via ENV)
    HTTP_POOL_CONNECTIONS: int = 50  # Número de connection pools
    HTTP_POOL_MAXSIZE: int = 100  # Tamanho máximo de cada pool
    
    # Cache Local (valores fixos - não configuráveis via ENV)
    LOCAL_CACHE_ENABLED: bool = True  # Habilita cache HTTP local em memória
    LOCAL_CACHE_TTL: int = 30  # TTL do cache local em segundos (30s para evitar requisições duplicadas)
    
    # Tracker Scraping (valor fixo - não configurável via ENV)
    TRACKER_SCRAPING_ENABLED: bool = True  # Habilita scraping de trackers
    
    # Text Processing Constants
    MAX_QUERY_LENGTH: int = int(os.getenv('MAX_QUERY_LENGTH', '200'))  # Tamanho máximo de query de busca
    MAX_EPISODE_NUMBER: int = 99  # Número máximo de episódio válido
    MAX_EPISODE_DIFF: int = 20  # Diferença máxima entre episódios consecutivos
    INFO_HASH_LENGTH: int = 40  # Tamanho esperado de info_hash (SHA1)
    RELEASE_TITLE_CACHE_TTL: int = 7 * 24 * 3600  # 7 dias em segundos
    
    # Retry Configuration
    HTTP_RETRY_MAX_ATTEMPTS: int = int(os.getenv('HTTP_RETRY_MAX_ATTEMPTS', '3'))  # Número máximo de tentativas
    HTTP_RETRY_BACKOFF_BASE: float = float(os.getenv('HTTP_RETRY_BACKOFF_BASE', '1.0'))  # Base do backoff exponencial (segundos)
    
    # Proxy Configuration
    PROXY_TYPE: str = os.getenv('PROXY_TYPE', 'http').lower().strip()  # http, https, socks5, socks5h
    PROXY_HOST: Optional[str] = os.getenv('PROXY_HOST', None)
    PROXY_PORT: Optional[str] = os.getenv('PROXY_PORT', None)
    PROXY_USER: Optional[str] = os.getenv('PROXY_USER', None)
    PROXY_PASS: Optional[str] = os.getenv('PROXY_PASS', None)
    
