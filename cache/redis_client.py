"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

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
_WARNING_LOG_COOLDOWN = 60  # Só loga warning uma vez por minuto


def init_redis():
    global _redis_client, _last_warning_log
    
    # Se o módulo redis não está disponível, retorna sem logar
    if redis is None:
        _redis_client = None
        return
    
    # Se REDIS_HOST não está configurado, retorna sem logar (bootstrap.log faz isso)
    if not Config.REDIS_HOST or Config.REDIS_HOST.strip() == '':
        _redis_client = None
        return
    
    try:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            decode_responses=False,  # Retorna bytes para compatibilidade
            socket_connect_timeout=2,
            socket_timeout=2
        )
        _redis_client.ping()
        # Não loga aqui - bootstrap.log faz isso
        _last_warning_log = 0.0  # Reset cooldown quando conectar
    except Exception as e:
        _redis_client = None
        # Não loga aqui - bootstrap.log faz isso
        pass


def get_redis_client() -> Optional['redis.Redis']:
    # Se o módulo redis não está disponível, retorna None
    if redis is None:
        return None
    
    if _redis_client is None:
        try:
            init_redis()
        except Exception:
            pass
    return _redis_client

