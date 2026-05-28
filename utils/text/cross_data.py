# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def get_cross_data_from_redis(info_hash: str) -> Optional[Dict[str, Any]]:
    if not info_hash or len(info_hash) != 40:
        return None
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import torrent_cross_data_key
        
        redis = get_redis_client()
        if not redis:
            return None
        
        info_hash_lower = info_hash.lower()
        key = torrent_cross_data_key(info_hash_lower)
        data = redis.hgetall(key)
        if not data:
            return None
        
        result = {}
        for field, value in data.items():
            field_str = field.decode('utf-8')
            value_str = value.decode('utf-8')
            
            if field_str == 'missing_dn':
                result[field_str] = value_str.lower() == 'true'
            elif field_str == 'has_legenda':
                result[field_str] = value_str.lower() == 'true'
            elif field_str in ('tracker_seed', 'tracker_leech'):
                try:
                    result[field_str] = int(value_str) if value_str and value_str != 'N/A' else 0
                except (ValueError, TypeError):
                    result[field_str] = 0
            else:
                result[field_str] = value_str if value_str and value_str != 'N/A' else None
        
        if result:
            return result
    except Exception:
        pass
    
    return None

def save_cross_data_to_redis(info_hash: str, data: Dict[str, Any]) -> None:
    if not info_hash or len(info_hash) != 40:
        return
    
    if not data:
        return
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import torrent_cross_data_key
        
        redis = get_redis_client()
        if not redis:
            return
        
        info_hash_lower = info_hash.lower()
        key = torrent_cross_data_key(info_hash_lower)
        
        to_save = {}
        for field, value in data.items():
            if value is None:
                continue
            
            if field in ('tracker_seed', 'tracker_leech'):
                if value != '' and value != 'N/A':
                    if isinstance(value, int):
                        to_save[field] = str(value)
                    elif isinstance(value, str) and value.strip().isdigit():
                        to_save[field] = value.strip()
            else:
                if isinstance(value, bool):
                    to_save[field] = 'true' if value else 'false'
                elif isinstance(value, int):
                    to_save[field] = str(value)
                else:
                    value_str = str(value).strip()
                    if value_str and value_str != 'N/A' and len(value_str) >= 1:
                        to_save[field] = value_str
        
        if not to_save:
            return
        
        redis.hset(key, mapping=to_save)
        
        has_tracker_data = 'tracker_seed' in to_save or 'tracker_leech' in to_save
        
        current_ttl = redis.ttl(key)
        
        if has_tracker_data:

            if current_ttl == -1 or current_ttl > 24 * 3600:
                redis.expire(key, 24 * 3600)
        else:

            if current_ttl == -1 or current_ttl < 30 * 24 * 3600:
                redis.expire(key, 30 * 24 * 3600)
    except Exception:
        pass

def get_field_from_cross_data(info_hash: str, field: str) -> Optional[str]:
    cross_data = get_cross_data_from_redis(info_hash)
    if cross_data:
        value = cross_data.get(field)
        if value and value != 'N/A':
            return str(value) if not isinstance(value, bool) else ('true' if value else 'false')
    return None

