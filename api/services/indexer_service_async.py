# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import copy
import logging
import asyncio
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import List, Dict, Optional, Callable, Tuple
from app.config import Config
from scraper import create_scraper, available_scraper_types
from cache import cleanup_request_caches
from core.enrichers.torrent_enricher_async import TorrentEnricherAsync
from core.filters.query_filter import QueryFilter
from core.processors.torrent_processor import TorrentProcessor
from api.services.indexer_common import get_scraper_info, validate_scraper_type

logger = logging.getLogger(__name__)

# Cache + coalesce de buscas idênticas (Sonarr/Prowlarr reenvia a mesma q).
_search_cache_lock = threading.Lock()
_search_result_cache: Dict[Tuple, Tuple[float, List[Dict], Optional[Dict]]] = {}
_search_inflight: Dict[Tuple, asyncio.Future] = {}


def _normalize_search_query(query: str) -> str:
    return ' '.join((query or '').lower().split())


def _search_cache_key(
    scraper_type: str,
    query: str,
    use_flaresolverr: bool,
    filter_results: bool,
    max_results: Optional[int],
) -> Tuple:
    return (
        (scraper_type or '').lower().strip(),
        _normalize_search_query(query),
        bool(use_flaresolverr),
        bool(filter_results),
        max_results if max_results and max_results > 0 else None,
    )


def _clone_search_result(
    torrents: List[Dict],
    filter_stats: Optional[Dict],
) -> Tuple[List[Dict], Optional[Dict]]:
    return copy.deepcopy(torrents or []), copy.deepcopy(filter_stats) if filter_stats else None


def _get_cached_search(key: Tuple) -> Optional[Tuple[List[Dict], Optional[Dict]]]:
    ttl = getattr(Config, 'SEARCH_RESULT_CACHE_TTL', 0) or 0
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _search_cache_lock:
        entry = _search_result_cache.get(key)
        if not entry:
            return None
        expires_at, torrents, stats = entry
        if expires_at <= now:
            _search_result_cache.pop(key, None)
            return None
        return _clone_search_result(torrents, stats)


def _store_cached_search(
    key: Tuple,
    torrents: List[Dict],
    filter_stats: Optional[Dict],
) -> None:
    ttl = getattr(Config, 'SEARCH_RESULT_CACHE_TTL', 0) or 0
    if ttl <= 0:
        return
    with _search_cache_lock:
        _search_result_cache[key] = (
            time.monotonic() + ttl,
            copy.deepcopy(torrents or []),
            copy.deepcopy(filter_stats) if filter_stats else None,
        )


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
        ttl = getattr(Config, 'SEARCH_RESULT_CACHE_TTL', 0) or 0
        if ttl <= 0 or not (query or '').strip():
            return await self._search_uncached(
                scraper_type, query, use_flaresolverr, filter_results, max_results
            )

        key = _search_cache_key(
            scraper_type, query, use_flaresolverr, filter_results, max_results
        )
        cached = _get_cached_search(key)
        if cached is not None:
            logger.info(
                '[SearchCache] HIT scraper=%s query=%r results=%s',
                scraper_type,
                query,
                len(cached[0]),
            )
            return cached

        loop = asyncio.get_running_loop()
        leader = False
        inflight: Optional[asyncio.Future] = None
        with _search_cache_lock:
            cached_entry = _search_result_cache.get(key)
            if cached_entry and cached_entry[0] > time.monotonic():
                return _clone_search_result(cached_entry[1], cached_entry[2])
            existing = _search_inflight.get(key)
            if existing is not None and not existing.done():
                inflight = existing
            else:
                inflight = loop.create_future()
                _search_inflight[key] = inflight
                leader = True

        if not leader:
            logger.info(
                '[SearchCache] COALESCE scraper=%s query=%r',
                scraper_type,
                query,
            )
            torrents, stats = await asyncio.shield(inflight)
            return _clone_search_result(torrents, stats)

        try:
            result = await self._search_uncached(
                scraper_type, query, use_flaresolverr, filter_results, max_results
            )
            _store_cached_search(key, result[0], result[1])
            if not inflight.done():
                inflight.set_result(_clone_search_result(result[0], result[1]))
            return result
        except Exception as exc:
            if not inflight.done():
                inflight.set_exception(exc)
            raise
        finally:
            with _search_cache_lock:
                if _search_inflight.get(key) is inflight:
                    _search_inflight.pop(key, None)

    async def _search_uncached(
        self,
        scraper_type: str,
        query: str,
        use_flaresolverr: bool = False,
        filter_results: bool = False,
        max_results: Optional[int] = None
    ) -> tuple[List[Dict], Optional[Dict]]:
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)

        try:
            filter_func = None
            if filter_results and query:
                filter_func = QueryFilter.create_filter(query)

            torrents = await asyncio.to_thread(
                scraper.search,
                query,
                filter_func=None,
                skip_trackers=True,
                skip_metadata=True,
            )
            torrents = self._dedupe_by_info_hash(torrents)

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
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        try:
            max_links = None
            if is_test:
                max_links = Config.EMPTY_QUERY_MAX_LINKS if Config.EMPTY_QUERY_MAX_LINKS > 0 else None
            
            torrents = await asyncio.to_thread(
                scraper.get_page, page, max_items=max_links, is_test=is_test
            )
            torrents = self._dedupe_by_info_hash(torrents)
            
            if max_results and max_results > 0:
                torrents = torrents[:max_results]
            
            # get_page já retorna itens enriquecidos no caminho sync do scraper.
            # Evita segunda rodada de metadata/trackers no serviço async.
            enriched_torrents = torrents
            filter_stats = None

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
        

        enriched, filter_stats = await self.enricher.enrich(
            torrents,
            skip_metadata=skip_metadata,
            skip_trackers=skip_trackers,
            filter_func=filter_func,
            scraper_name=scraper_name
        )
        
        return enriched, filter_stats

    @staticmethod
    def _dedupe_by_info_hash(torrents: List[Dict]) -> List[Dict]:
        seen_hashes = set()
        deduped: List[Dict] = []
        for torrent in torrents or []:
            info_hash = str(torrent.get('info_hash') or '').strip().lower()
            if info_hash and len(info_hash) == 40:
                if info_hash in seen_hashes:
                    continue
                seen_hashes.add(info_hash)
            deduped.append(torrent)
        return deduped
    
    get_scraper_info = staticmethod(get_scraper_info)
    validate_scraper_type = staticmethod(validate_scraper_type)

    async def close(self):
        await self.enricher.close()

_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_loop_thread: Optional[threading.Thread] = None
_async_loop_lock = threading.Lock()

def _get_async_loop() -> asyncio.AbstractEventLoop:
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

