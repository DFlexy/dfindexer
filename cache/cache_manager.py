# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import threading
import time
from typing import Optional, List, Dict, Any
from cache.redis_client import get_redis_client
from cache.http_cache import get_http_cache

logger = logging.getLogger(__name__)

class CacheInvalidationManager:
    """Gerenciador de invalidação inteligente de cache"""
    
    def __init__(self):
        self.redis = get_redis_client()
        self.http_cache = get_http_cache()
        self._lock = threading.Lock()
        self._invalidation_log: Dict[str, float] = {}
        self._min_invalidation_interval = 300
    
    def invalidate_url(self, url: str, reason: str = "manual") -> bool:
        with self._lock:
            now = time.time()
            last_invalidation = self._invalidation_log.get(url, 0)
            
            if now - last_invalidation < self._min_invalidation_interval:
                return False
            
            try:
                with self.http_cache._lock:
                    if url in self.http_cache._cache:
                        del self.http_cache._cache[url]
                        logger.debug(f"Cache local invalidado: {url[:50]}... (razão: {reason})")
            except Exception as e:
                logger.debug(f"Erro ao invalidar cache local: {type(e).__name__}")
            
            if self.redis:
                try:
                    from cache.redis_keys import html_long_key, html_short_key
                    long_key = html_long_key(url)
                    short_key = html_short_key(url)
                    
                    deleted = 0
                    if self.redis.exists(long_key):
                        self.redis.delete(long_key)
                        deleted += 1
                    if self.redis.exists(short_key):
                        self.redis.delete(short_key)
                        deleted += 1
                    
                    if deleted > 0:
                        logger.debug(f"Cache Redis invalidado: {url[:50]}... ({deleted} chaves, razão: {reason})")
                except Exception as e:
                    logger.debug(f"Erro ao invalidar cache Redis: {type(e).__name__}")
            
            self._invalidation_log[url] = now
            
            old_urls = [u for u, t in self._invalidation_log.items() if now - t > 3600]
            for old_url in old_urls:
                del self._invalidation_log[old_url]
            
            return True
    
    def invalidate_pattern(self, base_url: str, pattern: str = "*") -> int:
        invalidated = 0
        
        with self.http_cache._lock:
            urls_to_remove = []
            for url in list(self.http_cache._cache.keys()):
                if url.startswith(base_url):
                    if pattern == "*" or pattern in url:
                        urls_to_remove.append(url)
            
            for url in urls_to_remove:
                del self.http_cache._cache[url]
                invalidated += 1
        
        if invalidated > 0:
            logger.info(f"Cache invalidado: {invalidated} URLs de {base_url} (padrão: {pattern})")
        
        return invalidated
    
    def get_cache_stats(self) -> Dict[str, Any]:
        stats = {
            'http_cache': self.http_cache.stats() if self.http_cache else {},
            'redis_available': self.redis is not None,
            'invalidations_logged': len(self._invalidation_log)
        }
        
        if self.redis:
            try:
                info = self.redis.info('memory')
                stats['redis_memory'] = {
                    'used_memory_human': info.get('used_memory_human', 'N/A'),
                    'used_memory_peak_human': info.get('used_memory_peak_human', 'N/A'),
                }
            except Exception:
                stats['redis_memory'] = {'error': 'unable to fetch'}
        
        return stats
    
    def warm_cache(self, urls: List[str], fetch_func) -> int:
        """Pre-aquece o cache com uma lista de URLs"""
        cached = 0
        
        for url in urls:
            try:
                if self.http_cache.get(url):
                    continue
                
                content = fetch_func(url)
                if content:
                    self.http_cache.set(url, content)
                    cached += 1
            except Exception as e:
                logger.debug(f"Erro ao aquecer cache para {url[:50]}: {type(e).__name__}")
        
        if cached > 0:
            logger.info(f"Cache aquecido: {cached}/{len(urls)} URLs")
        
        return cached

_cache_manager = None
_cache_manager_lock = threading.Lock()

def get_cache_manager() -> CacheInvalidationManager:
    global _cache_manager
    
    if _cache_manager is None:
        with _cache_manager_lock:
            if _cache_manager is None:
                _cache_manager = CacheInvalidationManager()
    
    return _cache_manager

