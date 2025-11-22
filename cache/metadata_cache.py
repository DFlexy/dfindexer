"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import json
import time
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
from cache.redis_keys import metadata_key
from app.config import Config

logger = logging.getLogger(__name__)


# Cache para metadata de torrents
class MetadataCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        """Obtém metadata do cache"""
        if not self.redis:
            return None
        
        try:
            key = metadata_key(info_hash)
            # Usa Redis Hash para armazenar metadata
            data_str = self.redis.hget(key, 'data')
            if data_str:
                return json.loads(data_str.decode('utf-8'))
        except Exception:
            pass
        
        return None
    
    def set(self, info_hash: str, metadata: Dict[str, Any]) -> None:
        """Salva metadata no cache"""
        if not self.redis:
            return
        
        try:
            key = metadata_key(info_hash)
            # Usa Redis Hash para armazenar metadata
            self.redis.hset(key, 'data', json.dumps(metadata, separators=(',', ':')))
            self.redis.hset(key, 'created', str(int(time.time())))
            # Define TTL no hash inteiro
            self.redis.expire(key, Config.METADATA_CACHE_TTL)
        except Exception:
            pass  # Ignora erros de cache
    
    def set_failure(self, info_hash: str, ttl: int = 60) -> None:
        """Marca metadata como falha no cache"""
        if not self.redis:
            return
        
        try:
            key = metadata_key(info_hash)
            self.redis.hset(key, 'failure', str(int(time.time())))
            self.redis.expire(key, ttl)
        except Exception:
            pass  # Ignora erros de cache

