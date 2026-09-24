# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager, contextmanager

from app.config import Config

logger = logging.getLogger(__name__)

_sync_semaphore = None
_sync_limit = None
_sync_lock = threading.Lock()

_times_list = []
_times_lock = threading.Lock()

_async_semaphore: asyncio.Semaphore = None
_async_limit = None
_async_lock = asyncio.Lock()


def get_metadata_semaphore():
    global _sync_semaphore, _sync_limit

    max_concurrent = Config.METADATA_MAX_CONCURRENT if hasattr(Config, 'METADATA_MAX_CONCURRENT') else 128

    if _sync_semaphore is None or _sync_limit != max_concurrent:
        with _sync_lock:
            if _sync_semaphore is None or _sync_limit != max_concurrent:
                if _sync_semaphore is not None:
                    logger.info(f"[Semaforo] metadata recriado: {_sync_limit} → {max_concurrent} requisicoes simultaneas")
                else:
                    logger.info(f"[Semaforo] metadata criado com limite de {max_concurrent} requisicoes simultaneas")
                _sync_semaphore = threading.Semaphore(max_concurrent)
                _sync_limit = max_concurrent

    return _sync_semaphore


@contextmanager
def metadata_slot(timeout=None):
    semaphore = get_metadata_semaphore()
    acquired = False
    start_time = time.time()

    try:
        if timeout is not None:
            acquired = semaphore.acquire(timeout=timeout)
            if not acquired:
                raise TimeoutError(f"Timeout ao adquirir slot de metadata após {timeout}s")
        else:
            semaphore.acquire()
            acquired = True
        yield
    finally:
        if acquired:
            semaphore.release()
            elapsed = time.time() - start_time
            available_after = semaphore._value
            in_use_after = _sync_limit - available_after

            with _times_lock:
                _times_list.append(elapsed)

                if in_use_after == 0 and len(_times_list) > 0:
                    avg_time = sum(_times_list) / len(_times_list)
                    min_time = min(_times_list)
                    max_time = max(_times_list)
                    total_requests = len(_times_list)
                    logger.debug(f"[Semaforo] Batch concluido: {total_requests} requisicoes | Tempo medio: {avg_time:.2f}s | Min: {min_time:.2f}s | Max: {max_time:.2f}s")
                    _times_list.clear()


async def get_metadata_semaphore_async() -> asyncio.Semaphore:
    global _async_semaphore, _async_limit

    max_concurrent = Config.METADATA_MAX_CONCURRENT if hasattr(Config, 'METADATA_MAX_CONCURRENT') else 64

    if _async_semaphore is None or _async_limit != max_concurrent:
        async with _async_lock:
            if _async_semaphore is None or _async_limit != max_concurrent:
                if _async_semaphore is not None:
                    logger.info(f"[Semaforo] metadata async recriado: {_async_limit} → {max_concurrent} requisicoes simultaneas")
                else:
                    logger.info(f"[Semaforo] metadata async criado com limite de {max_concurrent} requisicoes simultaneas")
                _async_semaphore = asyncio.Semaphore(max_concurrent)
                _async_limit = max_concurrent

    return _async_semaphore


@asynccontextmanager
async def metadata_slot_async(timeout=None):
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


__all__ = [
    'get_metadata_semaphore',
    'metadata_slot',
    'get_metadata_semaphore_async',
    'metadata_slot_async',
]
