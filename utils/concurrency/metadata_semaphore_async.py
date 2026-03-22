"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import asyncio
import logging
from contextlib import asynccontextmanager
from app.config import Config

logger = logging.getLogger(__name__)

# Semáforo async global para limitar requisições de metadata simultâneas
# Evita rate limiting da API quando múltiplos scrapers processam simultaneamente
_metadata_semaphore: asyncio.Semaphore = None
_semaphore_lock = asyncio.Lock()
_current_limit = None


# Retorna o semáforo async global para requisições de metadata
# Recria o semáforo se o limite mudou
async def get_metadata_semaphore_async() -> asyncio.Semaphore:
    global _metadata_semaphore, _current_limit

    max_concurrent = Config.METADATA_MAX_CONCURRENT if hasattr(Config, 'METADATA_MAX_CONCURRENT') else 64

    # Se o semáforo não existe ou o limite mudou, recria
    if _metadata_semaphore is None or _current_limit != max_concurrent:
        async with _semaphore_lock:
            # Double-check locking pattern
            if _metadata_semaphore is None or _current_limit != max_concurrent:
                if _metadata_semaphore is not None:
                    logger.info(f"[Semaforo] metadata async recriado: {_current_limit} → {max_concurrent} requisicoes simultaneas")
                else:
                    logger.info(f"[Semaforo] metadata async criado com limite de {max_concurrent} requisicoes simultaneas")
                _metadata_semaphore = asyncio.Semaphore(max_concurrent)
                _current_limit = max_concurrent

    return _metadata_semaphore


# Context manager async para garantir que o slot sempre seja liberado
@asynccontextmanager
async def metadata_slot_async(timeout=None):
    """
    Context manager async para adquirir e liberar slot de metadata automaticamente.

    Args:
        timeout: Timeout em segundos para adquirir o slot (None = sem timeout)

    Usage:
        async with metadata_slot_async():
            # código que usa metadata
            pass
    """
    semaphore = await get_metadata_semaphore_async()
    acquired = False

    try:
        if timeout is not None:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
                acquired = True
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timeout ao adquirir slot de metadata após {timeout}s")
        else:
            await semaphore.acquire()
            acquired = True
        yield
    finally:
        if acquired:
            semaphore.release()
