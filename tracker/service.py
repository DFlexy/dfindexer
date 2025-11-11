"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple

from cache.redis_client import get_redis_client

from .list_provider import TrackerListProvider
from .udp_scraper import UDPScraper

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "tracker:peers:"


def _sanitize_tracker(url: str) -> Optional[str]:
    if not url:
        return None
    normalized = url.strip()
    if not normalized:
        return None
    for token in ("/anunciar", "/Anunciar", "/ANUNCIAR", "/anunc", "/Anunc", "/ANUNC"):
        if token in normalized:
            normalized = normalized.replace(token, "/announce")
    return normalized


def _stable_unique(values: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _filter_udp(trackers: Iterable[str]) -> List[str]:
    return [
        tracker
        for tracker in trackers
        if tracker and tracker.lower().startswith("udp://")
    ]


class TrackerService:
    """Serviço para obter seeds/leechers de trackers UDP."""

    def __init__(
        self,
        redis_client=None,
        scrape_timeout: float = 0.5,
        scrape_retries: int = 2,
        max_trackers: int = 0,
        cache_ttl: int = 24 * 3600,
    ):
        self.redis = redis_client or get_redis_client()
        self.cache_ttl = cache_ttl
        self._memory_cache: Dict[str, Tuple[float, Tuple[int, int]]] = {}
        self._cache_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=16)
        self._udp_scraper = UDPScraper(timeout=scrape_timeout, retries=scrape_retries)
        self._list_provider = TrackerListProvider(redis_client=self.redis)
        self.max_trackers = max_trackers

    def get_peers(self, info_hash: str, trackers: Iterable[str]) -> Tuple[int, int]:
        result = self.get_peers_bulk({info_hash: list(trackers)})
        return result.get(info_hash, (0, 0))

    def get_peers_bulk(
        self, infohash_trackers: Dict[str, List[str]]
    ) -> Dict[str, Tuple[int, int]]:
        results: Dict[str, Tuple[int, int]] = {}
        todo: Dict[str, List[str]] = {}

        for info_hash, trackers in infohash_trackers.items():
            if not info_hash:
                continue
            cached = self._get_cached(info_hash)
            if cached is not None:
                results[info_hash] = cached
            else:
                todo[info_hash] = trackers

        if not todo:
            return results

        futures = {
            self._executor.submit(
                self._scrape_info_hash,
                info_hash,
                trackers,
            ): info_hash
            for info_hash, trackers in todo.items()
        }

        for future in as_completed(futures):
            info_hash = futures[future]
            try:
                peers = future.result()
                if peers:
                    results[info_hash] = peers
                    self._store_cache(info_hash, peers)
                else:
                    results[info_hash] = (0, 0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tracker %s falhou para %s: %s", tracker, info_hash, exc)
                results[info_hash] = (0, 0)

        return results

    def _scrape_info_hash(
        self, info_hash: str, trackers: Optional[Iterable[str]]
    ) -> Optional[Tuple[int, int]]:
        info_hash = info_hash.lower()
        try:
            info_hash_bytes = bytes.fromhex(info_hash)
        except ValueError:
            logger.debug("info_hash inválido para scrape: %s", info_hash)
            return None

        provided_trackers = [
            tracker
            for tracker in (_sanitize_tracker(t) for t in (trackers or []))
            if tracker
        ]
        dynamic_trackers = self._list_provider.get_trackers()

        combined_trackers = _stable_unique(provided_trackers + dynamic_trackers)
        udp_trackers = _filter_udp(combined_trackers)

        if self.max_trackers > 0:
            udp_trackers = udp_trackers[: self.max_trackers]

        best: Optional[Tuple[int, int]] = None
        errors = 0
        if not udp_trackers:
            return None

        for tracker in udp_trackers:
            try:
                leechers, seeders = self._udp_scraper.scrape(tracker, info_hash_bytes)
                if seeders or leechers:
                    logger.debug(
                        "Peers obtidos via tracker %s para %s (S:%d L:%d).",
                        tracker,
                        info_hash,
                        seeders,
                        leechers,
                    )
                    return leechers, seeders
                if best is None:
                    best = (leechers, seeders)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Tracker %s não respondeu para %s: %s", tracker, info_hash, exc
                )
                errors += 1
                continue

        if best:
            return best
        if errors:
            logger.info(
                "Todos os trackers falharam para %s (tentativas=%d).",
                info_hash,
                errors,
            )
        return None

    def _cache_key(self, info_hash: str) -> str:
        return f"{_CACHE_PREFIX}{info_hash.lower()}"

    def _get_cached(self, info_hash: str) -> Optional[Tuple[int, int]]:
        key = self._cache_key(info_hash)
        now = time.time()
        with self._cache_lock:
            memory_value = self._memory_cache.get(key)
            if memory_value and memory_value[0] > now:
                return memory_value[1]

        if not self.redis:
            return None

        try:
            cached = self.redis.get(key)
            if not cached:
                return None
            data = json.loads(cached.decode("utf-8"))
            return int(data.get("leech", 0)), int(data.get("seed", 0))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao ler cache Redis de peers: %s", exc)
            return None

    def _store_cache(self, info_hash: str, peers: Tuple[int, int]) -> None:
        key = self._cache_key(info_hash)
        expires_at = time.time() + self.cache_ttl
        with self._cache_lock:
            self._memory_cache[key] = (expires_at, peers)

        if not self.redis:
            return
        try:
            payload = json.dumps({"leech": peers[0], "seed": peers[1]}).encode("utf-8")
            self.redis.setex(key, self.cache_ttl, payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao gravar cache Redis de peers: %s", exc)


