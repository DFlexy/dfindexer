# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import threading

from cache.store import MetadataCache, TrackerCache, get_redis_client, init_redis

def cleanup_request_caches():
    modules = []
    for name in ("cache.store", "utils.parsing", "scraper.base", "magnet.metadata", "utils.http"):
        try:
            modules.append(__import__(name, fromlist=["*"]))
        except Exception:
            pass

    for mod in modules:
        rc = getattr(mod, "_request_cache", None)
        if rc and isinstance(rc, threading.local):
            for attr in list(vars(rc).keys()):
                try:
                    delattr(rc, attr)
                except Exception:
                    pass

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
    try:
        from magnet.metadata_async import cleanup_metadata_async_state
        cleanup_metadata_async_state()
    except Exception:
        pass
    try:
        from utils.http import cleanup_flaresolverr_state
        cleanup_flaresolverr_state()
    except Exception:
        pass

__all__ = [
    "init_redis",
    "get_redis_client",
    "MetadataCache",
    "TrackerCache",
    "cleanup_request_caches",
]
