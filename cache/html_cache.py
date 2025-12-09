"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import threading
import time
from typing import Optional
from cache.redis_client import get_redis_client
from cache.redis_keys import html_long_key, html_short_key
from app.config import Config

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()


# Cache para documentos HTML
class HTMLCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, url: str) -> Optional[bytes]:
        # Obtém HTML do cache (Redis primeiro, memória se Redis não disponível)
        # Tenta Redis primeiro
        if self.redis:
            try:
                # Tenta cache de longa duração primeiro
                cache_key = html_long_key(url)
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug(f"[HTMLCache] HIT (long): {url[:60]}... (TTL: {Config.HTML_CACHE_TTL_LONG}s)")
                    return cached
                
                # Tenta cache de curta duração
                short_cache_key = html_short_key(url)
                cached = self.redis.get(short_cache_key)
                if cached:
                    logger.debug(f"[HTMLCache] HIT (short): {url[:60]}... (TTL: {Config.HTML_CACHE_TTL_SHORT}s)")
                    return cached
                
                logger.debug(f"[HTMLCache] MISS: {url[:60]}...")
            except Exception as e:
                logger.debug(f"[HTMLCache] Erro ao buscar cache Redis: {type(e).__name__}")
                # Se Redis falhou durante operação, não usa memória
                return None
        
        # Usa memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'html_cache'):
                _request_cache.html_cache = {}
            
            cache_entry = _request_cache.html_cache.get(url)
            if cache_entry:
                cached_content, expire_at = cache_entry
                if time.time() < expire_at:
                    logger.debug(f"[HTMLCache] HIT (memória): {url[:60]}...")
                    return cached_content
                else:
                    # Expirou, remove
                    logger.debug(f"[HTMLCache] EXPIRADO (memória): {url[:60]}...")
                    del _request_cache.html_cache[url]
        
        return None
    
    def set(self, url: str, html_content: bytes, skip_cache: bool = False) -> None:
        # Salva HTML no cache (Redis primeiro, memória se Redis não disponível)
        if skip_cache:
            return
        
        # Tenta Redis primeiro
        if self.redis:
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
                logger.debug(f"[HTMLCache] SET: {url[:60]}... (short: {Config.HTML_CACHE_TTL_SHORT}s, long: {Config.HTML_CACHE_TTL_LONG}s, size: {len(html_content)} bytes)")
                return
            except Exception as e:
                logger.debug(f"[HTMLCache] Erro ao salvar cache Redis: {type(e).__name__}")
                # Se Redis falhou durante operação, não salva em memória
                return
        
        # Salva em memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'html_cache'):
                _request_cache.html_cache = {}
            
            # Usa TTL curto para memória (10 minutos)
            expire_at = time.time() + Config.HTML_CACHE_TTL_SHORT
            _request_cache.html_cache[url] = (html_content, expire_at)

