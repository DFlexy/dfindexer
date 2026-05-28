# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import threading
import logging
import time
from contextlib import contextmanager
from app.config import Config

logger = logging.getLogger(__name__)

_metadata_semaphore = None
_semaphore_lock = threading.Lock()
_current_limit = None
_debug_enabled = True

_times_list = []
_times_lock = threading.Lock()

def get_metadata_semaphore():
    global _metadata_semaphore, _current_limit
    
    max_concurrent = Config.METADATA_MAX_CONCURRENT if hasattr(Config, 'METADATA_MAX_CONCURRENT') else 128
    
    if _metadata_semaphore is None or _current_limit != max_concurrent:
        with _semaphore_lock:
            if _metadata_semaphore is None or _current_limit != max_concurrent:
                if _metadata_semaphore is not None:
                    logger.info(f"[Semaforo] metadata recriado: {_current_limit} → {max_concurrent} requisicoes simultaneas")
                else:
                    logger.info(f"[Semaforo] metadata criado com limite de {max_concurrent} requisicoes simultaneas")
                _metadata_semaphore = threading.Semaphore(max_concurrent)
                _current_limit = max_concurrent
    
    return _metadata_semaphore

@contextmanager
def metadata_slot(timeout=None):
    """Context manager para adquirir e liberar slot de metadata automaticamente"""
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
            in_use_after = _current_limit - available_after
            
            with _times_lock:
                _times_list.append(elapsed)
                
                if in_use_after == 0 and len(_times_list) > 0:
                    avg_time = sum(_times_list) / len(_times_list)
                    min_time = min(_times_list)
                    max_time = max(_times_list)
                    total_requests = len(_times_list)
                    logger.debug(f"[Semaforo] Batch concluido: {total_requests} requisicoes | Tempo medio: {avg_time:.2f}s | Min: {min_time:.2f}s | Max: {max_time:.2f}s")
                    _times_list.clear()

def acquire_metadata_slot(timeout=None):
    """Adquire um slot no semáforo"""
    semaphore = get_metadata_semaphore()
    if timeout is not None:
        return semaphore.acquire(timeout=timeout)
    else:
        semaphore.acquire()
        return True

def release_metadata_slot():
    semaphore = get_metadata_semaphore()
    semaphore.release()

