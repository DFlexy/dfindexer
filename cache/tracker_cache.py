# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import json
import time
import threading
from typing import Optional, Dict, Any
from cache.redis_client import get_redis_client
from cache.redis_keys import tracker_key
from app.config import Config

logger = logging.getLogger(__name__)

_request_cache = threading.local()

class TrackerCache:
    def __init__(self):
        self.redis = get_redis_client()
    
    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        info_hash_lower = info_hash.lower()
        
        if self.redis:
            try:
                key = tracker_key(info_hash_lower)
                peers_str = self.redis.hget(key, 'peers')
                if peers_str:
                    data = json.loads(peers_str.decode('utf-8'))
                    return data
            except Exception as e:
                logger.debug(f"[TrackerCache] Erro ao buscar cache Redis: {type(e).__name__}")
                return None
        
        if not self.redis:
            if not hasattr(_request_cache, 'tracker_cache'):
                _request_cache.tracker_cache = {}
            
            cached = _request_cache.tracker_cache.get(info_hash_lower)
            return cached
        
        return None
    
    def set(self, info_hash: str, tracker_data: Dict[str, Any]) -> None:
        info_hash_lower = info_hash.lower()
        
        if self.redis:
            try:
                key = tracker_key(info_hash_lower)
                self.redis.hset(key, 'peers', json.dumps(tracker_data, separators=(',', ':')))
                self.redis.hset(key, 'last_scrape', str(int(time.time())))
                self.redis.hset(key, 'created', str(int(time.time())))
                self.redis.expire(key, Config.TRACKER_CACHE_TTL)
                return
            except Exception as e:
                logger.debug(f"[TrackerCache] Erro ao salvar cache Redis: {type(e).__name__}")
                return
        
        if not self.redis:
            if not hasattr(_request_cache, 'tracker_cache'):
                _request_cache.tracker_cache = {}
            
            _request_cache.tracker_cache[info_hash_lower] = tracker_data

