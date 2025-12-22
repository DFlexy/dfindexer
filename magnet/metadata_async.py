"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import re
import time
import asyncio
from typing import Dict, Optional, Tuple
from urllib.parse import unquote
import aiohttp
from cache.redis_client import get_redis_client
from cache.redis_keys import metadata_key, metadata_failure_key, metadata_failure503_key, circuit_metadata_key
from app.config import Config
from utils.concurrency.metadata_semaphore_async import metadata_slot_async

logger = logging.getLogger(__name__)

# Rate limiter async
_rate_limiter_lock = asyncio.Lock()
_rate_limiter_last_request = 0.0
_rate_limiter_min_interval = 0.5
_rate_limiter_burst_tokens = 4
_CIRCUIT_BREAKER_KEY = circuit_metadata_key()
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3
_CIRCUIT_BREAKER_503_THRESHOLD = 5
_CIRCUIT_BREAKER_DISABLE_DURATION = 60
_CIRCUIT_BREAKER_COUNTER_TTL = 60  # TTL para contadores do circuit breaker (timeouts, 503s)
# TTLs para cache de falha por hash (não são do circuit breaker, são do cache de falha)
_METADATA_FAILURE_CACHE_TTL = 60  # TTL para cache de falhas genéricas por hash
_METADATA_503_CACHE_TTL = 300  # TTL para cache de falhas 503 por hash
_METADATA_NOT_FOUND_CACHE_TTL = 120  # TTL para cache de "não encontrado" por hash
_hash_locks = {}
_hash_locks_lock = asyncio.Lock()

# Circuit breaker log cache
_circuit_breaker_log_cache = {}
_circuit_breaker_log_lock = asyncio.Lock()
_CIRCUIT_BREAKER_LOG_COOLDOWN = 30
_cache_failure_log_cache = {}
_cache_failure_log_lock = asyncio.Lock()
_CACHE_FAILURE_LOG_COOLDOWN = 60


def _is_redis_connection_error(error: Exception) -> bool:
    """Verifica se o erro é de conexão com Redis."""
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


async def _rate_limit():
    """Rate limiting async."""
    global _rate_limiter_last_request, _rate_limiter_burst_tokens
    
    async with _rate_limiter_lock:
        now = time.time()
        elapsed = now - _rate_limiter_last_request
        
        if elapsed >= _rate_limiter_min_interval:
            tokens_to_add = int(elapsed / _rate_limiter_min_interval)
            _rate_limiter_burst_tokens = min(4, _rate_limiter_burst_tokens + tokens_to_add)
        
        if _rate_limiter_burst_tokens <= 0:
            wait_time = _rate_limiter_min_interval - elapsed
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                now = time.time()
                elapsed = now - _rate_limiter_last_request
                if elapsed >= _rate_limiter_min_interval:
                    tokens_to_add = int(elapsed / _rate_limiter_min_interval)
                    _rate_limiter_burst_tokens = min(4, tokens_to_add)
        
        _rate_limiter_burst_tokens -= 1
        _rate_limiter_last_request = now


async def _is_circuit_breaker_open() -> bool:
    """Verifica se o circuit breaker está aberto (async)."""
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
    
    return False


async def _record_timeout():
    """Registra um timeout (async)."""
    redis = get_redis_client()
    
    if redis:
        try:
            timeout_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, 'timeouts', 1)
            # Expira hash com TTL do contador (garante que não expire antes do disabled)
            redis.expire(_CIRCUIT_BREAKER_KEY, max(_CIRCUIT_BREAKER_COUNTER_TTL, _CIRCUIT_BREAKER_DISABLE_DURATION))
            
            if timeout_count >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                # Expira hash com duração do disable (garante que disabled não expire antes do tempo)
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {timeout_count} timeouts consecutivos. "
                    f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
        except Exception:
            pass


async def _record_503():
    """Registra um erro 503 (async)."""
    redis = get_redis_client()
    
    if redis:
        try:
            error_503_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, '503s', 1)
            # Expira hash com TTL do contador (garante que não expire antes do disabled)
            redis.expire(_CIRCUIT_BREAKER_KEY, max(_CIRCUIT_BREAKER_COUNTER_TTL, _CIRCUIT_BREAKER_DISABLE_DURATION))
            
            if error_503_count >= _CIRCUIT_BREAKER_503_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                # Expira hash com duração do disable (garante que disabled não expire antes do tempo)
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {error_503_count} erros 503 consecutivos. "
                    f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                redis.hdel(_CIRCUIT_BREAKER_KEY, '503s')
        except Exception:
            pass


async def _record_success():
    """
    Registra uma requisição bem-sucedida, resetando os contadores de erros (async).
    Se o circuit breaker estiver aberto, fecha (half-open state).
    """
    redis = get_redis_client()
    
    if redis:
        try:
            # Reseta contadores no Hash
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts', '503s')
            # Fecha circuit breaker se estiver aberto (half-open state - permite tentar novamente)
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'disabled')
        except Exception:
            pass


async def _is_failure_cached(info_hash: str) -> bool:
    """Verifica se uma falha recente está em cache (async)."""
    info_hash_lower = info_hash.lower()
    
    try:
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        return metadata_cache.is_failure_cached(info_hash_lower)
    except Exception:
        return False


async def _cache_failure(info_hash: str, is_503: bool = False, ttl: Optional[int] = None):
    """
    Cacheia uma falha para evitar tentativas repetidas (async).
    Parte do sistema de circuit breaker.
    
    Args:
        info_hash: Hash do torrent
        is_503: Se True, cacheia por mais tempo (5 minutos) no Redis, pois é erro de serviço indisponível
        ttl: TTL customizado (opcional). Se não fornecido, usa TTL padrão baseado em is_503
    """
    info_hash_lower = info_hash.lower()
    
    try:
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        if ttl is not None:
            # TTL customizado (ex: para "não encontrado" - 2 minutos)
            metadata_cache.set_failure(info_hash_lower, ttl)
        elif is_503:
            # Erros 503 são cacheados por mais tempo
            metadata_cache.set_failure(info_hash_lower, _METADATA_503_CACHE_TTL)
        else:
            metadata_cache.set_failure(info_hash_lower, _METADATA_FAILURE_CACHE_TTL)
    except Exception:
        pass


async def _get_hash_lock(info_hash: str):
    """Obtém um lock específico para um hash (async)."""
    info_hash_lower = info_hash.lower()
    async with _hash_locks_lock:
        if info_hash_lower not in _hash_locks:
            _hash_locks[info_hash_lower] = asyncio.Lock()
        return _hash_locks[info_hash_lower]


def _parse_bencode_size(data: bytes) -> Optional[int]:
    """Parseia bencode parcial para extrair tamanho do torrent."""
    try:
        pattern = rb'lengthi(\d+)e'
        match = re.search(pattern, data)
        if match:
            return int(match.group(1))
        
        length_patterns = [
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
    except Exception:
        return None


async def _fetch_torrent_header_async(
    session: aiohttp.ClientSession,
    info_hash: str,
    use_lowercase: bool = False
) -> Tuple[Optional[bytes], bool, bool]:
    """
    Baixa apenas o header do arquivo .torrent do iTorrents (async).
    
    Returns:
        Tupla (dados, foi_timeout, foi_503)
    """
    info_hash_hex = info_hash.lower() if use_lowercase else info_hash.upper()
    url = f"https://itorrents.org/torrent/{info_hash_hex}.torrent"
    
    timeout = aiohttp.ClientTimeout(total=3.5, connect=2, sock_read=1.5)
    chunk_size = 128 * 1024
    max_size = 512 * 1024
    all_data = b''
    start = 0
    max_iterations = 8
    iteration = 0
    
    await _rate_limit()
    
    try:
        while start < max_size and iteration < max_iterations:
            iteration += 1
            
            headers = {'Range': f'bytes={start}-{start + chunk_size - 1}'}
            async with session.get(url, headers=headers, timeout=timeout) as response:
                if response.status not in (200, 206):
                    if response.status == 404:
                        await _cache_failure(info_hash, is_503=False)
                        return None, False, False
                    if response.status == 503:
                        await _record_503()
                        await _cache_failure(info_hash, is_503=True)
                        return None, False, True
                    return None, False, False
                
                chunk = await response.read()
                if not chunk:
                    break
                
                all_data += chunk
                
                if b'<!DOCTYPE html' in all_data or b'<html' in all_data.lower():
                    return None, False, False
                
                if b'pieces' in all_data:
                    pieces_index = all_data.index(b'pieces')
                    await _record_success()
                    return all_data[:pieces_index + 20], False, False
                
                if len(chunk) < chunk_size:
                    break
                
                start += len(chunk)
                chunk_size = min(chunk_size * 2, 256 * 1024)
        
        if all_data:
            await _record_success()
        return (all_data if all_data else None), False, False
    
    except asyncio.TimeoutError:
        await _record_timeout()
        return None, True, False
    except aiohttp.ClientResponseError as e:
        if e.status == 503:
            await _record_503()
            await _cache_failure(info_hash, is_503=True)
            return None, False, True
        elif e.status == 404:
            await _cache_failure(info_hash, is_503=False)
            return None, False, False
        else:
            await _cache_failure(info_hash, is_503=False)
            return None, False, False
    except Exception:
        return None, False, False


async def fetch_metadata_from_itorrents_async(
    session: aiohttp.ClientSession,
    info_hash: str,
    scraper_name: Optional[str] = None,
    title: Optional[str] = None
) -> Optional[Dict[str, any]]:
    """
    Busca metadados do torrent via iTorrents.org (async).
    
    Args:
        session: Sessão aiohttp para reutilização de conexões
        info_hash: Info hash do torrent (hex, 40 caracteres)
        
    Returns:
        Dict com metadados extraídos ou None
    """
    info_hash_lower = info_hash.lower()
    
    # Verifica cache primeiro
    try:
        from cache.metadata_cache import MetadataCache
        from utils.concurrency.metadata_semaphore_async import _cache_hits, _cache_misses, _cache_stats_lock
        metadata_cache = MetadataCache()
        data = metadata_cache.get(info_hash_lower)
        if data:
            # Incrementa contador de HIT para resumo no batch
            async with _cache_stats_lock:
                _cache_hits += 1
            return data
        # Incrementa contador de MISS para resumo no batch
        async with _cache_stats_lock:
            _cache_misses += 1
    except Exception:
        pass
    
    # Verifica circuit breaker
    if await _is_circuit_breaker_open():
        return None
    
    # Verifica se há falha recente em cache
    if await _is_failure_cached(info_hash):
        return None
    
    # Usa lock por hash para evitar requisições simultâneas
    hash_lock = await _get_hash_lock(info_hash)
    async with hash_lock:
        # Verifica cache novamente após adquirir lock
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            data = metadata_cache.get(info_hash_lower)
            if data:
                return data
        except Exception:
            pass
        
        # Busca do iTorrents
        # Monta identificação para o log
        log_parts = []
        if scraper_name:
            log_parts.append(f"[{scraper_name}]")
        if title:
            title_preview = title[:120] if len(title) > 120 else title
            log_parts.append(title_preview)
        if not log_parts:
            log_parts.append(info_hash_lower[:16])
        log_id = " ".join(log_parts) if log_parts else info_hash_lower[:16]
        logger.debug(f"[Metadata Async] Buscando metadata: {log_id}...")
        torrent_data, was_timeout, was_503 = await _fetch_torrent_header_async(
            session, info_hash, use_lowercase=True
        )
        
        if not torrent_data and not was_timeout and not was_503:
            torrent_data, was_timeout, was_503 = await _fetch_torrent_header_async(
                session, info_hash, use_lowercase=False
            )
        
        if not torrent_data:
            # Torrent não encontrado - cacheia falha para evitar tentativas repetidas
            await _cache_failure(info_hash_lower, is_503=False, ttl=_METADATA_NOT_FOUND_CACHE_TTL)
            # Logs de erro removidos para reduzir verbosidade
            return None
        
        # Extrai tamanho do bencode
        size = _parse_bencode_size(torrent_data)
        
        if not size:
            # Tamanho não encontrado - cacheia falha para evitar tentativas repetidas
            await _cache_failure(info_hash_lower, is_503=False, ttl=_METADATA_NOT_FOUND_CACHE_TTL)
            return None
        
        # Tenta extrair nome
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
                    if name:
                        logger.debug(f"[Metadata Async] Buscando metadata: {name[:60]}...")
        except Exception:
            pass
        
        result = {'size': size}
        if name:
            result['name'] = name
        
        # Tenta extrair data de criação
        try:
            creation_date_pattern = rb'13:creation datei(\d+)e'
            creation_match = re.search(creation_date_pattern, torrent_data)
            if creation_match:
                timestamp = int(creation_match.group(1))
                if 946684800 <= timestamp <= 4102444800:
                    result['creation_date'] = timestamp
        except Exception:
            pass
        
        # Tenta extrair IMDB
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
        
        # Cacheia resultado
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            metadata_cache.set(info_hash_lower, result)
        except Exception:
            pass
        
        return result

