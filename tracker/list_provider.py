"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import json
import logging
import threading
import time
from typing import List, Optional

import requests

from cache.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_TRACKERS_LIST_CACHE_KEY = "dynamic_trackers_list"
_TRACKERS_LIST_TTL_SECONDS = 24 * 3600

_TRACKER_SOURCES = [
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best_ip.txt",
    "https://cdn.jsdelivr.net/gh/ngosang/trackerslist@master/trackers_best_ip.txt",
    "https://ngosang.github.io/trackerslist/trackers_best_ip.txt",
]


def _normalize_tracker(url: str) -> Optional[str]:
    url = (url or "").strip()
    if not url:
        return None

    lowered = url.lower()
    if not lowered.startswith(("udp://", "http://", "https://")):
        return None

    # Corrige traduções equivocadas presentes em alguns magnets
    url = url.replace("/anunciar", "/announce")
    url = url.replace("/anunc", "/announce")

    return url


class TrackerListProvider:
    """Fornece lista de trackers (dinâmica com fallback estático)."""

    def __init__(self, redis_client=None):
        self.redis = redis_client or get_redis_client()
        self._lock = threading.Lock()
        self._memory_cache: List[str] = []
        self._memory_cache_expire_at = 0.0

    def get_trackers(self) -> List[str]:
        trackers = self._get_cached_trackers()
        if trackers:
            return trackers

        trackers = self._fetch_remote_trackers()
        if trackers:
            self._cache_trackers(trackers)
            return trackers

        logger.error("Falha ao obter lista dinâmica de trackers.")
        return []

    def _get_cached_trackers(self) -> Optional[List[str]]:
        now = time.time()
        if now < self._memory_cache_expire_at and self._memory_cache:
            return list(self._memory_cache)
        if not self.redis:
            return None
        try:
            cached = self.redis.get(_TRACKERS_LIST_CACHE_KEY)
            if not cached:
                return None
            trackers = json.loads(cached.decode("utf-8"))
            if not trackers:
                return None
            with self._lock:
                self._memory_cache = trackers
                self._memory_cache_expire_at = now + _TRACKERS_LIST_TTL_SECONDS
            logger.debug("Trackers recuperados do cache Redis.")
            return list(trackers)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao recuperar trackers do Redis: %s", exc)
            return None

    def _fetch_remote_trackers(self) -> Optional[List[str]]:
        session = requests.Session()
        session.headers.update({"User-Agent": "DFIndexer/1.0"})
        for source in _TRACKER_SOURCES:
            try:
                resp = session.get(source, timeout=10)
                resp.raise_for_status()
                trackers = [
                    tracker
                    for tracker in (line.strip() for line in resp.text.splitlines())
                    if tracker and _normalize_tracker(tracker)
                ]
                if trackers:
                    logger.info(
                        "Lista de trackers dinâmica carregada (%s) com %d entradas.",
                        source,
                        len(trackers),
                    )
                    return trackers
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Falha ao obter trackers de %s: %s", source, exc
                )
        return None

    def _cache_trackers(self, trackers: List[str]) -> None:
        with self._lock:
            self._memory_cache = list(trackers)
            self._memory_cache_expire_at = time.time() + _TRACKERS_LIST_TTL_SECONDS
        if not self.redis:
            return
        try:
            encoded = json.dumps(trackers).encode("utf-8")
            self.redis.setex(
                _TRACKERS_LIST_CACHE_KEY, _TRACKERS_LIST_TTL_SECONDS, encoded
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao gravar lista de trackers no Redis: %s", exc)


