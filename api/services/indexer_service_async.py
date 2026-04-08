"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import asyncio
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import List, Dict, Optional, Callable, Tuple
from app.config import Config
from scraper import (
    create_scraper,
    available_scraper_types,
    normalize_scraper_type,
)
from cache import cleanup_request_caches
from core.enrichers.torrent_enricher_async import TorrentEnricherAsync
from core.filters.query_filter import QueryFilter
from core.processors.torrent_processor import TorrentProcessor

logger = logging.getLogger(__name__)

SCRAPER_NUMBER_MAP = {
    "1": "starck",
    "2": "rede",
    "3": "xfilmes",
    "4": "tfilme",
    "5": None,
    "6": "comand",
    "7": "bludv",
    "8": "portal",
}


def get_valid_scraper_ids() -> Dict[str, str]:
    """Retorna apenas os IDs válidos do mapeamento."""
    return {k: v for k, v in SCRAPER_NUMBER_MAP.items() if v is not None}


class IndexerServiceAsync:
    def __init__(self):
        self.enricher = TorrentEnricherAsync()
        self.processor = TorrentProcessor()
    
    async def search(
        self,
        scraper_type: str,
        query: str,
        use_flaresolverr: bool = False,
        filter_results: bool = False,
        max_results: Optional[int] = None
    ) -> tuple[List[Dict], Optional[Dict]]:
        """
        Busca torrents por query (async).
        
        Nota: Por enquanto, os scrapers ainda são síncronos.
        Apenas o enriquecimento é async.
        """
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        try:
            filter_func = None
            if query:
                filter_func = QueryFilter.create_filter(query)
            
            torrents = await asyncio.to_thread(
                scraper.search, query, filter_func=filter_func, skip_trackers=True
            )
            
            if max_results and max_results > 0:
                torrents = torrents[:max_results]
            
            enriched_torrents, filter_stats = await self._enrich_torrents_async(
                torrents,
                scraper_type,
                filter_func
            )
            
            if filter_stats is None and filter_func and enriched_torrents:
                total_before_filter = len(enriched_torrents)
                filtered_count = sum(1 for t in enriched_torrents if not filter_func(t))
                approved_count = total_before_filter - filtered_count
                
                filter_stats = {
                    'total': total_before_filter,
                    'filtered': filtered_count,
                    'approved': approved_count,
                    'scraper_name': scraper.SCRAPER_TYPE if hasattr(scraper, 'SCRAPER_TYPE') else ''
                }
            
            self.processor.sanitize_torrents(enriched_torrents)
            self.processor.remove_internal_fields(enriched_torrents)
            self.processor.sort_by_date(enriched_torrents)
            
            return enriched_torrents, filter_stats
        finally:
            scraper.close()
            cleanup_request_caches()
    
    async def get_page(
        self,
        scraper_type: str,
        page: str = '1',
        use_flaresolverr: bool = False,
        is_test: bool = False,
        max_results: Optional[int] = None
    ) -> tuple[List[Dict], Optional[Dict]]:
        """Obtém torrents de uma página (async)."""
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        try:
            max_links = None
            if is_test:
                max_links = Config.EMPTY_QUERY_MAX_LINKS if Config.EMPTY_QUERY_MAX_LINKS > 0 else None
            
            torrents = await asyncio.to_thread(
                scraper.get_page, page, max_items=max_links, is_test=is_test
            )
            
            if max_results and max_results > 0:
                torrents = torrents[:max_results]
            
            enriched_torrents, filter_stats = await self._enrich_torrents_async(
                torrents,
                scraper_type,
                None,
                is_test=is_test
            )
            
            self.processor.sanitize_torrents(enriched_torrents)
            self.processor.remove_internal_fields(enriched_torrents)
            
            if not (is_test and Config.EMPTY_QUERY_MAX_LINKS > 0):
                self.processor.sort_by_date(enriched_torrents)
            
            return enriched_torrents, filter_stats
        finally:
            scraper.close()
            cleanup_request_caches()
    
    async def _enrich_torrents_async(
        self,
        torrents: List[Dict],
        scraper_type: str,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        is_test: bool = False
    ) -> tuple[List[Dict], Optional[Dict]]:
        """Enriquece torrents usando enricher async e retorna estatísticas."""
        from scraper import available_scraper_types
        
        scraper_name = None
        types_info = available_scraper_types()
        normalized_type = scraper_type.lower().strip()
        if normalized_type in types_info:
            scraper_name = types_info[normalized_type].get('display_name', scraper_type)
        else:
            scraper_name = scraper_type
        
        skip_metadata = False
        skip_trackers = False
        
        if is_test:
            skip_metadata = True
            skip_trackers = True
        
        # Enriquece e recebe estatísticas diretamente do retorno (evita race condition)
        enriched, filter_stats = await self.enricher.enrich(
            torrents,
            skip_metadata=skip_metadata,
            skip_trackers=skip_trackers,
            filter_func=filter_func,
            scraper_name=scraper_name
        )
        
        return enriched, filter_stats
    
    def get_scraper_info(self) -> Dict:
        """Obtém informações dos scrapers disponíveis."""
        types_info = available_scraper_types()
        sites_dict = {
            scraper_type: meta.get('default_url')
            for scraper_type, meta in types_info.items()
            if meta.get('default_url')
        }
        
        return {
            'configured_sites': sites_dict,
            'available_types': list(types_info.keys()),
            'types_info': types_info
        }
    
    def validate_scraper_type(self, scraper_type: str) -> tuple[bool, Optional[str]]:
        """Valida tipo de scraper e retorna tipo normalizado."""
        if scraper_type in SCRAPER_NUMBER_MAP:
            mapped_type = SCRAPER_NUMBER_MAP[scraper_type]
            if mapped_type is None:
                return False, None
            scraper_type = mapped_type
        
        types_info = available_scraper_types()
        normalized_type = normalize_scraper_type(scraper_type)
        
        if normalized_type not in types_info:
            return False, None
        
        return True, normalized_type
    
    async def close(self):
        """Fecha recursos async."""
        await self.enricher.close()


# Event loop persistente em thread dedicada para operações async.
# Evita criar/destruir event loops a cada requisição (que causa vazamento
# de sessões aiohttp e conexões TCP órfãs).
_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_loop_thread: Optional[threading.Thread] = None
_async_loop_lock = threading.Lock()


def _get_async_loop() -> asyncio.AbstractEventLoop:
    """Obtém o event loop persistente, criando-o se necessário."""
    global _async_loop, _async_loop_thread
    if _async_loop is not None and not _async_loop.is_closed():
        return _async_loop
    with _async_loop_lock:
        if _async_loop is not None and not _async_loop.is_closed():
            return _async_loop
        _async_loop = asyncio.new_event_loop()
        _async_loop_thread = threading.Thread(
            target=_async_loop.run_forever,
            daemon=True,
            name="async-loop"
        )
        _async_loop_thread.start()
    return _async_loop


def run_async(coro):
    """Executa corrotina no event loop persistente (thread-safe)."""
    loop = _get_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    timeout = getattr(Config, 'RUN_ASYNC_TIMEOUT', None)
    try:
        if timeout is not None and timeout > 0:
            return future.result(timeout=timeout)
        return future.result()
    except FuturesTimeoutError:
        logger.error(
            'Timeout ao aguardar operação async (RUN_ASYNC_TIMEOUT=%ss)',
            timeout,
        )
        raise


async def fetch_all_scrapers_index(
    scraper_types: List[str],
    query: str,
    page: str,
    use_flaresolverr: bool,
    filter_results: bool,
    max_results: Optional[int],
    page_mode: bool,
    is_prowlarr_test: bool,
) -> Tuple[List[Dict], List[Optional[Dict]], List[Tuple[str, List[Dict], Optional[Dict]]]]:
    """
    Busca em todos os scrapers em paralelo (com limite de concorrência).
    Cada tarefa usa IndexerServiceAsync próprio para não compartilhar enricher entre corrotinas.
    Retorna (lista agregada, stats agregados, linhas por scraper para logging).
    """
    types_info = available_scraper_types()
    max_conc = getattr(Config, 'ALL_SCRAPERS_MAX_CONCURRENT', 4) or 1
    sem = asyncio.Semaphore(max_conc)

    async def run_one(st: str) -> Tuple[str, List[Dict], Optional[Dict]]:
        label = types_info.get(st, {}).get('display_name', st)
        logger.info('[TODOS] Buscando em [%s]...', label)
        svc = IndexerServiceAsync()
        try:
            async with sem:
                if page_mode:
                    t, s = await svc.get_page(
                        st, page, use_flaresolverr, is_prowlarr_test, max_results=max_results
                    )
                else:
                    t, s = await svc.search(
                        st, query, use_flaresolverr, filter_results, max_results=max_results
                    )
        except Exception as e:
            logger.warning('[TODOS] Erro ao buscar em [%s]: %s', st, e)
            return (st, [], None)
        finally:
            await svc.close()
        return (st, t or [], s)

    rows: List[Tuple[str, List[Dict], Optional[Dict]]] = list(
        await asyncio.gather(*[run_one(st) for st in scraper_types])
    )

    all_torrents: List[Dict] = []
    all_filter_stats: List[Optional[Dict]] = []
    for _st, t, s in rows:
        if t:
            all_torrents.extend(t)
        if s:
            all_filter_stats.append(s)

    return all_torrents, all_filter_stats, rows

