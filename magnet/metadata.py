"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

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
_rate_limiter_min_interval = 0.15  # Otimizado para 0.15s (~6-7 requisições/segundo) - reduzido de 0.5s
_rate_limiter_burst_tokens = 10  # Aumentado de 4 para 10 tokens para permitir rajadas maiores
_CIRCUIT_BREAKER_KEY = circuit_metadata_key()
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3
_CIRCUIT_BREAKER_503_THRESHOLD = 5
_CIRCUIT_BREAKER_DISABLE_DURATION = 60
_CIRCUIT_BREAKER_FAILURE_CACHE_TTL = 60
_CIRCUIT_BREAKER_503_CACHE_TTL = 300
_hash_locks = {}
_hash_locks_lock = threading.Lock()
# Rastreia hashes que estão sendo buscados para evitar logs duplicados
_hash_fetching = set()
_hash_fetching_lock = threading.Lock()


def _is_redis_connection_error(error: Exception) -> bool:
    """
    Verifica se o erro é de conexão com Redis (Redis desabilitado/indisponível).
    Retorna True se for erro de conexão, False caso contrário.
    """
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
    """
    Loga erros do Redis de forma mais amigável.
    Se for erro de conexão (Redis desabilitado), mostra mensagem informativa.
    Se for outro erro, mostra detalhes técnicos apenas em DEBUG.
    
    Args:
        operation: Descrição da operação que falhou (ex: "verificar circuit breaker")
        error: Exceção capturada
        log_once: Se True, só loga uma vez por operação (evita spam)
    """
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
    """
    Verifica se o circuit breaker está aberto (desabilitado).
    Retorna True se deve evitar consultas por um período.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
        try:
            disabled_until_str = redis.hget(_CIRCUIT_BREAKER_KEY, 'disabled')
            if disabled_until_str:
                disabled_until_float = float(disabled_until_str)
                now = time.time()
                if now < disabled_until_float:
                    remaining = int(disabled_until_float - now)
                    # Throttling de logs - só loga uma vez por minuto
                    log_key = "circuit_breaker_open"
                    should_log = False
                    with _circuit_breaker_log_lock:
                        last_logged = _circuit_breaker_log_cache.get(log_key, 0)
                        if now - last_logged >= _CIRCUIT_BREAKER_LOG_COOLDOWN:
                            _circuit_breaker_log_cache[log_key] = now
                            should_log = True
                    
                    return True
                # Período expirou, limpa o campo
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'disabled')
        except Exception as e:
            _log_redis_error("verificar circuit breaker", e)
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
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
    """
    Registra um timeout e abre o circuit breaker se houver muitos timeouts consecutivos.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
        try:
            # Usa Redis Hash para armazenar contadores
            timeout_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, 'timeouts', 1)
            redis.expire(_CIRCUIT_BREAKER_KEY, 60)  # Expira hash após 1 minuto
            
            # Se atingiu o limite, abre o circuit breaker
            if timeout_count >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {timeout_count} timeouts consecutivos. "
                    f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                # Reseta contador
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
            return
        except Exception as e:
            _log_redis_error("registrar timeout", e)
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0,
            '503_count': 0
        }
    
    _request_cache.circuit_breaker['timeout_count'] += 1
    
    # Se atingiu o limite, abre o circuit breaker apenas para esta query
    if _request_cache.circuit_breaker['timeout_count'] >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(f"Circuit breaker: {_request_cache.circuit_breaker['timeout_count']} timeouts (query atual)")


def _record_503():
    """
    Registra um erro 503 e abre o circuit breaker se houver muitos 503s consecutivos.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
        try:
            # Usa Redis Hash para armazenar contadores
            error_503_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, '503s', 1)
            redis.expire(_CIRCUIT_BREAKER_KEY, 60)  # Expira hash após 1 minuto
            
            # Se atingiu o limite, abre o circuit breaker
            if error_503_count >= _CIRCUIT_BREAKER_503_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {error_503_count} erros 503 consecutivos. "
                    f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                # Reseta contador
                redis.hdel(_CIRCUIT_BREAKER_KEY, '503s')
            return
        except Exception as e:
            _log_redis_error("registrar 503", e)
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0,
            '503_count': 0
        }
    
    _request_cache.circuit_breaker['503_count'] += 1
    
    # Se atingiu o limite, abre o circuit breaker apenas para esta query
    if _request_cache.circuit_breaker['503_count'] >= _CIRCUIT_BREAKER_503_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(f"Circuit breaker: {_request_cache.circuit_breaker['503_count']} erros 503 (query atual)")


def _record_success():
    """
    Registra uma requisição bem-sucedida, resetando os contadores de erros.
    Usa Redis se disponível (global), senão usa cache por requisição (apenas durante a query).
    """
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (circuit breaker global)
    if redis:
        try:
            # Reseta contadores no Hash
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts', '503s')
        except Exception:
            pass
    
    # Fallback: reseta contadores por requisição (apenas durante a query atual)
    if hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker['timeout_count'] = 0
        _request_cache.circuit_breaker['503_count'] = 0
        _request_cache.circuit_breaker['disabled'] = False


def _is_failure_cached(info_hash: str) -> bool:
    """
    Verifica se uma falha recente está em cache para evitar tentativas repetidas.
    Usa Redis primeiro, memória apenas se Redis não disponível.
    """
    info_hash_lower = info_hash.lower()
    
    try:
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        return metadata_cache.is_failure_cached(info_hash_lower)
    except Exception:
        return False


def _cache_failure(info_hash: str, is_503: bool = False):
    """
    Cacheia uma falha para evitar tentativas repetidas.
    Usa Redis primeiro, memória apenas se Redis não disponível.
    
    Args:
        info_hash: Hash do torrent
        is_503: Se True, cacheia por mais tempo (5 minutos) no Redis, pois é erro de serviço indisponível
    """
    info_hash_lower = info_hash.lower()
    
    try:
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        if is_503:
            # Erros 503 são cacheados por mais tempo
            metadata_cache.set_failure(info_hash_lower, _CIRCUIT_BREAKER_503_CACHE_TTL)
        else:
            metadata_cache.set_failure(info_hash_lower, _CIRCUIT_BREAKER_FAILURE_CACHE_TTL)
    except Exception:
        pass


def _get_hash_lock(info_hash: str):
    """
    Obtém um lock específico para um hash, evitando requisições simultâneas.
    """
    info_hash_lower = info_hash.lower()
    with _hash_locks_lock:
        if info_hash_lower not in _hash_locks:
            _hash_locks[info_hash_lower] = threading.Lock()
        return _hash_locks[info_hash_lower]


def _parse_bencode_size(data: bytes) -> Optional[int]:
    """
    Parseia bencode parcial para extrair tamanho do torrent.
    Procura por 'length' no campo 'info'.
    """
    try:
        # Procura por padrão "length" seguido de número
        # Formato bencode: "6:length" seguido de "i123456e" (número)
        pattern = rb'lengthi(\d+)e'
        match = re.search(pattern, data)
        if match:
            return int(match.group(1))
        
        # Tenta encontrar "length" e depois o número em formato bencode
        # Para single file: "6:lengthi{size}e"
        # Para multi-file: "5:filesl" seguido de múltiplos "d6:lengthi{size}e"
        length_patterns = [
            rb'6:lengthi(\d+)e',  # Single file
            rb'6:lengthi(\d+)e',   # Multi-file (cada arquivo)
        ]
        
        for pattern in length_patterns:
            matches = re.findall(pattern, data)
            if matches:
                # Se múltiplos matches, soma (multi-file)
                total = sum(int(m) for m in matches)
                if total > 0:
                    return total
        
        # Fallback: procura por números grandes que podem ser tamanhos
        # Procura por padrão "i" seguido de 6-15 dígitos seguido de "e"
        large_number_pattern = rb'i(\d{6,15})e'
        matches = re.findall(large_number_pattern, data)
        if matches:
            # Filtra números que podem ser tamanhos (entre 1MB e 1PB)
            sizes = []
            for num_str in matches:
                num = int(num_str)
                # Entre 1MB (1048576) e 1PB (1125899906842624)
                if 1048576 <= num <= 1125899906842624:
                    sizes.append(num)
            
            if sizes:
                # Se há múltiplos tamanhos válidos, pode ser multi-file
                # Retorna a soma (tamanho total)
                return sum(sizes)
        
        return None
    except Exception as e:
        logger.debug(f"Bencode parse error: {type(e).__name__}")
        return None


def _fetch_torrent_header(info_hash: str, use_lowercase: bool = False) -> Tuple[Optional[bytes], bool, bool]:
    """
    Baixa apenas o header do arquivo .torrent do iTorrents.
    Usa HTTP Range requests para baixar só o necessário (até 512KB).
    
    Returns:
        Tupla (dados, foi_timeout, foi_503): dados do torrent ou None, se houve timeout, e se foi 503
    """
    info_hash_hex = info_hash.lower() if use_lowercase else info_hash.upper()
    url = f"https://itorrents.org/torrent/{info_hash_hex}.torrent"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'TorrentMetadataService/1.0',
        'Accept-Encoding': 'gzip',
    })
    
    # Timeout otimizado para balancear velocidade e confiabilidade
    timeout_config = (3, 3)  # (connect_timeout, read_timeout) - aumentado de (2, 1.5) para reduzir timeouts
    
    # Tenta baixar chunks progressivamente até ter o header completo
    # Chunk inicial muito maior para reduzir drasticamente número de requisições HTTP
    chunk_size = 128 * 1024  # 128KB inicial (aumentado de 32KB) - menos requisições = mais rápido
    max_size = 512 * 1024   # 512KB máximo
    all_data = b''
    start = 0
    max_iterations = 8  # Reduzido de 10 para 8 (chunks maiores = menos iterações necessárias)
    iteration = 0
    
    # Rate limiting apenas uma vez no início (não a cada chunk)
    _rate_limit()
    
    try:
        while start < max_size and iteration < max_iterations:
            iteration += 1
            
            # Faz requisição com Range header
            headers = {'Range': f'bytes={start}-{start + chunk_size - 1}'}
            try:
                response = session.get(url, headers=headers, timeout=timeout_config)
            except requests.exceptions.Timeout:
                # Timeout detectado - registra mas NÃO cacheia falha (pode ser temporário)
                _record_timeout()
                return None, True, False
            except requests.exceptions.ReadTimeout:
                # Read timeout detectado - registra mas NÃO cacheia falha (pode ser temporário)
                _record_timeout()
                return None, True, False
            
            # Aceita 200 (full) ou 206 (partial)
            if response.status_code not in (200, 206):
                if response.status_code == 404:
                    # Torrent não encontrado - cacheia por tempo curto (1m) para evitar tentativas repetidas
                    _cache_failure(info_hash, is_503=False)
                    return None, False, False
                if response.status_code == 503:
                    # Service Unavailable - registra 503 e cacheia falha por mais tempo
                    _record_503()
                    _cache_failure(info_hash, is_503=True)
                    return None, False, True
                # Outros erros HTTP (500, 502, etc.) - cacheia por tempo curto
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError:
                    # Erro HTTP genérico - cacheia falha por tempo curto
                    _cache_failure(info_hash, is_503=False)
                    return None, False, False
            
            chunk = response.content
            if not chunk:
                break  # Fim do arquivo
            
            all_data += chunk
            
            # Se recebeu HTML (erro), para
            if b'<!DOCTYPE html' in all_data or b'<html' in all_data.lower():
                return None, False, False
            
            # Verifica se já tem o suficiente (procura por "pieces" que vem depois dos metadados)
            if b'pieces' in all_data:
                # Encontrou o campo "pieces", já tem metadados suficientes
                pieces_index = all_data.index(b'pieces')
                # Retorna até "pieces" + um pouco mais para garantir
                _record_success()  # Registra sucesso
                return all_data[:pieces_index + 20], False, False
            
            # Se recebeu menos que o chunk_size, chegou ao fim
            if len(chunk) < chunk_size:
                break
            
            # Próximo chunk - aumenta mais agressivamente
            start += len(chunk)
            chunk_size = min(chunk_size * 2, 256 * 1024)  # Aumenta chunk, máximo 256KB (aumentado de 128KB)
        
        if all_data:
            _record_success()  # Registra sucesso
        return (all_data if all_data else None), False, False
    
    except requests.exceptions.Timeout:
        # Timeout - registra mas NÃO cacheia falha (pode ser temporário)
        _record_timeout()
        return None, True, False
    except requests.exceptions.ReadTimeout:
        # Read timeout - registra mas NÃO cacheia falha (pode ser temporário)
        _record_timeout()
        return None, True, False
    except requests.exceptions.HTTPError as e:
        # Trata erros HTTP específicos
        if hasattr(e.response, 'status_code') and e.response.status_code == 503:
            _record_503()
            _cache_failure(info_hash, is_503=True)
            return None, False, True
        elif hasattr(e.response, 'status_code') and e.response.status_code == 404:
            # 404 - torrent não encontrado, cacheia por tempo curto
            _cache_failure(info_hash, is_503=False)
            return None, False, False
        else:
            # Outros erros HTTP - cacheia por tempo curto
            _cache_failure(info_hash, is_503=False)
            return None, False, False
    except requests.exceptions.ConnectionError:
        # Erro de conexão (DNS, rede, etc.) - não cacheia falha, pode ser temporário
        return None, False, False
    except requests.exceptions.RequestException:
        # Outros erros de requisição - não cacheia falha, pode ser temporário
        return None, False, False
    except Exception:
        # Erro inesperado - não cacheia falha
        return None, False, False


def fetch_metadata_from_itorrents(info_hash: str, scraper_name: Optional[str] = None, title: Optional[str] = None) -> Optional[Dict[str, any]]:
    """
    Busca metadados do torrent via iTorrents.org.
    
    Args:
        info_hash: Info hash do torrent (hex, 40 caracteres)
        scraper_name: Nome do scraper (opcional, para logs)
        title: Título do torrent (opcional, para logs)
        
    Returns:
        Dict com metadados extraídos:
        - 'size' (int): Tamanho total em bytes (obrigatório)
        - 'name' (str, opcional): Nome do torrent
        - 'creation_date' (int, opcional): Timestamp Unix da criação do torrent
        
        Retorna None se não conseguir extrair pelo menos o tamanho.
    """
    info_hash_lower = info_hash.lower()
    
    redis = get_redis_client()
    
    # Usa lock por hash para evitar requisições simultâneas ao mesmo hash
    hash_lock = _get_hash_lock(info_hash)
    with hash_lock:
        # Verifica cache primeiro (dentro do lock para evitar verificações duplicadas)
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            data = metadata_cache.get(info_hash_lower)
            if data:
                return data
        except Exception as e:
            _log_redis_error("verificar cache de metadata", e)
        
        # Verifica circuit breaker
        if _is_circuit_breaker_open():
            # Throttling de logs - só loga uma vez a cada 30 segundos
            now = time.time()
            log_key = "circuit_breaker_skip_metadata"
            should_log = False
            with _circuit_breaker_log_lock:
                last_logged = _circuit_breaker_log_cache.get(log_key, 0)
                if now - last_logged >= _CIRCUIT_BREAKER_LOG_COOLDOWN:
                    _circuit_breaker_log_cache[log_key] = now
                    should_log = True
            
            return None
        
        # Verifica se há falha recente em cache
        if _is_failure_cached(info_hash):
            # Throttling de logs - só loga uma vez a cada 60 segundos por hash
            now = time.time()
            log_key = f"cache_failure_{info_hash_lower}"
            should_log = False
            with _cache_failure_log_lock:
                last_logged = _cache_failure_log_cache.get(log_key, 0)
                if now - last_logged >= _CACHE_FAILURE_LOG_COOLDOWN:
                    _cache_failure_log_cache[log_key] = now
                    should_log = True
            
            return None
        
        # Verifica se já está sendo buscado por outra thread (evita logs duplicados)
        # Usa verificação atômica: verifica e adiciona em uma única operação
        will_fetch = False
        with _hash_fetching_lock:
            if info_hash_lower not in _hash_fetching:
                _hash_fetching.add(info_hash_lower)
                will_fetch = True  # Esta thread será a responsável pela busca
        
        # Se já está sendo buscado, espera um pouco e verifica cache novamente
        if not will_fetch:
            import time
            # Espera até 2 segundos verificando cache periodicamente
            for _ in range(20):
                time.sleep(0.1)  # Espera 100ms
                try:
                    from cache.metadata_cache import MetadataCache
                    metadata_cache = MetadataCache()
                    data = metadata_cache.get(info_hash_lower)
                    if data:
                        # Outra thread já buscou e salvou no cache
                        return data
                except Exception:
                    pass
            # Se não encontrou após esperar, outra thread está buscando
            # Remove do conjunto e retorna None para evitar busca duplicada
            with _hash_fetching_lock:
                _hash_fetching.discard(info_hash_lower)
            return None
        
        # Busca do iTorrents (não estava em cache e esta thread será a responsável)
        # Log apenas quando realmente vai buscar (não está em cache e não está sendo buscado)
        # Monta identificação para o log
        log_parts = []
        if scraper_name:
            log_parts.append(f"[{scraper_name}]")
        if title:
            title_preview = title[:50] if len(title) > 50 else title
            log_parts.append(title_preview)
        # Sempre inclui o hash completo para identificação
        log_parts.append(f"(hash: {info_hash_lower})")
        log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash_lower}"
        
        try:
            # Tenta com lowercase primeiro (mais comum)
            torrent_data, was_timeout, was_503 = _fetch_torrent_header(info_hash, use_lowercase=True)
            
            # Se falhou mas não foi timeout nem 503, tenta com uppercase (menos comum)
            # Se foi timeout ou 503, não tenta novamente para evitar esperas longas
            if not torrent_data and not was_timeout and not was_503:
                torrent_data, was_timeout, was_503 = _fetch_torrent_header(info_hash, use_lowercase=False)
            
            if not torrent_data:
                # Timeouts não devem cachear falha - podem ser temporários (rede lenta, servidor ocupado)
                # Apenas cacheia se foi erro HTTP específico (já foi cacheado dentro de _fetch_torrent_header)
                # Logs de erro removidos para reduzir verbosidade
                # Remove do conjunto de hashes sendo buscados mesmo em caso de falha
                logger.debug(f"[Metadata] Buscando metadata: {log_id} → Não encontrado")
                with _hash_fetching_lock:
                    _hash_fetching.discard(info_hash_lower)
                return None
        except Exception as e:
            # Em caso de erro, remove do conjunto
            with _hash_fetching_lock:
                _hash_fetching.discard(info_hash_lower)
            raise
        
        # Extrai tamanho do bencode
        size = _parse_bencode_size(torrent_data)
        
        if not size:
            logger.debug(f"[Metadata] Buscando metadata: {log_id} → Não encontrado (sem size)")
            with _hash_fetching_lock:
                _hash_fetching.discard(info_hash_lower)
            return None
        
        # Tenta extrair nome também (opcional)
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
                    # Log removido - nome será usado apenas internamente
        except Exception:
            pass
        
        result = {'size': size}
        if name:
            result['name'] = name
        
        # Tenta extrair data de criação (opcional) - para usar como date
        try:
            # Formato: "13:creation date" seguido de "i{timestamp}e"
            creation_date_pattern = rb'13:creation datei(\d+)e'
            creation_match = re.search(creation_date_pattern, torrent_data)
            if creation_match:
                timestamp = int(creation_match.group(1))
                # Timestamps válidos estão entre 2000 e 2100
                if 946684800 <= timestamp <= 4102444800:  # 2000-01-01 a 2100-01-01
                    result['creation_date'] = timestamp
        except Exception:
            pass
        
        # Tenta extrair campos customizados que possam conter IMDB
        # Alguns trackers adicionam campos como "imdb", "imdb_id", "imdb-id", etc.
        try:
            # Padrões comuns para campos IMDB no bencode
            imdb_patterns = [
                rb'4:imdb(\d+):',           # Campo "imdb"
                rb'7:imdb_id(\d+):',       # Campo "imdb_id"
                rb'8:imdb-id(\d+):',       # Campo "imdb-id"
                rb'9:imdb\.com(\d+):',     # Campo "imdb.com"
            ]
            
            for pattern in imdb_patterns:
                imdb_match = re.search(pattern, torrent_data)
                if imdb_match:
                    imdb_len = int(imdb_match.group(1))
                    start_pos = imdb_match.end()
                    if start_pos + imdb_len <= len(torrent_data):
                        imdb_bytes = torrent_data[start_pos:start_pos + imdb_len]
                        imdb_value = imdb_bytes.decode('utf-8', errors='ignore').strip()
                        # Verifica se é um formato válido de IMDB ID (tt1234567)
                        if re.match(r'^tt\d+$', imdb_value):
                            result['imdb'] = imdb_value
                            break
                        # Ou pode ser uma URL completa, extrai o ID
                        url_match = re.search(r'imdb\.com/title/(tt\d+)', imdb_value)
                        if url_match:
                            result['imdb'] = url_match.group(1)
                            break
        except Exception:
            pass
        
        # Cacheia resultado (Redis primeiro, memória apenas se Redis não disponível)
        saved_to_redis = False
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            metadata_cache.set(info_hash_lower, result)
            saved_to_redis = True
        except Exception:
            pass
        
        # Log com resultado da busca e salvamento
        if saved_to_redis:
            logger.debug(f"[Metadata] Buscando metadata: {log_id} → Salvo no Redis")
        else:
            logger.debug(f"[Metadata] Buscando metadata: {log_id} → Encontrado (não salvo no Redis)")
        
        # Remove do conjunto de hashes sendo buscados após salvar no cache com sucesso
        with _hash_fetching_lock:
            _hash_fetching.discard(info_hash_lower)
        
        return result


def get_torrent_size(magnet_link: str, info_hash: Optional[str] = None) -> Optional[str]:
    """
    Obtém tamanho do torrent em formato legível (ex: "1.5 GB").
    
    Args:
        magnet_link: Link magnet completo
        info_hash: Info hash (opcional, será extraído do magnet se não fornecido)
        
    Returns:
        String com tamanho formatado (ex: "1.5 GB") ou None
    """
    from magnet.parser import MagnetParser
    from utils.text.utils import format_bytes
    
    try:
        # Extrai info_hash do magnet se não fornecido
        if not info_hash:
            parsed = MagnetParser.parse(magnet_link)
            info_hash = parsed['info_hash']
        
        # Busca metadados
        metadata = fetch_metadata_from_itorrents(info_hash)
        if not metadata or 'size' not in metadata:
            return None
        
        # Formata tamanho
        size_bytes = metadata['size']
        return format_bytes(size_bytes)
    
    except Exception as e:
        logger.debug(f"Torrent size error: {type(e).__name__}")
        return None

