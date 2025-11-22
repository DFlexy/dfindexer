"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import Optional
from cache.redis_client import get_redis_client
from cache.redis_keys import html_long_key, html_short_key
from app.config import Config

logger = logging.getLogger(__name__)


# Cache para documentos HTML
class HTMLCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, url: str) -> Optional[bytes]:
        """Obtém HTML do cache"""
        if not self.redis:
            return None
        
        try:
            # Tenta cache de longa duração primeiro
            cache_key = html_long_key(url)
            cached = self.redis.get(cache_key)
            if cached:
                return cached
            
            # Tenta cache de curta duração
            short_cache_key = html_short_key(url)
            cached = self.redis.get(short_cache_key)
            if cached:
                return cached
        except Exception:
            pass
        
        return None
    
    def set(self, url: str, html_content: bytes, skip_cache: bool = False) -> None:
        """Salva HTML no cache"""
        if not self.redis or skip_cache:
            return
        
        try:
            # Cache de curta duração
            short_cache_key = html_short_key(url)
            self.redis.setex(
                short_cache_key,
                Config.HTML_CACHE_TTL_SHORT,
                html_content
            )
            
            # Cache de longa duração
            cache_key = html_long_key(url)
            self.redis.setex(
                cache_key,
                Config.HTML_CACHE_TTL_LONG,
                html_content
            )
        except Exception:
            pass  # Ignora erros de cache

