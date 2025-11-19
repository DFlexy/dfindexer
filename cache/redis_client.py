"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import redis
from typing import Optional
from app.config import Config
logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None


# Inicializa cliente Redis (opcional)
def init_redis():
    global _redis_client
    try:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            decode_responses=False,  # Retorna bytes para compatibilidade
            socket_connect_timeout=2,
            socket_timeout=2
        )
        # Testa conexão
        _redis_client.ping()
        logger.info("[[ Redis Conectado ]]")
    except Exception:
        _redis_client = None


# Retorna cliente Redis ou None se não disponível
def get_redis_client() -> Optional[redis.Redis]:
    if _redis_client is None:
        try:
            init_redis()
        except:
            pass
    return _redis_client

