"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import json
import time
import threading
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
from cache.redis_keys import metadata_key, metadata_failure_key, metadata_failure503_key

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()


# Cache para metadata de torrents
class MetadataCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        # Obtém metadata do cache (Redis primeiro, memória se Redis não disponível)
        info_hash_lower = info_hash.lower()
        
        # Tenta Redis primeiro
        if self.redis:
            try:
                key = metadata_key(info_hash_lower)
                # Busca diretamente - get retorna None se não existir (mais eficiente que exists + get)
                data_str = self.redis.get(key)
                if data_str:
                    data = json.loads(data_str.decode('utf-8'))
                    # Log removido - HITs são muito comuns e geram muito ruído
                    return data
                # Log removido - MISSs são esperados para novos hashes
            except json.JSONDecodeError as e:
                # Erro ao decodificar JSON - pode ser corrupção de dados
                logger.warning(f"[MetadataCache] Erro ao decodificar JSON: {info_hash_lower[:16]}... (chave: {key}) - {e}")
                return None
            except Exception as e:
                # Se Redis falhou durante operação, não usa memória
                logger.debug(f"[MetadataCache] Erro ao ler Redis: {type(e).__name__} - {info_hash_lower[:16]}... - {e}")
                return None
        
        # Usa memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.metadata_cache = {}
            
            return _request_cache.metadata_cache.get(info_hash_lower)
        
        return None
    
    def set(self, info_hash: str, metadata: Dict[str, Any]) -> None:
        # Salva metadata no cache (Redis primeiro, memória se Redis não disponível)
        info_hash_lower = info_hash.lower()
        
        # Tenta Redis primeiro
        if self.redis:
            try:
                key = metadata_key(info_hash_lower)
                # Verifica se já existe no cache antes de salvar
                exists = self.redis.exists(key)
                # Chave separada para metadata principal - armazena JSON diretamente
                metadata_json = json.dumps(metadata, separators=(',', ':'))
                self.redis.setex(key, 7 * 24 * 3600, metadata_json)  # 7 dias
                # Log removido - SETs são muito comuns e geram muito ruído
                # Metadata salvo/atualizado no cache
                return
            except Exception as e:
                # Se Redis falhou durante operação, não salva em memória
                logger.debug(f"[MetadataCache] Erro ao salvar Redis: {type(e).__name__} - {info_hash_lower[:16]}...")
                return
        
        # Salva em memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.metadata_cache = {}
            
            _request_cache.metadata_cache[info_hash_lower] = metadata
    
    def set_failure(self, info_hash: str, ttl: int = 60) -> None:
        # Marca metadata como falha no cache (Redis primeiro, memória se Redis não disponível)
        info_hash_lower = info_hash.lower()
        
        # Tenta Redis primeiro
        if self.redis:
            try:
                # Usa chave específica conforme o tipo de falha
                if ttl == 300:  # Falha 503
                    key = metadata_failure503_key(info_hash_lower)
                else:  # Falha normal
                    key = metadata_failure_key(info_hash_lower)
                self.redis.setex(key, ttl, str(int(time.time())))
                return
            except Exception:
                # Se Redis falhou durante operação, não salva em memória
                return
        
        # Salva em memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_failure_cache'):
                _request_cache.metadata_failure_cache = {}
            
            expire_at = time.time() + ttl
            _request_cache.metadata_failure_cache[info_hash_lower] = expire_at
    
    def is_failure_cached(self, info_hash: str) -> bool:
        # Verifica se metadata está marcada como falha (Redis primeiro, memória se Redis não disponível)
        info_hash_lower = info_hash.lower()
        
        # Tenta Redis primeiro
        if self.redis:
            try:
                # Verifica falha 503 primeiro (TTL maior)
                failure503_key = metadata_failure503_key(info_hash_lower)
                if self.redis.exists(failure503_key):
                    return True
                
                # Verifica falha normal
                failure_key = metadata_failure_key(info_hash_lower)
                if self.redis.exists(failure_key):
                    return True
            except Exception:
                # Se Redis falhou durante operação, não usa memória
                return False
        
        # Usa memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_failure_cache'):
                return False
            
            expire_at = _request_cache.metadata_failure_cache.get(info_hash_lower)
            if expire_at and time.time() < expire_at:
                return True
            elif expire_at:
                # Expirou, remove
                del _request_cache.metadata_failure_cache[info_hash_lower]
        
        return False

