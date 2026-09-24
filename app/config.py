# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import os
from typing import List, Optional

CONFIG_WARNINGS: List[str] = []


def _warn(name: str, raw: str, fallback) -> None:
    CONFIG_WARNINGS.append(
        f"{name}='{raw}' é inválido; usando {fallback}"
    )


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


def _env_int(name: str, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        _warn(name, str(raw), default)
        return default
    if minimum is not None and value < minimum:
        _warn(name, str(raw), minimum)
        return minimum
    if maximum is not None and value > maximum:
        _warn(name, str(raw), maximum)
        return maximum
    return value


def _env_float(name: str, default: float, minimum: Optional[float] = None) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        _warn(name, str(raw), default)
        return default
    if minimum is not None and value < minimum:
        _warn(name, str(raw), minimum)
        return minimum
    return value


def _env_duration(name: str, default: str, minimum: int = 0) -> int:
    raw = os.getenv(name, default)
    try:
        value = _parse_duration(str(raw))
    except (TypeError, ValueError):
        _warn(name, str(raw), default)
        value = _parse_duration(default)
    if value < minimum:
        _warn(name, str(raw), minimum)
        return minimum
    return value


class Config:
    PORT: int = _env_int('PORT', 7006, minimum=1, maximum=65535)
    METRICS_PORT: int = _env_int('METRICS_PORT', 8081, minimum=1, maximum=65535)

    REDIS_HOST: Optional[str] = os.getenv('REDIS_HOST', None)
    REDIS_PORT: int = _env_int('REDIS_PORT', 6379, minimum=1, maximum=65535)
    REDIS_DB: int = _env_int('REDIS_DB', 0, minimum=0)

    HTML_CACHE_TTL_SHORT: int = _env_duration('HTML_CACHE_TTL_SHORT', '10m', minimum=1)
    HTML_CACHE_TTL_LONG: int = _env_duration('HTML_CACHE_TTL_LONG', '12h', minimum=1)
    FLARESOLVERR_SESSION_TTL: int = _env_duration('FLARESOLVERR_SESSION_TTL', '8h', minimum=60)

    LOG_LEVEL: int = _env_int('LOG_LEVEL', 1)
    LOG_FORMAT: str = os.getenv('LOG_FORMAT', 'console')

    FLARESOLVERR_ADDRESS: Optional[str] = os.getenv('FLARESOLVERR_ADDRESS', None)

    EMPTY_QUERY_MAX_LINKS: int = _env_int('EMPTY_QUERY_MAX_LINKS', 16, minimum=0)

    TRACKER_MAX_WORKERS: int = _env_int('TRACKER_MAX_WORKERS', 30, minimum=1)
    METADATA_MAX_CONCURRENT: int = _env_int('METADATA_MAX_CONCURRENT', 128, minimum=1)
    FLARESOLVERR_MAX_SESSIONS: int = _env_int('FLARESOLVERR_MAX_SESSIONS', 15, minimum=1)
    SCRAPER_MAX_WORKERS: int = _env_int('SCRAPER_MAX_WORKERS', 16, minimum=1)

    HTTP_REQUEST_TIMEOUT: int = _env_int('HTTP_REQUEST_TIMEOUT', 20, minimum=1)

    HTTP_POOL_CONNECTIONS: int = _env_int('HTTP_POOL_CONNECTIONS', 50, minimum=1)
    HTTP_POOL_MAXSIZE: int = _env_int('HTTP_POOL_MAXSIZE', 100, minimum=1)

    LOCAL_CACHE_ENABLED: bool = os.getenv('LOCAL_CACHE_ENABLED', 'true').strip().lower() != 'false'
    LOCAL_CACHE_TTL: int = _env_int('LOCAL_CACHE_TTL', 30, minimum=1)

    TRACKER_SCRAPING_ENABLED: bool = os.getenv('TRACKER_SCRAPING_ENABLED', 'true').strip().lower() != 'false'

    QUERY_YEAR_LINK_TOLERANCE: int = _env_int('QUERY_YEAR_LINK_TOLERANCE', 1, minimum=0)

    MAX_QUERY_LENGTH: int = _env_int('MAX_QUERY_LENGTH', 200, minimum=1)
    MAX_EPISODE_NUMBER: int = 99
    MAX_EPISODE_DIFF: int = 20
    INFO_HASH_LENGTH: int = 40
    RELEASE_TITLE_CACHE_TTL: int = _env_duration('RELEASE_TITLE_CACHE_TTL', '7d', minimum=1)
    METADATA_CACHE_TTL: int = _env_duration('METADATA_CACHE_TTL', '7d', minimum=1)
    TRACKER_CACHE_TTL: int = _env_duration('TRACKER_CACHE_TTL', '24h', minimum=1)
    IMDB_CACHE_TTL: int = _env_duration('IMDB_CACHE_TTL', '7d', minimum=1)
    RESOLVED_LINK_CACHE_TTL: int = _env_duration('RESOLVED_LINK_CACHE_TTL', '7d', minimum=1)
    CROSS_DATA_TTL_WITH_TRACKER: int = _env_duration('CROSS_DATA_TTL_WITH_TRACKER', '24h', minimum=1)
    CROSS_DATA_TTL_DEFAULT: int = _env_duration('CROSS_DATA_TTL_DEFAULT', '30d', minimum=1)

    HTTP_RETRY_MAX_ATTEMPTS: int = _env_int('HTTP_RETRY_MAX_ATTEMPTS', 3, minimum=0)
    HTTP_RETRY_BACKOFF_BASE: float = _env_float('HTTP_RETRY_BACKOFF_BASE', 1.0, minimum=0.0)

    PROXY_TYPE: str = os.getenv('PROXY_TYPE', 'http').lower().strip()
    PROXY_HOST: Optional[str] = os.getenv('PROXY_HOST', None)
    PROXY_PORT: Optional[str] = os.getenv('PROXY_PORT', None)
    PROXY_USER: Optional[str] = os.getenv('PROXY_USER', None)
    PROXY_PASS: Optional[str] = os.getenv('PROXY_PASS', None)

    RUN_ASYNC_TIMEOUT: float = _env_float('RUN_ASYNC_TIMEOUT', 180.0, minimum=1.0)
    ALL_SCRAPERS_MAX_CONCURRENT: int = _env_int('ALL_SCRAPERS_MAX_CONCURRENT', 4, minimum=1)
    INDEXED_COUNT_CACHE_TTL: float = _env_float('INDEXED_COUNT_CACHE_TTL', 60.0, minimum=0.0)
    SEARCH_RESULT_CACHE_TTL: int = _env_duration('SEARCH_RESULT_CACHE_TTL', '90s', minimum=0)

    FLARESOLVERR_SESSION_CREATE_TIMEOUT: int = _env_int('FLARESOLVERR_SESSION_CREATE_TIMEOUT', 90, minimum=5)
    FLARESOLVERR_SOLVE_TIMEOUT: int = _env_int('FLARESOLVERR_SOLVE_TIMEOUT', 60, minimum=5)
