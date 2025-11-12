"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import re
import time
import threading
from typing import Dict, Optional
from urllib.parse import unquote
import requests
from cache.redis_client import get_redis_client
from app.config import Config

logger = logging.getLogger(__name__)

# Rate limiter simples (2 req/s com burst de 4)
_rate_limiter_lock = threading.Lock()
_rate_limiter_last_request = 0.0
_rate_limiter_min_interval = 0.5  # 2 req/s = 0.5s entre requisições
_rate_limiter_burst_tokens = 4

# Circuit breaker para evitar consultas quando há muitos timeouts
_CIRCUIT_BREAKER_KEY = "metadata:circuit_breaker"
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3  # Número de timeouts consecutivos antes de desabilitar
_CIRCUIT_BREAKER_DISABLE_DURATION = 300  # 5 minutos de desabilitação após muitos timeouts
_CIRCUIT_BREAKER_FAILURE_CACHE_TTL = 60  # Cache de falhas individuais por 1 minuto


def _rate_limit():
    """Rate limiter simples para iTorrents"""
    global _rate_limiter_last_request, _rate_limiter_burst_tokens
    
    with _rate_limiter_lock:
        now = time.time()
        elapsed = now - _rate_limiter_last_request
        
        # Recarrega tokens de burst (1 token a cada 0.5s, máximo 4)
        if elapsed >= _rate_limiter_min_interval:
            _rate_limiter_burst_tokens = min(4, _rate_limiter_burst_tokens + int(elapsed / _rate_limiter_min_interval))
        
        # Se não tem tokens, espera
        if _rate_limiter_burst_tokens <= 0:
            wait_time = _rate_limiter_min_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
        
        _rate_limiter_burst_tokens -= 1
        _rate_limiter_last_request = now


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
                f"Metadata desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
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


def _is_failure_cached(info_hash: str) -> bool:
    """
    Verifica se uma falha recente está em cache para evitar tentativas repetidas.
    """
    redis = get_redis_client()
    if not redis:
        return False
    
    try:
        failure_key = f"metadata:failure:{info_hash.lower()}"
        return redis.exists(failure_key) > 0
    except Exception:
        return False


def _cache_failure(info_hash: str):
    """
    Cacheia uma falha para evitar tentativas repetidas por um período.
    """
    redis = get_redis_client()
    if not redis:
        return
    
    try:
        failure_key = f"metadata:failure:{info_hash.lower()}"
        redis.setex(failure_key, _CIRCUIT_BREAKER_FAILURE_CACHE_TTL, "1")
    except Exception:
        pass


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


def _fetch_torrent_header(info_hash: str, use_lowercase: bool = False) -> Optional[bytes]:
    """
    Baixa apenas o header do arquivo .torrent do iTorrents.
    Usa HTTP Range requests para baixar só o necessário (até 512KB).
    """
    info_hash_hex = info_hash.lower() if use_lowercase else info_hash.upper()
    url = f"https://itorrents.org/torrent/{info_hash_hex}.torrent"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'TorrentMetadataService/1.0',
        'Accept-Encoding': 'gzip',
    })
    
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
                response = session.get(url, headers=headers, timeout=15)
            except requests.exceptions.Timeout:
                # Timeout detectado - registra e retorna None
                _record_timeout()
                logger.debug(f"Timeout ao buscar torrent header de {info_hash_hex}")
                return None
            except requests.exceptions.ReadTimeout:
                # Read timeout detectado - registra e retorna None
                _record_timeout()
                logger.debug(f"Read timeout ao buscar torrent header de {info_hash_hex}")
                return None
            
            # Aceita 200 (full) ou 206 (partial)
            if response.status_code not in (200, 206):
                if response.status_code == 404:
                    return None  # Torrent não encontrado
                response.raise_for_status()
            
            chunk = response.content
            if not chunk:
                break  # Fim do arquivo
            
            all_data += chunk
            
            # Se recebeu HTML (erro), para
            if b'<!DOCTYPE html' in all_data or b'<html' in all_data.lower():
                return None
            
            # Verifica se já tem o suficiente (procura por "pieces" que vem depois dos metadados)
            if b'pieces' in all_data:
                # Encontrou o campo "pieces", já tem metadados suficientes
                pieces_index = all_data.index(b'pieces')
                # Retorna até "pieces" + um pouco mais para garantir
                _record_success()  # Registra sucesso
                return all_data[:pieces_index + 20]
            
            # Se recebeu menos que o chunk_size, chegou ao fim
            if len(chunk) < chunk_size:
                break
            
            # Próximo chunk
            start += len(chunk)
            chunk_size = min(chunk_size * 2, 64 * 1024)  # Aumenta chunk, máximo 64KB
        
        if all_data:
            _record_success()  # Registra sucesso
        return all_data if all_data else None
    
    except requests.exceptions.Timeout:
        _record_timeout()
        logger.debug(f"Timeout ao buscar torrent header de {info_hash_hex}")
        return None
    except requests.exceptions.ReadTimeout:
        _record_timeout()
        logger.debug(f"Read timeout ao buscar torrent header de {info_hash_hex}")
        return None
    except requests.RequestException as e:
        logger.debug(f"Erro ao buscar torrent header de {info_hash_hex}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Erro inesperado ao buscar torrent: {e}")
        return None


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
    # Verifica circuit breaker primeiro
    if _is_circuit_breaker_open():
        logger.debug(f"Circuit breaker aberto - pulando busca de metadata para {info_hash}")
        return None
    
    # Verifica se há falha recente em cache
    if _is_failure_cached(info_hash):
        logger.debug(f"Falha recente em cache - pulando busca de metadata para {info_hash}")
        return None
    
    redis = get_redis_client()
    
    # Verifica cache primeiro
    if redis:
        try:
            cache_key = f"metadata:{info_hash.lower()}"
            cached = redis.get(cache_key)
            if cached:
                import json
                data = json.loads(cached)
                logger.debug(f"Cache hit para metadata: {info_hash}")
                return data
        except Exception as e:
            logger.debug(f"Erro ao verificar cache: {e}")
    
    # Tenta com uppercase primeiro
    torrent_data = _fetch_torrent_header(info_hash, use_lowercase=False)
    
    # Se falhou, tenta com lowercase
    if not torrent_data:
        torrent_data = _fetch_torrent_header(info_hash, use_lowercase=True)
    
    if not torrent_data:
        # Cacheia a falha para evitar tentativas repetidas
        _cache_failure(info_hash)
        return None
    
    # Extrai tamanho do bencode
    size = _parse_bencode_size(torrent_data)
    
    if not size:
        return None
    
    # Tenta extrair nome também (opcional)
    name = None
    try:
        # Procura por padrão "4:name" seguido de string bencode
        name_pattern = rb'4:name(\d+):(.+?)(?=[0-9]|e|:)'
        name_match = re.search(name_pattern, torrent_data)
        if name_match:
            name_len = int(name_match.group(1))
            name_bytes = name_match.group(2)[:name_len]
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
    
    # Cacheia resultado (24 horas)
    if redis:
        try:
            import json
            cache_key = f"metadata:{info_hash.lower()}"
            redis.setex(cache_key, 24 * 3600, json.dumps(result))
        except Exception:
            pass
    
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
    from utils.text_processing import format_bytes
    
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

