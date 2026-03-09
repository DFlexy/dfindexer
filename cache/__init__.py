"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

# Módulo de cache (Redis e memória)
import threading

from cache.redis_client import init_redis, get_redis_client
from cache.html_cache import HTMLCache
from cache.metadata_cache import MetadataCache
from cache.tracker_cache import TrackerCache


def cleanup_request_caches():
    """
    Limpa caches em threading.local e estado global acumulado entre requisições.
    Chamar após cada busca de scraper para evitar acúmulo de memória.
    """
    # Limpa threading.local de todos os módulos que usam _request_cache
    _modules_with_request_cache = []
    try:
        from cache import metadata_cache as _mc
        _modules_with_request_cache.append(_mc)
    except Exception:
        pass
    try:
        from cache import tracker_cache as _tc
        _modules_with_request_cache.append(_tc)
    except Exception:
        pass
    try:
        from utils.parsing import link_resolver as _lr
        _modules_with_request_cache.append(_lr)
    except Exception:
        pass
    try:
        from scraper import base as _sb
        _modules_with_request_cache.append(_sb)
    except Exception:
        pass
    try:
        from magnet import metadata as _mm
        _modules_with_request_cache.append(_mm)
    except Exception:
        pass
    try:
        from utils.http import flaresolverr as _fs
        _modules_with_request_cache.append(_fs)
    except Exception:
        pass

    for mod in _modules_with_request_cache:
        rc = getattr(mod, '_request_cache', None)
        if rc and isinstance(rc, threading.local):
            for attr in list(vars(rc).keys()):
                try:
                    delattr(rc, attr)
                except Exception:
                    pass

    # Limpa dicionários globais de locks que crescem
    try:
        from scraper.base import cleanup_url_state
        cleanup_url_state()
    except Exception:
        pass
    try:
        from magnet.metadata import cleanup_metadata_state
        cleanup_metadata_state()
    except Exception:
        pass


__all__ = [
    'init_redis',
    'get_redis_client',
    'HTMLCache',
    'MetadataCache',
    'TrackerCache',
    'cleanup_request_caches',
]
