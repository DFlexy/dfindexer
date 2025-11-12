"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import os


def _parse_duration(duration_str: str) -> int:
    """Converte duração (10m, 12h, 7d) para segundos"""
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
    """Configurações da aplicação via variáveis de ambiente"""
    
    # Servidor
    PORT: int = int(os.getenv('PORT', '7006'))
    METRICS_PORT: int = int(os.getenv('METRICS_PORT', '8081'))
    # Trackers / scrape
    TRACKER_SCRAPE_TIMEOUT: float = float(os.getenv('TRACKER_SCRAPE_TIMEOUT', '0.5'))
    TRACKER_SCRAPE_RETRIES: int = int(os.getenv('TRACKER_SCRAPE_RETRIES', '2'))
    TRACKER_SCRAPE_MAX_TRACKERS: int = int(os.getenv('TRACKER_SCRAPE_MAX_TRACKERS', '0'))
    TRACKER_CACHE_TTL: int = _parse_duration(os.getenv('TRACKER_CACHE_TTL', '24h'))
    
    # Redis
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    
    # Cache
    SHORT_LIVED_CACHE_EXPIRATION: int = _parse_duration(
        os.getenv('SHORT_LIVED_CACHE_EXPIRATION', '10m')
    )
    LONG_LIVED_CACHE_EXPIRATION: int = _parse_duration(
        os.getenv('LONG_LIVED_CACHE_EXPIRATION', '12h')
    )
    
    # Scraper padrão utilizado quando nenhum tipo é informado
    DEFAULT_SCRAPER_TYPE: str = 'starck'
    
    # Logging
    # LOG_LEVEL: 0 (debug), 1 (info), 2 (warn), 3 (error) - valores numéricos como no Go
    LOG_LEVEL: int = int(os.getenv('LOG_LEVEL', '1'))  # Padrão: 1 (info)
    LOG_FORMAT: str = os.getenv('LOG_FORMAT', 'console')  # 'json' ou 'console'
    
    # Magnet Metadata API
    MAGNET_METADATA_ENABLED: bool = os.getenv('MAGNET_METADATA_ENABLED', 'true').lower() == 'true'  # Padrão: true
    
