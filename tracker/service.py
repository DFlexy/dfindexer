"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple

from cache.redis_client import get_redis_client
from cache.redis_keys import tracker_key
from app.config import Config

from .list_provider import TrackerListProvider
from .udp_scraper import UDPScraper

logger = logging.getLogger(__name__)


def _is_redis_connection_error(error: Exception) -> bool:
    error_str = str(error).lower()
    connection_errors = [
        "connection refused",
        "error 111",
        "error 111 connecting",
        "cannot connect",
        "no connection",
        "connection error",
        "connection timeout",
        "name or service not known",
    ]
    return any(err in error_str for err in connection_errors)


def _log_redis_error(operation: str, error: Exception) -> None:
    if _is_redis_connection_error(error):
        logger.debug(f"Redis fallback: {operation}")
    else:
        logger.debug(f"Redis error: {operation}")


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
        # Usa configuração global para workers (padrão: 20 para suportar múltiplos scrapers)
        max_workers = Config.TRACKER_MAX_WORKERS if hasattr(Config, 'TRACKER_MAX_WORKERS') else 20
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
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
                # Se peers não é None, significa que conseguiu obter resposta do tracker (sucesso)
                # Mesmo que seja (0, 0), devemos salvar para evitar consultas futuras
                if peers is not None:
                    results[info_hash] = peers
                    self._store_cache(info_hash, peers)
                else:
                    # peers é None = falha ao obter dados (não salva, vai para circuito breaker)
                    results[info_hash] = (0, 0)
            except Exception as exc:  # noqa: BLE001
                # Exceção = falha (não salva, vai para circuito breaker)
                logger.warning("Falha ao obter peers para %s: %s", info_hash, exc)
                results[info_hash] = (0, 0)

        return results

    def _scrape_info_hash(
        self, info_hash: str, trackers: Optional[Iterable[str]]
    ) -> Optional[Tuple[int, int]]:
        info_hash = info_hash.lower()
        try:
            info_hash_bytes = bytes.fromhex(info_hash)
        except ValueError:
            logger.debug("Invalid info_hash: %s", info_hash[:16])
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

        if not udp_trackers:
            return None

        best: Optional[Tuple[int, int]] = None
        dns_errors = {}  # Agrupa erros de DNS por tracker
        timeout_errors = {}  # Agrupa erros de timeout por tracker
        
        for tracker in udp_trackers:
            try:
                peers = self._scrape_single_tracker(
                    tracker, info_hash_bytes, info_hash
                )
                # Se peers não é None, significa que conseguiu obter resposta do tracker (sucesso)
                # Mesmo que seja (0, 0), é um resultado válido
                if peers is not None:
                    leechers, seeders = peers
                    if seeders or leechers:
                        logger.debug("Tracker %s: %s (S:%d L:%d)", tracker, info_hash, seeders, leechers)
                        return leechers, seeders
                    # Se ambos são 0, armazena em best para retornar ao final (é resultado válido)
                    if best is None:
                        best = (leechers, seeders)
            except Exception as exc:  # noqa: BLE001
                # Detecta e trata erros de forma mais amigável
                error_msg = str(exc)
                is_dns_error = (
                    "Temporary failure in name resolution" in error_msg
                    or "[Errno -3]" in error_msg
                    or "[Errno -2]" in error_msg
                    or "[Errno -5]" in error_msg
                    or "No address associated with hostname" in error_msg
                    or "name or service not known" in error_msg.lower()
                    or "Name or service not known" in error_msg
                )
                is_timeout_error = (
                    "Timeout" in error_msg
                    or "timeout" in error_msg.lower()
                    or isinstance(exc, TimeoutError)
                )
                
                if is_dns_error:
                    # Agrupa erros de DNS - só loga uma vez por tracker
                    if tracker not in dns_errors:
                        dns_errors[tracker] = True
                        logger.debug("Tracker %s: DNS error", tracker)
                    # Não loga cada info_hash individualmente para erros de DNS
                elif is_timeout_error:
                    # Agrupa erros de timeout - só loga uma vez por tracker
                    if tracker not in timeout_errors:
                        timeout_errors[tracker] = True
                        logger.debug("Tracker %s: timeout", tracker)
                    # Não loga cada info_hash individualmente para erros de timeout
                else:
                    # Outros erros são logados normalmente (mas de forma mais resumida)
                    error_type = type(exc).__name__
                    short_msg = error_msg.split('\n')[0][:100]  # Primeira linha, máximo 100 chars
                    logger.debug("Tracker %s: %s - %s", tracker, error_type, short_msg[:50])

        # Se best não é None, retorna (mesmo que seja 0, 0 - é resultado válido)
        if best is not None:
            return best
        return None

    def _scrape_single_tracker(
        self, tracker: str, info_hash_bytes: bytes, info_hash: str
    ) -> Optional[Tuple[int, int]]:
        """
        Faz scrape de um único tracker.
        Método auxiliar para consultas paralelas.
        """
        try:
            leechers, seeders = self._udp_scraper.scrape(tracker, info_hash_bytes)
            return leechers, seeders
        except Exception:  # noqa: BLE001
            # Erro será tratado e logado no loop principal com agrupamento
            return None

    def _cache_key(self, info_hash: str) -> str:
        # Mantém para compatibilidade com cache em memória
        return tracker_key(info_hash)

    def _get_cached(self, info_hash: str) -> Optional[Tuple[int, int]]:
        # Obtém peers do cache (Redis primeiro, memória se Redis não disponível)
        try:
            from cache.tracker_cache import TrackerCache
            tracker_cache = TrackerCache()
            cached_data = tracker_cache.get(info_hash)
            if cached_data:
                return int(cached_data.get("leech", 0)), int(cached_data.get("seed", 0))
        except Exception:
            pass
        
        return None

    def _store_cache(self, info_hash: str, peers: Tuple[int, int]) -> None:
        # Salva peers no cache (Redis primeiro, memória se Redis não disponível)
        try:
            from cache.tracker_cache import TrackerCache
            tracker_cache = TrackerCache()
            tracker_data = {"leech": peers[0], "seed": peers[1]}
            tracker_cache.set(info_hash, tracker_data)
        except Exception:
            pass


