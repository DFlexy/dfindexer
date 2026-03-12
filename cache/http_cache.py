"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import threading
import time
from typing import Optional, Dict, Any
from app.config import Config

# Cache local em memória para requisições HTTP
# Evita requisições duplicadas em curto período de tempo (30s padrão)
# Complementa o cache Redis com uma camada ainda mais rápida


class HTTPLocalCache:
    """
    Cache local thread-safe em memória para requisições HTTP.
    Usa TTL configurável e limpeza automática de entradas expiradas.
    """
    
    def __init__(self, ttl: Optional[int] = None, max_size: int = 200):
        """
        Args:
            ttl: Time to live em segundos (padrão: Config.LOCAL_CACHE_TTL ou 30s)
            max_size: Tamanho máximo do cache (padrão: 200 entradas)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.ttl = ttl if ttl is not None else (Config.LOCAL_CACHE_TTL if hasattr(Config, 'LOCAL_CACHE_TTL') else 30)
        self.max_size = max_size
        self.enabled = Config.LOCAL_CACHE_ENABLED if hasattr(Config, 'LOCAL_CACHE_ENABLED') else True
        self._last_cleanup = time.time()
        self._cleanup_interval = 30  # Limpeza a cada 30 segundos
    
    def get(self, key: str) -> Optional[bytes]:
        """
        Obtém valor do cache se não expirou.
        
        Args:
            key: Chave (geralmente URL)
            
        Returns:
            Valor em bytes ou None se não encontrado/expirado
        """
        if not self.enabled:
            return None
        
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            now = time.time()
            
            # Verifica se expirou
            if now > entry['expires_at']:
                del self._cache[key]
                return None
            
            entry['hits'] += 1
            entry['last_access'] = now
            return entry['value']
    
    def set(self, key: str, value: bytes) -> None:
        """
        Armazena valor no cache com TTL.
        
        Args:
            key: Chave (geralmente URL)
            value: Valor em bytes
        """
        if not self.enabled:
            return
        
        with self._lock:
            now = time.time()
            
            # Limpeza periódica de entradas expiradas
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired(now)
                self._last_cleanup = now
            
            # Se atingiu o tamanho máximo, remove expiradas primeiro, depois mais antigas
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
        """Remove entradas expiradas (deve ser chamado dentro do lock)."""
        expired_keys = [
            key for key, entry in self._cache.items()
            if now > entry['expires_at']
        ]
        for key in expired_keys:
            del self._cache[key]
    
    def _evict_oldest(self) -> None:
        """Remove entradas mais antigas (LRU) quando cache está cheio. Remove 25% de uma vez."""
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
        """
        Retorna estatísticas do cache.
        
        Returns:
            Dict com estatísticas (size, total_hits, etc.)
        """
        with self._lock:
            total_hits = sum(entry['hits'] for entry in self._cache.values())
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'total_hits': total_hits,
                'ttl': self.ttl,
                'enabled': self.enabled
            }


# Instância global (singleton)
_http_cache = None
_http_cache_lock = threading.Lock()


def get_http_cache() -> HTTPLocalCache:
    """
    Obtém instância global do cache HTTP local.
    Thread-safe singleton pattern.
    
    Returns:
        Instância de HTTPLocalCache
    """
    global _http_cache
    
    if _http_cache is None:
        with _http_cache_lock:
            if _http_cache is None:
                _http_cache = HTTPLocalCache()
    
    return _http_cache

