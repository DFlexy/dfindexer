# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import redis
else:
    try:
        import redis
    except ImportError:
        redis = None  # type: ignore

from app.config import Config
logger = logging.getLogger(__name__)

_redis_client: Optional['redis.Redis'] = None if redis is None else None
_last_warning_log = 0.0
_WARNING_LOG_COOLDOWN = 60

def init_redis():
    global _redis_client, _last_warning_log
    
    if redis is None:
        _redis_client = None
        return
    
    if not Config.REDIS_HOST or Config.REDIS_HOST.strip() == '':
        _redis_client = None
        return
    
    try:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2
        )
        _redis_client.ping()
        _last_warning_log = 0.0
    except Exception as e:
        _redis_client = None
        pass

def get_redis_client() -> Optional['redis.Redis']:
    if redis is None:
        return None
    
    if _redis_client is None:
        try:
            init_redis()
        except Exception:
            pass
    return _redis_client

