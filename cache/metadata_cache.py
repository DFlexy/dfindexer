# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import json
import time
import threading
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
from cache.redis_keys import metadata_key, metadata_failure_key, metadata_failure503_key

logger = logging.getLogger(__name__)

_request_cache = threading.local()

class MetadataCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        info_hash_lower = info_hash.lower()
        
        if self.redis:
            try:
                key = metadata_key(info_hash_lower)
                data_str = self.redis.get(key)
                if data_str:
                    data = json.loads(data_str.decode('utf-8'))
                    return data
            except json.JSONDecodeError as e:
                logger.warning(f"[MetadataCache] Erro ao decodificar JSON: {info_hash_lower[:16]}... (chave: {key}) - {e}")
                return None
            except Exception as e:
                logger.debug(f"[MetadataCache] Erro ao ler Redis: {type(e).__name__} - {info_hash_lower[:16]}... - {e}")
                return None
        
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.metadata_cache = {}
            
            return _request_cache.metadata_cache.get(info_hash_lower)
        
        return None
    
    def set(self, info_hash: str, metadata: Dict[str, Any]) -> None:
        info_hash_lower = info_hash.lower()
        
        if self.redis:
            try:
                key = metadata_key(info_hash_lower)
                exists = self.redis.exists(key)
                metadata_json = json.dumps(metadata, separators=(',', ':'))
                self.redis.setex(key, 7 * 24 * 3600, metadata_json)
                return
            except Exception as e:
                logger.debug(f"[MetadataCache] Erro ao salvar Redis: {type(e).__name__} - {info_hash_lower[:16]}...")
                return
        
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.metadata_cache = {}
            
            _request_cache.metadata_cache[info_hash_lower] = metadata
    
    def set_failure(self, info_hash: str, ttl: int = 60) -> None:
        info_hash_lower = info_hash.lower()
        
        if self.redis:
            try:
                if ttl == 300:
                    key = metadata_failure503_key(info_hash_lower)
                else:
                    key = metadata_failure_key(info_hash_lower)
                self.redis.setex(key, ttl, str(int(time.time())))
                return
            except Exception:
                return
        
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_failure_cache'):
                _request_cache.metadata_failure_cache = {}
            
            expire_at = time.time() + ttl
            _request_cache.metadata_failure_cache[info_hash_lower] = expire_at
    
    def is_failure_cached(self, info_hash: str) -> bool:
        info_hash_lower = info_hash.lower()
        
        if self.redis:
            try:
                failure503_key = metadata_failure503_key(info_hash_lower)
                if self.redis.exists(failure503_key):
                    return True
                
                failure_key = metadata_failure_key(info_hash_lower)
                if self.redis.exists(failure_key):
                    return True
            except Exception:
                return False
        
        if not self.redis:
            if not hasattr(_request_cache, 'metadata_failure_cache'):
                return False
            
            expire_at = _request_cache.metadata_failure_cache.get(info_hash_lower)
            if expire_at and time.time() < expire_at:
                return True
            elif expire_at:
                del _request_cache.metadata_failure_cache[info_hash_lower]
        
        return False

