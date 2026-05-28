# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import threading
import time
from typing import Optional, Dict, Any
from app.config import Config

class HTTPLocalCache:
    """Cache local thread-safe em memória para requisições HTTP"""
    
    def __init__(self, ttl: Optional[int] = None, max_size: int = 200):
        """Args:"""
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.ttl = ttl if ttl is not None else (Config.LOCAL_CACHE_TTL if hasattr(Config, 'LOCAL_CACHE_TTL') else 30)
        self.max_size = max_size
        self.enabled = Config.LOCAL_CACHE_ENABLED if hasattr(Config, 'LOCAL_CACHE_ENABLED') else True
        self._last_cleanup = time.time()
        self._cleanup_interval = 30
    
    def get(self, key: str) -> Optional[bytes]:
        if not self.enabled:
            return None
        
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            now = time.time()
            
            if now > entry['expires_at']:
                del self._cache[key]
                return None
            
            entry['hits'] += 1
            entry['last_access'] = now
            return entry['value']
    
    def set(self, key: str, value: bytes) -> None:
        """Armazena valor no cache com TTL"""
        if not self.enabled:
            return
        
        with self._lock:
            now = time.time()
            
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired(now)
                self._last_cleanup = now
            
            if len(self._cache) >= self.max_size:
                self._cleanup_expired(now)
                if len(self._cache) >= self.max_size:
                    self._evict_oldest()
            
            self._cache[key] = {
                'value': value,
                'expires_at': now + self.ttl,
                'created_at': now,
                'last_access': now,
                'hits': 0
            }
    
    def _cleanup_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._cache.items()
            if now > entry['expires_at']
        ]
        for key in expired_keys:
            del self._cache[key]
    
    def _evict_oldest(self) -> None:
        if not self._cache:
            return
        
        to_remove = max(1, len(self._cache) // 4)
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k]['last_access']
        )
        for key in sorted_keys[:to_remove]:
            del self._cache[key]
    
    def clear(self) -> None:
        """Limpa todo o cache."""
        with self._lock:
            self._cache.clear()
    
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total_hits = sum(entry['hits'] for entry in self._cache.values())
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'total_hits': total_hits,
                'ttl': self.ttl,
                'enabled': self.enabled
            }

_http_cache = None
_http_cache_lock = threading.Lock()

def get_http_cache() -> HTTPLocalCache:
    global _http_cache
    
    if _http_cache is None:
        with _http_cache_lock:
            if _http_cache is None:
                _http_cache = HTTPLocalCache()
    
    return _http_cache

