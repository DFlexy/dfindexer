# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import json
import logging
import threading
import time
from typing import List, Optional

import requests

from cache.redis_client import get_redis_client
from cache.redis_keys import tracker_list_key, circuit_tracker_key
from app.config import Config

logger = logging.getLogger(__name__)

_request_cache = threading.local()

_logged_sources = {}
_logged_sources_lock = threading.Lock()
_LOG_COOLDOWN = 60

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

_CIRCUIT_BREAKER_KEY = circuit_tracker_key()
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3
_CIRCUIT_BREAKER_DISABLE_DURATION = 60

_TRACKER_SOURCES = [
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all_http.txt",
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all_https.txt",
]

def _is_circuit_breaker_open() -> bool:
    """Verifica se o circuit breaker está aberto (desabilitado)"""
    redis = get_redis_client()
    
    if redis:
        try:
            disabled_until_str = redis.hget(_CIRCUIT_BREAKER_KEY, 'disabled')
            if disabled_until_str:
                disabled_until_float = float(disabled_until_str)
                now = time.time()
                if now < disabled_until_float:
                    return True
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'disabled')
        except Exception:
            pass
    
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0
        }
    
    if _request_cache.circuit_breaker['disabled']:
        logger.debug("Circuit breaker: tracker desabilitado (query atual)")
    
    return _request_cache.circuit_breaker['disabled']

def _record_timeout():
    """Registra um timeout e abre o circuit breaker se houver muitos timeouts consecutivos"""
    redis = get_redis_client()
    
    if redis:
        try:
            timeout_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, 'timeouts', 1)
            redis.expire(_CIRCUIT_BREAKER_KEY, 60)
            

            if timeout_count >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {timeout_count} timeouts consecutivos. "
                    f"Tracker desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
            return
        except Exception as e:
            logger.debug("Timeout register error")
    
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0
        }
    
    _request_cache.circuit_breaker['timeout_count'] += 1
    

    if _request_cache.circuit_breaker['timeout_count'] >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(f"Circuit breaker: {_request_cache.circuit_breaker['timeout_count']} timeouts (query atual)")

def _record_success():
    """Registra uma requisição bem-sucedida, resetando o contador de timeouts"""
    redis = get_redis_client()
    
    if redis:
        try:
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
        except Exception:
            pass
    
    if hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker['timeout_count'] = 0
        _request_cache.circuit_breaker['disabled'] = False

def _normalize_tracker(url: str) -> Optional[str]:
    url = (url or "").strip()
    if not url:
        return None

    lowered = url.lower()
    if not lowered.startswith(("udp://", "http://", "https://")):
        return None

    url = url.replace("/anunciar", "/announce")
    url = url.replace("/anunc", "/announce")

    return url

class TrackerListProvider:

    def __init__(self, redis_client=None):
        self.redis = redis_client or get_redis_client()
        self._lock = threading.Lock()
        self._memory_cache: List[str] = []
        self._memory_cache_expire_at = 0.0

    def get_trackers(self) -> List[str]:
        trackers = self._get_cached_trackers()
        if trackers:
            return trackers

        if _is_circuit_breaker_open():
            logger.debug("Circuit breaker: pulando trackers remotos")
            if not self.redis and self._memory_cache:
                logger.debug("Usando cache em memória expirado como fallback (Redis desativado)")
                return list(self._memory_cache)
            return []

        trackers = self._fetch_remote_trackers()
        if trackers:
            self._cache_trackers(trackers)
            return trackers

        if not self.redis and self._memory_cache:
            logger.debug("Falha ao buscar trackers remotos - usando cache em memória como fallback (Redis desativado)")
            return list(self._memory_cache)

        logger.error("Falha ao obter lista dinâmica de trackers.")
        return []

    def _get_cached_trackers(self) -> Optional[List[str]]:
        if self.redis:
            try:
                cache_key = tracker_list_key()
                cached = self.redis.get(cache_key)
                if not cached:
                    return None
                trackers = json.loads(cached.decode("utf-8"))
                if not trackers:
                    return None
                trackers_list = list(trackers)
                return trackers_list
            except Exception as exc:  # noqa: BLE001
                _log_redis_error("recuperar trackers do cache", exc)
                return None
        
        if not self.redis:
            now = time.time()
            if now < self._memory_cache_expire_at and self._memory_cache:
                return list(self._memory_cache)
        
        return None

    def _fetch_remote_trackers(self) -> Optional[List[str]]:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        from utils.http.proxy import get_proxy_dict
        
        session = requests.Session()
        session.headers.update({"User-Agent": "DFIndexer/1.0"})
        
        retry_strategy = Retry(
            total=1,
            backoff_factor=0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            connect=0,
            read=0,
            redirect=0,
            status=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        proxy_dict = get_proxy_dict()
        if proxy_dict:
            session.proxies.update(proxy_dict)
        
        for source in _TRACKER_SOURCES:
            try:
                resp = session.get(source, timeout=(5, 15))
                resp.raise_for_status()
                trackers = [
                    tracker
                    for tracker in (line.strip() for line in resp.text.splitlines())
                    if tracker and _normalize_tracker(tracker)
                ]
                if trackers:
                    now = time.time()
                    should_log = False
                    with _logged_sources_lock:
                        last_logged = _logged_sources.get(source, 0)
                        if now - last_logged >= _LOG_COOLDOWN:
                            _logged_sources[source] = now
                            should_log = True
                            if len(_logged_sources) > 10:
                                oldest_key = min(_logged_sources.items(), key=lambda x: x[1])[0]
                                _logged_sources.pop(oldest_key, None)
                    
                    _record_success()
                    return trackers
            except requests.exceptions.Timeout:
                _record_timeout()
                logger.debug("Timeout: %s", source)
            except requests.exceptions.ReadTimeout:
                _record_timeout()
                logger.debug("Read timeout: %s", source)
            except requests.exceptions.ConnectionError as exc:
                error_msg = str(exc)
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(source)
                    host = parsed.netloc or parsed.path.split('/')[0] if parsed.path else source
                except Exception:
                    host = source.split('/')[2] if '/' in source and len(source.split('/')) > 2 else source
                
                if "Failed to resolve" in error_msg or "No address associated" in error_msg:
                    logger.debug("DNS error: %s (host: %s)", source, host)
                elif "Connection refused" in error_msg:
                    logger.debug("Connection refused: %s (host: %s)", source, host)
                else:
                    short_msg = error_msg.split('(')[0].strip() if '(' in error_msg else error_msg[:100]
                    logger.debug("Connection error: %s - %s", source, short_msg[:50])
            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if hasattr(exc, 'response') and exc.response else 'unknown'
                logger.debug("HTTP %s: %s", status_code, source)
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                error_msg = str(exc).split('\n')[0]
                logger.debug("Error: %s (%s) - %s", source, error_type, error_msg[:50])
        return None

    def _cache_trackers(self, trackers: List[str]) -> None:
        if self.redis:
            try:
                cache_key = tracker_list_key()
                encoded = json.dumps(trackers, separators=(',', ':')).encode("utf-8")
                self.redis.setex(
                    cache_key, 24 * 3600, encoded
                )
                return
            except Exception as exc:  # noqa: BLE001
                _log_redis_error("gravar lista de trackers", exc)
                return
        
        if not self.redis:
            with self._lock:
                self._memory_cache = list(trackers)
                self._memory_cache_expire_at = time.time() + 24 * 3600

