"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import json
import time
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
from cache.redis_keys import tracker_key
from app.config import Config

logger = logging.getLogger(__name__)


# Cache para dados de trackers (seeds/leechers)
class TrackerCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        """Obtém dados de tracker do cache"""
        if not self.redis:
            return None
        
        try:
            key = tracker_key(info_hash)
            # Usa Redis Hash para armazenar dados de tracker
            peers_str = self.redis.hget(key, 'peers')
            if peers_str:
                return json.loads(peers_str.decode('utf-8'))
        except Exception:
            pass
        
        return None
    
    def set(self, info_hash: str, tracker_data: Dict[str, Any]) -> None:
        """Salva dados de tracker no cache"""
        if not self.redis:
            return
        
        try:
            key = tracker_key(info_hash)
            # Usa Redis Hash para armazenar dados de tracker
            self.redis.hset(key, 'peers', json.dumps(tracker_data, separators=(',', ':')))
            self.redis.hset(key, 'last_scrape', str(int(time.time())))
            self.redis.hset(key, 'created', str(int(time.time())))
            # Define TTL no hash inteiro
            self.redis.expire(key, Config.TRACKER_CACHE_TTL)
        except Exception:
            pass  # Ignora erros de cache

