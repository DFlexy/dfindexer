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

# Cache em memória temporário por requisição (evita buscas duplicadas quando cache Redis está desligado)
_request_cache = threading.local()

_TRACKERS_LIST_CACHE_KEY = "dynamic_trackers_list"
_TRACKERS_LIST_TTL_SECONDS = 24 * 3600

# Cache para evitar logs duplicados de carregamento de trackers
_logged_sources = {}
_logged_sources_lock = threading.Lock()
_LOG_COOLDOWN = 60  # Só loga uma vez por minuto por source


# Verifica se o erro é de conexão com Redis (Redis desabilitado/indisponível)
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


# Loga erros do Redis de forma mais amigável
def _log_redis_error(operation: str, error: Exception) -> None:
    if _is_redis_connection_error(error):
        logger.debug(f"Redis indisponível - {operation} usando fallback em memória")
    else:
        logger.debug(f"Erro ao {operation} no Redis: {error}")

# Circuit breaker para evitar consultas quando há muitos timeouts
_CIRCUIT_BREAKER_KEY = "tracker:circuit_breaker"
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3  # Número de timeouts consecutivos antes de desabilitar
_CIRCUIT_BREAKER_DISABLE_DURATION = 60  # 1 minuto de desabilitação após muitos timeouts

_TRACKER_SOURCES = [
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best_ip.txt",
    "https://cdn.jsdelivr.net/gh/ngosang/trackerslist@master/trackers_best_ip.txt",
    "https://ngosang.github.io/trackerslist/trackers_best_ip.txt",
]


def _is_circuit_breaker_open() -> bool:
    """
    Verifica se o circuit breaker está aberto (desabilitado).
    Retorna True se deve evitar consultas por um período.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    # Se circuit breakers estão desabilitados via variável de ambiente, sempre retorna False
    from app.config import Config
    if not Config.CIRCUIT_BREAKER_ENABLED:
        return False
    
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
        try:
            disabled_until = redis.get(_CIRCUIT_BREAKER_KEY)
            if disabled_until:
                disabled_until_float = float(disabled_until)
                now = time.time()
                if now < disabled_until_float:
                    return True
                # Período expirou, limpa a chave
                redis.delete(_CIRCUIT_BREAKER_KEY)
        except Exception:
            pass
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0
        }
    
    if _request_cache.circuit_breaker['disabled']:
        logger.debug(f"Circuit breaker aberto na query atual - tracker desabilitado para esta requisição")
    
    return _request_cache.circuit_breaker['disabled']


def _record_timeout():
    """
    Registra um timeout e abre o circuit breaker se houver muitos timeouts consecutivos.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    # Se circuit breakers estão desabilitados via variável de ambiente, não registra nada
    from app.config import Config
    if not Config.CIRCUIT_BREAKER_ENABLED:
        return
    
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
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
            return
        except Exception as e:
            logger.debug(f"Erro ao registrar timeout: {e}")
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0
        }
    
    _request_cache.circuit_breaker['timeout_count'] += 1
    
    # Se atingiu o limite, abre o circuit breaker apenas para esta query
    if _request_cache.circuit_breaker['timeout_count'] >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(
            f"Circuit breaker aberto (query atual): {_request_cache.circuit_breaker['timeout_count']} timeouts consecutivos. "
            f"Tracker desabilitado para esta query"
        )


def _record_success():
    """
    Registra uma requisição bem-sucedida, resetando o contador de timeouts.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    # Se circuit breakers estão desabilitados via variável de ambiente, não registra nada
    from app.config import Config
    if not Config.CIRCUIT_BREAKER_ENABLED:
        return
    
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
        try:
            timeout_key = f"{_CIRCUIT_BREAKER_KEY}:timeouts"
            redis.delete(timeout_key)
        except Exception:
            pass
    
    # Fallback: reseta contadores por requisição (apenas durante a query atual)
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

    # Corrige traduções equivocadas presentes em alguns magnets
    url = url.replace("/anunciar", "/announce")
    url = url.replace("/anunc", "/announce")

    return url


# Fornece lista de trackers (dinâmica com fallback estático)
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
        # Se Redis está disponível, usa apenas Redis
        if self.redis:
            try:
                cached = self.redis.get(_TRACKERS_LIST_CACHE_KEY)
                if not cached:
                    return None
                trackers = json.loads(cached.decode("utf-8"))
                if not trackers:
                    return None
                logger.debug("Trackers recuperados do cache Redis.")
                return list(trackers)
            except Exception as exc:  # noqa: BLE001
                _log_redis_error("recuperar trackers do cache", exc)
                # Se Redis falhou durante operação, retorna None (não usa memória)
                return None
        
        # Usa memória apenas se Redis não está disponível desde o início
        if not self.redis:
            now = time.time()
            if now < self._memory_cache_expire_at and self._memory_cache:
                return list(self._memory_cache)
        
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
                    # Evita logs duplicados - só loga uma vez por minuto por source
                    now = time.time()
                    should_log = False
                    with _logged_sources_lock:
                        last_logged = _logged_sources.get(source, 0)
                        if now - last_logged >= _LOG_COOLDOWN:
                            _logged_sources[source] = now
                            should_log = True
                            # Limpa entradas antigas (mantém apenas últimas 10)
                            if len(_logged_sources) > 10:
                                oldest_key = min(_logged_sources.items(), key=lambda x: x[1])[0]
                                _logged_sources.pop(oldest_key, None)
                    
                    if should_log:
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
                logger.debug(
                    "Timeout ao obter trackers de %s", source
                )
            except requests.exceptions.ReadTimeout:
                # Read timeout detectado - registra e continua para próxima fonte
                _record_timeout()
                logger.debug(
                    "Read timeout ao obter trackers de %s", source
                )
            except requests.exceptions.ConnectionError as exc:
                # Erro de conexão (DNS, rede, etc.)
                error_msg = str(exc)
                # Extrai hostname da URL
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(source)
                    host = parsed.netloc or parsed.path.split('/')[0] if parsed.path else source
                except Exception:
                    host = source.split('/')[2] if '/' in source and len(source.split('/')) > 2 else source
                
                # Detecta tipo específico de erro
                if "Failed to resolve" in error_msg or "No address associated" in error_msg:
                    # Erro de DNS - não consegue resolver o hostname
                    logger.debug(
                        "Erro de DNS ao obter trackers de %s (host: %s)", source, host
                    )
                elif "Connection refused" in error_msg:
                    logger.debug(
                        "Conexão recusada ao obter trackers de %s (host: %s)", source, host
                    )
                else:
                    # Outros erros de conexão - mostra mensagem resumida
                    short_msg = error_msg.split('(')[0].strip() if '(' in error_msg else error_msg[:100]
                    logger.debug(
                        "Erro de conexão ao obter trackers de %s: %s", source, short_msg
                    )
            except requests.exceptions.HTTPError as exc:
                # Erro HTTP (404, 500, etc.)
                status_code = exc.response.status_code if hasattr(exc, 'response') and exc.response else 'unknown'
                logger.debug(
                    "Erro HTTP %s ao obter trackers de %s", status_code, source
                )
            except Exception as exc:  # noqa: BLE001
                # Outros erros - mostra apenas mensagem principal
                error_type = type(exc).__name__
                error_msg = str(exc).split('\n')[0]  # Pega apenas primeira linha
                logger.debug(
                    "Falha ao obter trackers de %s (%s): %s", source, error_type, error_msg
                )
        return None

    def _cache_trackers(self, trackers: List[str]) -> None:
        # Se Redis está disponível, salva apenas no Redis
        if self.redis:
            try:
                encoded = json.dumps(trackers).encode("utf-8")
                self.redis.setex(
                    _TRACKERS_LIST_CACHE_KEY, _TRACKERS_LIST_TTL_SECONDS, encoded
                )
                return
            except Exception as exc:  # noqa: BLE001
                _log_redis_error("gravar lista de trackers", exc)
                # Se Redis falhou durante operação, não salva em memória
                return
        
        # Salva em memória apenas se Redis não está disponível desde o início
        if not self.redis:
            with self._lock:
                self._memory_cache = list(trackers)
                self._memory_cache_expire_at = time.time() + _TRACKERS_LIST_TTL_SECONDS


