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

# Circuit breaker para evitar consultas quando há muitos timeouts
_CIRCUIT_BREAKER_KEY = "tracker:circuit_breaker"
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3  # Número de timeouts consecutivos antes de desabilitar
_CIRCUIT_BREAKER_DISABLE_DURATION = 300  # 5 minutos de desabilitação após muitos timeouts

_TRACKER_SOURCES = [
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best_ip.txt",
    "https://cdn.jsdelivr.net/gh/ngosang/trackerslist@master/trackers_best_ip.txt",
    "https://ngosang.github.io/trackerslist/trackers_best_ip.txt",
]


def _is_circuit_breaker_open() -> bool:
    """
    Verifica se o circuit breaker está aberto (desabilitado).
    Retorna True se deve evitar consultas por um período.
    """
    redis = get_redis_client()
    if not redis:
        return False
    
    try:
        disabled_until = redis.get(_CIRCUIT_BREAKER_KEY)
        if disabled_until:
            disabled_until_float = float(disabled_until)
            if time.time() < disabled_until_float:
                return True
            # Período expirou, limpa a chave
            redis.delete(_CIRCUIT_BREAKER_KEY)
    except Exception:
        pass
    
    return False


def _record_timeout():
    """
    Registra um timeout e abre o circuit breaker se houver muitos timeouts consecutivos.
    """
    redis = get_redis_client()
    if not redis:
        return
    
    try:
        timeout_key = f"{_CIRCUIT_BREAKER_KEY}:timeouts"
        timeout_count = redis.incr(timeout_key)
        redis.expire(timeout_key, 60)  # Expira contador após 1 minuto
        
        # Se atingiu o limite, abre o circuit breaker
        if timeout_count >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
            disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
            redis.setex(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION, str(disabled_until))
            logger.warning(
                f"Circuit breaker aberto: {timeout_count} timeouts consecutivos. "
                f"Tracker desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
            )
            # Reseta contador
            redis.delete(timeout_key)
    except Exception as e:
        logger.debug(f"Erro ao registrar timeout: {e}")


def _record_success():
    """
    Registra uma requisição bem-sucedida, resetando o contador de timeouts.
    """
    redis = get_redis_client()
    if not redis:
        return
    
    try:
        timeout_key = f"{_CIRCUIT_BREAKER_KEY}:timeouts"
        redis.delete(timeout_key)
    except Exception:
        pass


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

        # Verifica circuit breaker antes de tentar buscar trackers remotos
        if _is_circuit_breaker_open():
            logger.debug("Circuit breaker aberto - pulando busca de trackers remotos")
            return []

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
                    logger.debug(
                        "Lista de trackers dinâmica carregada (%s) com %d entradas.",
                        source,
                        len(trackers),
                    )
                    _record_success()  # Registra sucesso
                    return trackers
            except requests.exceptions.Timeout:
                # Timeout detectado - registra e continua para próxima fonte
                _record_timeout()
                logger.warning(
                    "Timeout ao obter trackers de %s", source
                )
            except requests.exceptions.ReadTimeout:
                # Read timeout detectado - registra e continua para próxima fonte
                _record_timeout()
                logger.warning(
                    "Read timeout ao obter trackers de %s", source
                )
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


