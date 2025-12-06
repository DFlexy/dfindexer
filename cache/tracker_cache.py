"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import json
import time
import threading
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
from cache.redis_keys import tracker_key
from app.config import Config

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()


# Cache para dados de trackers (seeds/leechers)
class TrackerCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        # Obtém dados de tracker do cache (Redis primeiro, memória se Redis não disponível)
        info_hash_lower = info_hash.lower()
        
        # Tenta Redis primeiro
        if self.redis:
            try:
                key = tracker_key(info_hash_lower)
                # Usa Redis Hash para armazenar dados de tracker
                peers_str = self.redis.hget(key, 'peers')
                if peers_str:
                    return json.loads(peers_str.decode('utf-8'))
            except Exception:
                # Se Redis falhou durante operação, não usa memória
                return None
        
        # Usa memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'tracker_cache'):
                _request_cache.tracker_cache = {}
            
            return _request_cache.tracker_cache.get(info_hash_lower)
        
        return None
    
    def set(self, info_hash: str, tracker_data: Dict[str, Any]) -> None:
        # Salva dados de tracker no cache (Redis primeiro, memória se Redis não disponível)
        info_hash_lower = info_hash.lower()
        
        # Tenta Redis primeiro
        if self.redis:
            try:
                key = tracker_key(info_hash_lower)
                # Usa Redis Hash para armazenar dados de tracker
                self.redis.hset(key, 'peers', json.dumps(tracker_data, separators=(',', ':')))
                self.redis.hset(key, 'last_scrape', str(int(time.time())))
                self.redis.hset(key, 'created', str(int(time.time())))
                # Define TTL no hash inteiro (24 horas = 86400s)
                # Dados de tracker mudam frequentemente, então TTL menor é mais apropriado
                self.redis.expire(key, 24 * 3600)
                return
            except Exception:
                # Se Redis falhou durante operação, não salva em memória
                return
        
        # Salva em memória apenas se Redis não está disponível desde o início
        if not self.redis:
            if not hasattr(_request_cache, 'tracker_cache'):
                _request_cache.tracker_cache = {}
            
            _request_cache.tracker_cache[info_hash_lower] = tracker_data

