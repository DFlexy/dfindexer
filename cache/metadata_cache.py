"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import json
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
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
            cache_key = f"metadata:{info_hash}"
            cached = self.redis.get(cache_key)
            if cached:
                return json.loads(cached.decode('utf-8'))
        except Exception:
            pass
        
        return None
    
    def set(self, info_hash: str, metadata: Dict[str, Any]) -> None:
        """Salva metadata no cache"""
        if not self.redis:
            return
        
        try:
            cache_key = f"metadata:{info_hash}"
            self.redis.setex(
                cache_key,
                Config.METADATA_CACHE_TTL,
                json.dumps(metadata)
            )
        except Exception:
            pass  # Ignora erros de cache

