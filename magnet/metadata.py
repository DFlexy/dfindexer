"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import re
import time
import threading
import json
from typing import Dict, Optional, Tuple
from urllib.parse import unquote
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import metadata_key, circuit_metadata_key
from app.config import Config

logger = logging.getLogger(__name__)

# Cache em memória temporário por requisição (evita buscas duplicadas quando cache Redis está desligado)
_request_cache = threading.local()

# Rate limiter simples (1 req/s com burst de 2) - reduzido para evitar sobrecarga
_rate_limiter_lock = threading.Lock()
_rate_limiter_last_request = 0.0
_rate_limiter_min_interval = 1.0  # 1 req/s = 1s entre requisições (mais conservador)
_rate_limiter_burst_tokens = 2  # Burst reduzido

# Circuit breaker para evitar consultas quando há muitos timeouts/503s
_CIRCUIT_BREAKER_KEY = circuit_metadata_key()
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3  # Número de timeouts consecutivos antes de desabilitar
_CIRCUIT_BREAKER_503_THRESHOLD = 5  # Número de 503s consecutivos antes de desabilitar
_CIRCUIT_BREAKER_DISABLE_DURATION = 60  # 1 minuto de desabilitação após muitos erros
_CIRCUIT_BREAKER_FAILURE_CACHE_TTL = 60  # Cache de falhas individuais por 1 minuto (Redis)
_CIRCUIT_BREAKER_503_CACHE_TTL = 300  # Cache de falhas 503 por 5 minutos (Redis)

# Lock por hash para evitar requisições simultâneas ao mesmo hash
_hash_locks = {}
_hash_locks_lock = threading.Lock()

# Circuit breaker em memória (fallback quando Redis não está disponível)
# Funciona apenas durante a query atual (via _request_cache)


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
        # Redis desabilitado/indisponível - mensagem informativa
        logger.debug(f"Redis indisponível - {operation} usando fallback em memória")
    else:
        # Outro tipo de erro - mostra detalhes técnicos
        logger.debug(f"Erro ao {operation} no Redis: {error}")


# Rate limiter simples para iTorrents - mais conservador para evitar 503
def _rate_limit():
    global _rate_limiter_last_request, _rate_limiter_burst_tokens
    
    with _rate_limiter_lock:
        now = time.time()
        elapsed = now - _rate_limiter_last_request
        
        # Recarrega tokens de burst (1 token a cada intervalo, máximo 2)
        if elapsed >= _rate_limiter_min_interval:
            tokens_to_add = int(elapsed / _rate_limiter_min_interval)
            _rate_limiter_burst_tokens = min(2, _rate_limiter_burst_tokens + tokens_to_add)
        
        # Se não tem tokens, espera
        if _rate_limiter_burst_tokens <= 0:
            wait_time = _rate_limiter_min_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
                elapsed = now - _rate_limiter_last_request
                # Recarrega após espera
                if elapsed >= _rate_limiter_min_interval:
                    tokens_to_add = int(elapsed / _rate_limiter_min_interval)
                    _rate_limiter_burst_tokens = min(2, tokens_to_add)
        
        _rate_limiter_burst_tokens -= 1
        _rate_limiter_last_request = now


# Cache para evitar logs duplicados de circuit breaker
_circuit_breaker_log_cache = {}
_circuit_breaker_log_lock = threading.Lock()
_CIRCUIT_BREAKER_LOG_COOLDOWN = 30  # Só loga uma vez a cada 30 segundos

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
                    
                    if should_log:
                        logger.debug(f"[CIRCUIT BREAKER] metadata desabilitado por mais {remaining}s")
                    return True
                # Período expirou, limpa o campo
                logger.debug("Circuit breaker expirou no Redis - reabilitando metadata")
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
        logger.debug(f"Circuit breaker aberto na query atual - metadata desabilitado para esta requisição")
    
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
        logger.debug(
            f"Circuit breaker aberto (query atual): {_request_cache.circuit_breaker['timeout_count']} timeouts consecutivos. "
            f"Metadata desabilitado para esta query"
        )


def _record_503():
    """
    Registra um erro 503 e abre o circuit breaker se houver muitos 503s consecutivos.
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
        logger.debug(
            f"Circuit breaker aberto (query atual): {_request_cache.circuit_breaker['503_count']} erros 503 consecutivos. "
            f"Metadata desabilitado para esta query"
        )


def _record_success():
    """
    Registra uma requisição bem-sucedida, resetando os contadores de erros.
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
    Usa Redis se disponível (TTL fixo), senão usa cache por requisição (apenas durante a query).
    """
    info_hash_lower = info_hash.lower()
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (cache persistente entre requisições)
    if redis:
        try:
            # Verifica campo failure no Hash do metadata
            key = metadata_key(info_hash_lower)
            failure_timestamp = redis.hget(key, 'failure')
            if failure_timestamp:
                # Verifica se ainda está dentro do TTL (60s para falhas normais, 300s para 503)
                failure_time = float(failure_timestamp)
                now = time.time()
                # Assume TTL de 60s (pode ser 300s para 503, mas não temos como distinguir)
                if now - failure_time < 300:  # Máximo TTL de 503
                    return True
        except Exception:
            pass
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
    # Isso evita tentativas repetidas na mesma requisição, mas permite tentar novamente em requisições futuras
    if not hasattr(_request_cache, 'failure_cache'):
        _request_cache.failure_cache = set()
    
    return info_hash_lower in _request_cache.failure_cache


def _cache_failure(info_hash: str, is_503: bool = False):
    """
    Cacheia uma falha para evitar tentativas repetidas.
    Usa Redis se disponível (TTL fixo), senão usa cache por requisição (apenas durante a query).
    
    Args:
        info_hash: Hash do torrent
        is_503: Se True, cacheia por mais tempo (5 minutos) no Redis, pois é erro de serviço indisponível
    """
    info_hash_lower = info_hash.lower()
    redis = get_redis_client()
    
    # Tenta usar Redis primeiro (cache persistente entre requisições)
    if redis:
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            if is_503:
                # Erros 503 são cacheados por mais tempo
                metadata_cache.set_failure(info_hash_lower, _CIRCUIT_BREAKER_503_CACHE_TTL)
            else:
                metadata_cache.set_failure(info_hash_lower, _CIRCUIT_BREAKER_FAILURE_CACHE_TTL)
            return
        except Exception:
            pass
    
    # Fallback: usa cache por requisição (apenas durante a query atual)
    # Isso evita tentativas repetidas na mesma requisição, mas permite tentar novamente em requisições futuras
    if not hasattr(_request_cache, 'failure_cache'):
        _request_cache.failure_cache = set()
    
    _request_cache.failure_cache.add(info_hash_lower)


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
        logger.debug(f"Erro ao parsear bencode: {e}")
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
    
    # Timeout reduzido para evitar esperas longas (5s connect + 3s read)
    timeout_config = (5, 3)  # (connect_timeout, read_timeout)
    
    # Tenta baixar chunks progressivamente até ter o header completo
    chunk_size = 6 * 1024  # 6KB inicial
    max_size = 512 * 1024   # 512KB máximo
    all_data = b''
    start = 0
    max_iterations = 20  # Limite de iterações para evitar loops infinitos
    iteration = 0
    
    try:
        while start < max_size and iteration < max_iterations:
            iteration += 1
            _rate_limit()  # Rate limiting
            
            # Faz requisição com Range header
            headers = {'Range': f'bytes={start}-{start + chunk_size - 1}'}
            try:
                response = session.get(url, headers=headers, timeout=timeout_config)
            except requests.exceptions.Timeout:
                # Timeout detectado - registra e retorna None com flag de timeout
                _record_timeout()
                logger.debug(f"Timeout ao buscar torrent header de {info_hash_hex}")
                return None, True, False
            except requests.exceptions.ReadTimeout:
                # Read timeout detectado - registra e retorna None com flag de timeout
                _record_timeout()
                logger.debug(f"Read timeout ao buscar torrent header de {info_hash_hex}")
                return None, True, False
            
            # Aceita 200 (full) ou 206 (partial)
            if response.status_code not in (200, 206):
                if response.status_code == 404:
                    return None, False, False  # Torrent não encontrado
                if response.status_code == 503:
                    # Service Unavailable - registra 503 e cacheia falha por mais tempo
                    _record_503()
                    _cache_failure(info_hash, is_503=True)
                    logger.debug(f"503 Service Unavailable ao buscar torrent header de {info_hash_hex}")
                    return None, False, True
                # Outros erros HTTP
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError:
                    # Erro HTTP genérico - cacheia falha
                    _cache_failure(info_hash, is_503=False)
                    logger.debug(f"Erro HTTP {response.status_code} ao buscar torrent header de {info_hash_hex}")
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
            
            # Próximo chunk
            start += len(chunk)
            chunk_size = min(chunk_size * 2, 64 * 1024)  # Aumenta chunk, máximo 64KB
        
        if all_data:
            _record_success()  # Registra sucesso
        return (all_data if all_data else None), False, False
    
    except requests.exceptions.Timeout:
        _record_timeout()
        logger.debug(f"Timeout ao buscar torrent header de {info_hash_hex}")
        return None, True, False
    except requests.exceptions.ReadTimeout:
        _record_timeout()
        logger.debug(f"Read timeout ao buscar torrent header de {info_hash_hex}")
        return None, True, False
    except requests.exceptions.HTTPError as e:
        # Trata erros HTTP específicos
        if hasattr(e.response, 'status_code') and e.response.status_code == 503:
            _record_503()
            _cache_failure(info_hash, is_503=True)
            logger.debug(f"503 Service Unavailable ao buscar torrent header de {info_hash_hex}")
            return None, False, True
        else:
            _cache_failure(info_hash, is_503=False)
            logger.debug(f"Erro HTTP ao buscar torrent header de {info_hash_hex}: {e}")
            return None, False, False
    except requests.exceptions.ConnectionError as e:
        # Erro de conexão (DNS, rede, etc.) - não registra como timeout, apenas loga
        logger.debug(f"Erro de conexão ao buscar torrent header de {info_hash_hex}: {e}")
        return None, False, False
    except requests.RequestException as e:
        logger.debug(f"Erro ao buscar torrent header de {info_hash_hex}: {e}")
        return None, False, False
    except Exception as e:
        logger.debug(f"Erro inesperado ao buscar torrent: {e}")
        return None, False, False


def fetch_metadata_from_itorrents(info_hash: str) -> Optional[Dict[str, any]]:
    """
    Busca metadados do torrent via iTorrents.org.
    
    Args:
        info_hash: Info hash do torrent (hex, 40 caracteres)
        
    Returns:
        Dict com metadados extraídos:
        - 'size' (int): Tamanho total em bytes (obrigatório)
        - 'name' (str, opcional): Nome do torrent
        - 'creation_date' (int, opcional): Timestamp Unix da criação do torrent
        
        Retorna None se não conseguir extrair pelo menos o tamanho.
    """
    info_hash_lower = info_hash.lower()
    
    redis = get_redis_client()
    
    # Se Redis está disponível, usa apenas Redis (não usa cache em memória)
    if redis:
        # Verifica cache Redis primeiro
        try:
            from cache.metadata_cache import MetadataCache
            metadata_cache = MetadataCache()
            data = metadata_cache.get(info_hash_lower)
            if data:
                # Log já é feito dentro de metadata_cache.get()
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
            
            if should_log:
                logger.debug(f"[CIRCUIT BREAKER] aberto - pulando busca de metadata (muitos timeouts/503s recentes)")
            return None
        
        # Verifica se há falha recente em cache
        if _is_failure_cached(info_hash):
            logger.debug(f"[CACHE FAILURE] Falha recente - pulando busca de metadata: {info_hash[:16]}...")
            return None
    else:
        # Redis não disponível - usa cache em memória como fallback
        # Verifica cache por requisição primeiro (evita buscas duplicadas na mesma requisição)
        if not hasattr(_request_cache, 'metadata_cache'):
            _request_cache.metadata_cache = {}
        if info_hash_lower in _request_cache.metadata_cache:
            cached_data = _request_cache.metadata_cache[info_hash_lower]
            size_info = f"size={cached_data.get('size', 'N/A')}"
            logger.debug(f"[CACHE MEMÓRIA HIT] Metadata recuperado: {info_hash[:16]}... ({size_info})")
            return cached_data
        
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
            
            if should_log:
                logger.debug(f"[CIRCUIT BREAKER] aberto - pulando busca de metadata (muitos timeouts/503s recentes)")
            return None
        
        # Verifica se há falha recente em cache
        if _is_failure_cached(info_hash):
            logger.debug(f"[CACHE FAILURE] Falha recente - pulando busca de metadata: {info_hash[:16]}...")
            return None
    
    # Usa lock por hash para evitar requisições simultâneas ao mesmo hash
    hash_lock = _get_hash_lock(info_hash)
    with hash_lock:
        # Verifica cache novamente após adquirir lock (outra thread pode ter cacheado)
        if redis:
            try:
                from cache.metadata_cache import MetadataCache
                metadata_cache = MetadataCache()
                data = metadata_cache.get(info_hash_lower)
                if data:
                    # Log já é feito dentro de metadata_cache.get()
                    return data
            except Exception:
                pass
        else:
            # Redis não disponível - verifica cache em memória novamente após lock
            if hasattr(_request_cache, 'metadata_cache') and info_hash_lower in _request_cache.metadata_cache:
                cached_data = _request_cache.metadata_cache[info_hash_lower]
                size_info = f"size={cached_data.get('size', 'N/A')}"
                logger.debug(f"[CACHE MEMÓRIA HIT] Metadata recuperado (após lock): {info_hash[:16]}... ({size_info})")
                return cached_data
        
        # Busca do iTorrents (não estava em cache)
        logger.debug(f"[ITORRENTS FETCH] Buscando metadata do iTorrents.org: {info_hash[:16]}...")
        
        # Tenta com lowercase primeiro (mais comum)
        torrent_data, was_timeout, was_503 = _fetch_torrent_header(info_hash, use_lowercase=True)
        
        # Se falhou mas não foi timeout nem 503, tenta com uppercase (menos comum)
        # Se foi timeout ou 503, não tenta novamente para evitar esperas longas
        if not torrent_data and not was_timeout and not was_503:
            torrent_data, was_timeout, was_503 = _fetch_torrent_header(info_hash, use_lowercase=False)
        
        if not torrent_data:
            # Cacheia a falha (já foi cacheado dentro de _fetch_torrent_header se foi 503)
            if was_timeout:
                logger.debug(f"[ITORRENTS FAIL] Timeout ao buscar metadata do iTorrents.org: {info_hash[:16]}...")
                _cache_failure(info_hash, is_503=True)  # Trata timeout como 503
            elif was_503:
                logger.debug(f"[ITORRENTS FAIL] Erro 503 (Service Unavailable) ao buscar metadata do iTorrents.org: {info_hash[:16]}...")
            else:
                logger.debug(f"[ITORRENTS FAIL] Não foi possível buscar metadata do iTorrents.org: {info_hash[:16]}...")
                _cache_failure(info_hash, is_503=False)
            return None
        
        # Extrai tamanho do bencode
        size = _parse_bencode_size(torrent_data)
        
        if not size:
            logger.debug(f"[ITORRENTS FAIL] Não foi possível extrair tamanho do metadata: {info_hash[:16]}...")
            return None
        
        logger.debug(f"[ITORRENTS SUCCESS] Metadata extraído com sucesso do iTorrents.org: {info_hash[:16]}... (size: {size})")
        
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
        
        # Cacheia no Redis se disponível (24 horas)
        if redis:
            try:
                from cache.metadata_cache import MetadataCache
                metadata_cache = MetadataCache()
                metadata_cache.set(info_hash_lower, result)
            except Exception:
                pass
        else:
            # Redis não disponível - usa cache em memória como fallback
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.metadata_cache = {}
            _request_cache.metadata_cache[info_hash_lower] = result
        
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
    from utils.text.text_processing import format_bytes
    
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
        logger.debug(f"Erro ao obter tamanho do torrent: {e}")
        return None

