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
        os.getenv('FLARESOLVERR_SESSION_TTL', '4h')
    )
    
    # Logging
    LOG_LEVEL: int = int(os.getenv('LOG_LEVEL', '1'))
    LOG_FORMAT: str = os.getenv('LOG_FORMAT', 'console')  # 'json' ou 'console'
    
    # FlareSolverr
    FLARESOLVERR_ADDRESS: Optional[str] = os.getenv('FLARESOLVERR_ADDRESS', None)  # Padrão: None (desabilitado)
    
    EMPTY_QUERY_MAX_LINKS: int = int(os.getenv('EMPTY_QUERY_MAX_LINKS', '15'))
    
    # Concorrência
    TRACKER_MAX_WORKERS: int = int(os.getenv('TRACKER_MAX_WORKERS', '20'))  # Workers globais para trackers
    METADATA_MAX_CONCURRENT: int = int(os.getenv('METADATA_MAX_CONCURRENT', '64'))  # Limite global de requisições de metadata simultâneas (aumentado de 32 para 64)
    FLARESOLVERR_MAX_SESSIONS: int = int(os.getenv('FLARESOLVERR_MAX_SESSIONS', '15'))  # Limite de sessões FlareSolverr simultâneas
    
    # Timeouts
    HTTP_REQUEST_TIMEOUT: int = int(os.getenv('HTTP_REQUEST_TIMEOUT', '30'))  # Timeout padrão em segundos para requisições HTTP de páginas
    
