# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import os
from typing import Optional

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
        return int(duration_str)

class Config:
    PORT: int = int(os.getenv('PORT', '7006'))
    METRICS_PORT: int = int(os.getenv('METRICS_PORT', '8081'))
    
    REDIS_HOST: Optional[str] = os.getenv('REDIS_HOST', None)
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    
    HTML_CACHE_TTL_SHORT: int = _parse_duration(
        os.getenv('HTML_CACHE_TTL_SHORT', '10m')
    )
    HTML_CACHE_TTL_LONG: int = _parse_duration(
        os.getenv('HTML_CACHE_TTL_LONG', '12h')
    )
    FLARESOLVERR_SESSION_TTL: int = _parse_duration(
        os.getenv('FLARESOLVERR_SESSION_TTL', '8h')
    )
    
    LOG_LEVEL: int = int(os.getenv('LOG_LEVEL', '1'))
    LOG_FORMAT: str = os.getenv('LOG_FORMAT', 'console')
    
    FLARESOLVERR_ADDRESS: Optional[str] = os.getenv('FLARESOLVERR_ADDRESS', None)
    
    EMPTY_QUERY_MAX_LINKS: int = int(os.getenv('EMPTY_QUERY_MAX_LINKS', '16'))
    
    TRACKER_MAX_WORKERS: int = 30
    METADATA_MAX_CONCURRENT: int = 128
    FLARESOLVERR_MAX_SESSIONS: int = 15
    SCRAPER_MAX_WORKERS: int = 16
    
    HTTP_REQUEST_TIMEOUT: int = 20
    
    HTTP_POOL_CONNECTIONS: int = 50
    HTTP_POOL_MAXSIZE: int = 100
    
    LOCAL_CACHE_ENABLED: bool = True
    LOCAL_CACHE_TTL: int = 30
    
    TRACKER_SCRAPING_ENABLED: bool = True
    
    # Tolerância do filtro de ano por link (slug): aceita query_year ± N (ex.: 2016 → 2015–2017)
    QUERY_YEAR_LINK_TOLERANCE: int = max(0, int(os.getenv('QUERY_YEAR_LINK_TOLERANCE', '1')))

    MAX_QUERY_LENGTH: int = int(os.getenv('MAX_QUERY_LENGTH', '200'))
    MAX_EPISODE_NUMBER: int = 99
    MAX_EPISODE_DIFF: int = 20
    INFO_HASH_LENGTH: int = 40
    RELEASE_TITLE_CACHE_TTL: int = _parse_duration(os.getenv('RELEASE_TITLE_CACHE_TTL', '7d'))
    METADATA_CACHE_TTL: int = _parse_duration(os.getenv('METADATA_CACHE_TTL', '7d'))
    TRACKER_CACHE_TTL: int = _parse_duration(os.getenv('TRACKER_CACHE_TTL', '24h'))
    IMDB_CACHE_TTL: int = _parse_duration(os.getenv('IMDB_CACHE_TTL', '7d'))
    RESOLVED_LINK_CACHE_TTL: int = _parse_duration(os.getenv('RESOLVED_LINK_CACHE_TTL', '7d'))
    CROSS_DATA_TTL_WITH_TRACKER: int = _parse_duration(os.getenv('CROSS_DATA_TTL_WITH_TRACKER', '24h'))
    CROSS_DATA_TTL_DEFAULT: int = _parse_duration(os.getenv('CROSS_DATA_TTL_DEFAULT', '30d'))
    
    HTTP_RETRY_MAX_ATTEMPTS: int = int(os.getenv('HTTP_RETRY_MAX_ATTEMPTS', '3'))
    HTTP_RETRY_BACKOFF_BASE: float = float(os.getenv('HTTP_RETRY_BACKOFF_BASE', '1.0'))
    
    PROXY_TYPE: str = os.getenv('PROXY_TYPE', 'http').lower().strip()
    PROXY_HOST: Optional[str] = os.getenv('PROXY_HOST', None)
    PROXY_PORT: Optional[str] = os.getenv('PROXY_PORT', None)
    PROXY_USER: Optional[str] = os.getenv('PROXY_USER', None)
    PROXY_PASS: Optional[str] = os.getenv('PROXY_PASS', None)
    
    RUN_ASYNC_TIMEOUT: float = float(os.getenv('RUN_ASYNC_TIMEOUT', '600'))
    ALL_SCRAPERS_MAX_CONCURRENT: int = max(1, int(os.getenv('ALL_SCRAPERS_MAX_CONCURRENT', '4')))
    INDEXED_COUNT_CACHE_TTL: float = float(os.getenv('INDEXED_COUNT_CACHE_TTL', '60'))
    
