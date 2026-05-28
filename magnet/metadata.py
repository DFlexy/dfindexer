# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import re
import time
import threading
import json
from typing import Dict, Optional, Tuple, Any
from urllib.parse import unquote
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import metadata_key, metadata_failure_key, metadata_failure503_key, circuit_metadata_key
from app.config import Config

logger = logging.getLogger(__name__)

_request_cache = threading.local()
_rate_limiter_lock = threading.Lock()
_rate_limiter_last_request = 0.0
_rate_limiter_min_interval = 0.15
_rate_limiter_burst_tokens = 10
_CIRCUIT_BREAKER_KEY = circuit_metadata_key()
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3
_CIRCUIT_BREAKER_503_THRESHOLD = 5
_CIRCUIT_BREAKER_DISABLE_DURATION = 60
_CIRCUIT_BREAKER_COUNTER_TTL = 60
# TTL de falha por hash (fora do circuit breaker)
_METADATA_FAILURE_CACHE_TTL = 60
_METADATA_503_CACHE_TTL = 300
_METADATA_NOT_FOUND_CACHE_TTL = 120
_hash_locks = {}
_hash_locks_lock = threading.Lock()
_MAX_HASH_LOCKS = 500
_hash_fetching = set()
_hash_fetching_lock = threading.Lock()

_http_session = None
_http_session_lock = threading.Lock()

def _get_http_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        with _http_session_lock:
            if _http_session is None:
                s = requests.Session()
                s.headers.update({
                    'User-Agent': 'TorrentMetadataService/1.0',
                    'Accept-Encoding': 'gzip',
                })
                from utils.http.proxy import get_proxy_dict
                proxy_dict = get_proxy_dict()
                if proxy_dict:
                    s.proxies.update(proxy_dict)
                from requests.adapters import HTTPAdapter
                adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
                s.mount('https://', adapter)
                s.mount('http://', adapter)
                _http_session = s
    return _http_session

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

def _log_redis_error(operation: str, error: Exception, log_once: bool = True) -> None:
    if _is_redis_connection_error(error):
        logger.debug(f"Redis fallback: {operation}")
    else:
        logger.debug(f"Redis error: {operation}")

def _rate_limit():
    global _rate_limiter_last_request, _rate_limiter_burst_tokens
    
    with _rate_limiter_lock:
        now = time.time()
        elapsed = now - _rate_limiter_last_request
        
        if elapsed >= _rate_limiter_min_interval:
            tokens_to_add = int(elapsed / _rate_limiter_min_interval)
            _rate_limiter_burst_tokens = min(10, _rate_limiter_burst_tokens + tokens_to_add)
        
        if _rate_limiter_burst_tokens <= 0:
            wait_time = _rate_limiter_min_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
                elapsed = now - _rate_limiter_last_request
                if elapsed >= _rate_limiter_min_interval:
                    tokens_to_add = int(elapsed / _rate_limiter_min_interval)
                    _rate_limiter_burst_tokens = min(10, tokens_to_add)
        
        _rate_limiter_burst_tokens -= 1
        _rate_limiter_last_request = now

_circuit_breaker_log_cache = {}
_circuit_breaker_log_lock = threading.Lock()
_CIRCUIT_BREAKER_LOG_COOLDOWN = 30
_cache_failure_log_cache = {}
_cache_failure_log_lock = threading.Lock()
_CACHE_FAILURE_LOG_COOLDOWN = 60

def _is_circuit_breaker_open() -> bool:
    redis = get_redis_client()
    
    if redis:
        try:
            disabled_until_str = redis.hget(_CIRCUIT_BREAKER_KEY, 'disabled')
            if disabled_until_str:
                disabled_until_float = float(disabled_until_str)
                now = time.time()
                if now < disabled_until_float:
                    log_key = "circuit_breaker_open"
                    should_log = False
                    with _circuit_breaker_log_lock:
                        last_logged = _circuit_breaker_log_cache.get(log_key, 0)
                        if now - last_logged >= _CIRCUIT_BREAKER_LOG_COOLDOWN:
                            _circuit_breaker_log_cache[log_key] = now
                            should_log = True
                    
                    return True
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'disabled')
        except Exception as e:
            _log_redis_error("verificar circuit breaker", e)
    
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0,
            '503_count': 0
        }
    
    if _request_cache.circuit_breaker['disabled']:
        logger.debug("Circuit breaker: metadata desabilitado (query atual)")
    
    return _request_cache.circuit_breaker['disabled']

def _record_timeout():
    redis = get_redis_client()
    
    if redis:
        try:
            timeout_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, 'timeouts', 1)
            redis.expire(_CIRCUIT_BREAKER_KEY, max(_CIRCUIT_BREAKER_COUNTER_TTL, _CIRCUIT_BREAKER_DISABLE_DURATION))
            

            if timeout_count >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {timeout_count} timeouts consecutivos. "
                    f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
            return
        except Exception as e:
            _log_redis_error("registrar timeout", e)
    
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0,
            '503_count': 0
        }
    
    _request_cache.circuit_breaker['timeout_count'] += 1
    

    if _request_cache.circuit_breaker['timeout_count'] >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(f"Circuit breaker: {_request_cache.circuit_breaker['timeout_count']} timeouts (query atual)")

def _record_503():
    redis = get_redis_client()
    
    if redis:
        try:
            error_503_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, '503s', 1)
            redis.expire(_CIRCUIT_BREAKER_KEY, max(_CIRCUIT_BREAKER_COUNTER_TTL, _CIRCUIT_BREAKER_DISABLE_DURATION))
            

            if error_503_count >= _CIRCUIT_BREAKER_503_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {error_503_count} erros 503 consecutivos. "
                    f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                redis.hdel(_CIRCUIT_BREAKER_KEY, '503s')
            return
        except Exception as e:
            _log_redis_error("registrar 503", e)
    
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0,
            '503_count': 0
        }
    
    _request_cache.circuit_breaker['503_count'] += 1
    

    if _request_cache.circuit_breaker['503_count'] >= _CIRCUIT_BREAKER_503_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(f"Circuit breaker: {_request_cache.circuit_breaker['503_count']} erros 503 (query atual)")

def _record_success():
    """Registra uma requisição bem-sucedida, resetando os contadores de erros"""
    redis = get_redis_client()
    
    if redis:
        try:
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts', '503s')
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'disabled')
        except Exception:
            pass
    
    if hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker['timeout_count'] = 0
        _request_cache.circuit_breaker['503_count'] = 0
        _request_cache.circuit_breaker['disabled'] = False

def _is_failure_cached(info_hash: str) -> bool:
    """Verifica se uma falha recente está em cache para evitar tentativas repetidas"""
    info_hash_lower = info_hash.lower()
    
    try:
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        return metadata_cache.is_failure_cached(info_hash_lower)
    except Exception:
        return False

def _cache_failure(info_hash: str, is_503: bool = False, ttl: Optional[int] = None):
    info_hash_lower = info_hash.lower()
    
    try:
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        if ttl is not None:

            metadata_cache.set_failure(info_hash_lower, ttl)
        elif is_503:
            metadata_cache.set_failure(info_hash_lower, _METADATA_503_CACHE_TTL)
        else:
            metadata_cache.set_failure(info_hash_lower, _METADATA_FAILURE_CACHE_TTL)
    except Exception:
        pass

def _get_hash_lock(info_hash: str):
    info_hash_lower = info_hash.lower()
    with _hash_locks_lock:
        if len(_hash_locks) > _MAX_HASH_LOCKS:
            keys_to_remove = list(_hash_locks.keys())[:len(_hash_locks) // 2]
            for key in keys_to_remove:
                del _hash_locks[key]
        if info_hash_lower not in _hash_locks:
            _hash_locks[info_hash_lower] = threading.Lock()
        return _hash_locks[info_hash_lower]

def cleanup_metadata_state():
    """Limpa estado global de metadata (locks e fetching set). Chamar entre requisições."""
    with _hash_locks_lock:
        _hash_locks.clear()
    with _hash_fetching_lock:
        _hash_fetching.clear()
    with _cache_failure_log_lock:
        _cache_failure_log_cache.clear()
    with _circuit_breaker_log_lock:
        _circuit_breaker_log_cache.clear()

def _parse_bencode_size(data: bytes) -> Optional[int]:
    """Parseia bencode parcial para extrair tamanho do torrent"""
    try:
        pattern = rb'lengthi(\d+)e'
        match = re.search(pattern, data)
        if match:
            return int(match.group(1))
        
        length_patterns = [
            rb'6:lengthi(\d+)e',
            rb'6:lengthi(\d+)e',
        ]
        
        for pattern in length_patterns:
            matches = re.findall(pattern, data)
            if matches:
                total = sum(int(m) for m in matches)
                if total > 0:
                    return total
        
        large_number_pattern = rb'i(\d{6,15})e'
        matches = re.findall(large_number_pattern, data)
        if matches:
            sizes = []
            for num_str in matches:
                num = int(num_str)
                if 1048576 <= num <= 1125899906842624:
                    sizes.append(num)
            
            if sizes:
                return sum(sizes)
        
        return None
    except Exception as e:
        logger.debug(f"Bencode parse error: {type(e).__name__}")
        return None

def _fetch_torrent_header(info_hash: str, use_lowercase: bool = False) -> Tuple[Optional[bytes], bool, bool]:
    """Baixa header do .torrent do iTorrents em um único request (Range 0-512KB)"""
    info_hash_hex = info_hash.lower() if use_lowercase else info_hash.upper()
    url = f"https://itorrents.org/torrent/{info_hash_hex}.torrent"
    
    session = _get_http_session()
    timeout_config = (3, 4)
    max_bytes = 512 * 1024
    
    _rate_limit()
    
    try:
        headers = {'Range': f'bytes=0-{max_bytes - 1}'}
        response = session.get(url, headers=headers, timeout=timeout_config)
        
        if response.status_code == 404:
            _cache_failure(info_hash, is_503=False)
            return None, False, False
        if response.status_code == 503:
            _record_503()
            _cache_failure(info_hash, is_503=True)
            return None, False, True
        if response.status_code not in (200, 206):
            _cache_failure(info_hash, is_503=False)
            return None, False, False
        
        data = response.content
        if not data:
            return None, False, False
        
        if b'<!DOCTYPE html' in data or b'<html' in data.lower():
            return None, False, False
        
        _record_success()
        
        if b'pieces' in data:
            idx = data.index(b'pieces')
            return data[:idx + 20], False, False
        
        return data, False, False
    
    except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout):
        _record_timeout()
        return None, True, False
    except requests.exceptions.ConnectionError:
        return None, False, False
    except requests.exceptions.RequestException:
        return None, False, False
    except Exception:
        return None, False, False

def fetch_metadata_from_itorrents(info_hash: str, scraper_name: Optional[str] = None, title: Optional[str] = None) -> Optional[Dict[str, any]]:
    info_hash_lower = info_hash.lower()
    
    redis = get_redis_client()
    
    hash_lock = _get_hash_lock(info_hash)
    with hash_lock:
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            data = metadata_cache.get(info_hash_lower)
            if data:
                return data
        except Exception as e:
            _log_redis_error("verificar cache de metadata", e)
        
        if _is_circuit_breaker_open():
            now = time.time()
            log_key = "circuit_breaker_skip_metadata"
            should_log = False
            with _circuit_breaker_log_lock:
                last_logged = _circuit_breaker_log_cache.get(log_key, 0)
                if now - last_logged >= _CIRCUIT_BREAKER_LOG_COOLDOWN:
                    _circuit_breaker_log_cache[log_key] = now
                    should_log = True
            
            return None
        
        if _is_failure_cached(info_hash):
            now = time.time()
            log_key = f"cache_failure_{info_hash_lower}"
            should_log = False
            with _cache_failure_log_lock:
                last_logged = _cache_failure_log_cache.get(log_key, 0)
                if now - last_logged >= _CACHE_FAILURE_LOG_COOLDOWN:
                    _cache_failure_log_cache[log_key] = now
                    should_log = True
            
            return None
        
        will_fetch = False
        with _hash_fetching_lock:
            if info_hash_lower not in _hash_fetching:
                _hash_fetching.add(info_hash_lower)
                will_fetch = True
        
        if not will_fetch:
            import time
            for _ in range(20):
                time.sleep(0.1)
                try:
                    from cache.metadata_cache import MetadataCache
                    metadata_cache = MetadataCache()
                    data = metadata_cache.get(info_hash_lower)
                    if data:
                        return data
                except Exception:
                    pass
            with _hash_fetching_lock:
                _hash_fetching.discard(info_hash_lower)
            return None
        
        log_parts = []
        if scraper_name:
            log_parts.append(f"[{scraper_name}]")
        if title:
            title_preview = title[:120] if len(title) > 120 else title
            log_parts.append(title_preview)
        log_parts.append(f"(hash: {info_hash_lower})")
        log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash_lower}"
        
        try:
            torrent_data, was_timeout, was_503 = _fetch_torrent_header(info_hash, use_lowercase=True)
            
            if not torrent_data and not was_timeout and not was_503:
                torrent_data, was_timeout, was_503 = _fetch_torrent_header(info_hash, use_lowercase=False)
            
            if not torrent_data:

                _cache_failure(info_hash_lower, is_503=False, ttl=_METADATA_NOT_FOUND_CACHE_TTL)
                logger.debug(f"[Metadata] Buscando: {log_id} → Não encontrado")
                with _hash_fetching_lock:
                    _hash_fetching.discard(info_hash_lower)
                return None
        except Exception as e:
            with _hash_fetching_lock:
                _hash_fetching.discard(info_hash_lower)
            raise
        
        size = _parse_bencode_size(torrent_data)
        
        if not size:

            _cache_failure(info_hash_lower, is_503=False, ttl=_METADATA_NOT_FOUND_CACHE_TTL)
            logger.debug(f"[Metadata] Buscando: {log_id} → Não encontrado (sem size)")
            with _hash_fetching_lock:
                _hash_fetching.discard(info_hash_lower)
            return None
        
        name = None
        try:
            name_pattern = rb'4:name(\d+):'
            name_match = re.search(name_pattern, torrent_data)
            if name_match:
                name_len = int(name_match.group(1))
                start_pos = name_match.end()
                if start_pos + name_len <= len(torrent_data):
                    name_bytes = torrent_data[start_pos:start_pos + name_len]
                    name = name_bytes.decode('utf-8', errors='ignore')
        except Exception:
            pass
        
        result = {'size': size}
        if name:
            result['name'] = name
        
        try:
            creation_date_pattern = rb'13:creation datei(\d+)e'
            creation_match = re.search(creation_date_pattern, torrent_data)
            if creation_match:
                timestamp = int(creation_match.group(1))
                if 946684800 <= timestamp <= 4102444800:
                    result['creation_date'] = timestamp
        except Exception:
            pass
        
        try:
            imdb_patterns = [
                rb'4:imdb(\d+):',
                rb'7:imdb_id(\d+):',
                rb'8:imdb-id(\d+):',
                rb'9:imdb\.com(\d+):',
            ]
            
            for pattern in imdb_patterns:
                imdb_match = re.search(pattern, torrent_data)
                if imdb_match:
                    imdb_len = int(imdb_match.group(1))
                    start_pos = imdb_match.end()
                    if start_pos + imdb_len <= len(torrent_data):
                        imdb_bytes = torrent_data[start_pos:start_pos + imdb_len]
                        imdb_value = imdb_bytes.decode('utf-8', errors='ignore').strip()
                        if re.match(r'^tt\d+$', imdb_value):
                            result['imdb'] = imdb_value
                            break
                        url_match = re.search(r'imdb\.com/title/(tt\d+)', imdb_value)
                        if url_match:
                            result['imdb'] = url_match.group(1)
                            break
        except Exception:
            pass
        
        saved_to_redis = False
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            metadata_cache.set(info_hash_lower, result)
            saved_to_redis = True
        except Exception:
            pass
        
        if saved_to_redis:
            logger.debug(f"[Metadata] Buscando: {log_id} → Salvo no Redis")
        else:
            logger.debug(f"[Metadata] Buscando: {log_id} → Encontrado (não salvo no Redis)")
        
        with _hash_fetching_lock:
            _hash_fetching.discard(info_hash_lower)
        
        return result

def get_torrent_size(magnet_link: str, info_hash: Optional[str] = None) -> Optional[str]:
    """Obtém tamanho do torrent em formato legível (ex: "1.5 GB")"""
    from magnet.parser import MagnetParser
    from utils.text.utils import format_bytes
    
    try:
        if not info_hash:
            parsed = MagnetParser.parse(magnet_link)
            info_hash = parsed['info_hash']
        
        metadata = fetch_metadata_from_itorrents(info_hash)
        if not metadata or 'size' not in metadata:
            return None
        
        size_bytes = metadata['size']
        return format_bytes(size_bytes)
    
    except Exception as e:
        logger.debug(f"Torrent size error: {type(e).__name__}")
        return None

