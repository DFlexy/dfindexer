# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import asyncio
from typing import List, Dict, Optional, Callable, Any
from app.config import Config
from tracker import get_tracker_service
from magnet.metadata_async import fetch_metadata_from_itorrents_async
from magnet.parser import MagnetParser
from utils.http.proxy import get_aiohttp_proxy_connector
from core.enrichers.enricher_common import (
    apply_date_fallback,
    apply_imdb_fallback,
    apply_size_fallback,
    build_tracker_log_id,
    bulk_get_cross_data,
    hydrate_torrent_from_cross_data,
    save_metadata_name_to_cross_data,
)
import aiohttp

logger = logging.getLogger(__name__)

class TorrentEnricherAsync:
    def __init__(self):
        self.tracker_service = get_tracker_service()
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=5)
            proxy_connector = get_aiohttp_proxy_connector()
            if proxy_connector:
                connector = proxy_connector
            else:
                connector = aiohttp.TCPConnector(limit=30, limit_per_host=10)
            
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': 'TorrentMetadataService/1.0',
                    'Accept-Encoding': 'gzip',
                }
            )
        return self._session
    
    async def close(self):
        if self._session is not None:
            if not self._session.closed:
                await self._session.close()
            self._session = None

    def _bulk_get_cross_data(self, info_hashes: List[str]) -> Dict[str, Dict[str, Any]]:
        return bulk_get_cross_data(info_hashes)
    
    async def enrich(
        self,
        torrents: List[Dict],
        skip_metadata: bool = False,
        skip_trackers: bool = False,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        scraper_name: Optional[str] = None
    ) -> tuple[List[Dict], Optional[Dict]]:
        """Enriquece lista de torrents com metadata e trackers (async). Retorna (torrents, filter_stats)."""
        if not torrents:
            return torrents, None
        
        # Antes do filtro: só Redis/cross_data/cache local (sem HTTP no iTorrents).
        if not skip_metadata:
            await self._ensure_titles_complete(torrents, fetch_remote=False)
        
        total_before_filter = len(torrents)
        if filter_func:
            torrents = [t for t in torrents if filter_func(t)]
            filtered_count = total_before_filter - len(torrents)
            approved_count = len(torrents)
        else:
            filtered_count = 0
            approved_count = len(torrents)
        
        filter_stats = {
            'total': total_before_filter,
            'filtered': filtered_count,
            'approved': approved_count,
            'scraper_name': scraper_name
        }
        
        if not torrents:
            return torrents, filter_stats
        
        # Depois do filtro: metadata remota só para aprovados (DN incompleto, size, etc.).
        if not skip_metadata:
            self._current_scraper_name = scraper_name
            try:
                await self._ensure_titles_complete(torrents, fetch_remote=True)
                await self._fetch_metadata_batch(torrents)
            finally:
                if hasattr(self, '_current_scraper_name'):
                    delattr(self, '_current_scraper_name')
        
        # Uma única viagem ao Redis para os fallbacks e trackers.
        cross_data_by_hash = bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )
        apply_size_fallback(torrents, skip_metadata=skip_metadata, cross_data_by_hash=cross_data_by_hash)
        apply_date_fallback(torrents, skip_metadata=skip_metadata)
        apply_imdb_fallback(torrents)
        
        if not skip_trackers:
            await self._attach_peers(torrents, cross_data_by_hash=cross_data_by_hash)

        if not skip_metadata:
            await self._resolve_magnet_display_names(torrents)
        
        return torrents, filter_stats
    
    async def _resolve_magnet_display_names(self, torrents: List[Dict]) -> None:
        from utils.text.storage import (
            magnet_original_needs_raw_name,
            resolve_magnet_original_for_torrent,
        )
        still_need: List[Dict] = []
        for torrent in torrents:
            current = (torrent.get('magnet_original') or '').strip()
            processed = (torrent.get('magnet_processed') or '').strip()
            if not magnet_original_needs_raw_name(current, processed):
                continue
            if resolve_magnet_original_for_torrent(torrent, fetch_remote=True):
                continue
            if torrent.get('magnet_link') and not torrent.get('_metadata_fetched'):
                still_need.append(torrent)
            elif torrent.get('_metadata', {}).get('name'):
                torrent['magnet_original'] = str(torrent['_metadata']['name']).strip()

        if not still_need:
            return

        session = await self._get_session()
        worker_limit = min(16, max(4, len(still_need)))
        scraper_name = getattr(self, '_current_scraper_name', None)

        async def fetch_one(torrent: Dict) -> None:
            info_hash = str(torrent.get('info_hash') or '').lower()
            if not info_hash:
                return
            try:
                from utils.concurrency.metadata_semaphore_async import metadata_slot_async
                async with metadata_slot_async():
                    title = (
                        torrent.get('title_processed')
                        or torrent.get('original_title')
                        or torrent.get('title_translated_processed')
                        or torrent.get('magnet_processed')
                    )
                    metadata = await fetch_metadata_from_itorrents_async(
                        session, info_hash, scraper_name=scraper_name, title=title
                    )
                if metadata and metadata.get('name'):
                    torrent['_metadata'] = metadata
                    torrent['_metadata_fetched'] = True
                    torrent['magnet_original'] = str(metadata['name']).strip()
                    save_metadata_name_to_cross_data(torrent, metadata)
            except Exception:
                pass

        for i in range(0, len(still_need), worker_limit):
            chunk = still_need[i:i + worker_limit]
            await asyncio.gather(*(fetch_one(t) for t in chunk), return_exceptions=True)
    
    async def _ensure_titles_complete(
        self,
        torrents: List[Dict],
        fetch_remote: bool = True,
    ) -> None:
        """Hidrata títulos via Redis/cache; opcionalmente busca iTorrents (fetch_remote)."""
        from cache.metadata_cache import MetadataCache
        from utils.text.storage import (
            resolve_magnet_original_for_torrent,
            torrent_needs_metadata_title_upgrade,
            upgrade_torrent_title_from_metadata,
        )
        
        metadata_cache = MetadataCache()
        cross_data_by_hash = bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )
        to_upgrade: List[Dict] = []
        
        for torrent in torrents:
            info_hash = str(torrent.get('info_hash') or '').lower()
            hydrate_torrent_from_cross_data(torrent, cross_data_by_hash.get(info_hash))

            if info_hash:
                resolve_magnet_original_for_torrent(torrent, fetch_remote=fetch_remote)

            if not (info_hash and len(info_hash) == 40):
                continue
            if not torrent_needs_metadata_title_upgrade(torrent):
                continue
            try:
                cached_metadata = metadata_cache.get(info_hash)
            except Exception:
                cached_metadata = None
            if cached_metadata and cached_metadata.get('name'):
                torrent['_metadata'] = cached_metadata
                torrent['_metadata_fetched'] = True
                upgrade_torrent_title_from_metadata(torrent, cached_metadata)
                torrent['magnet_original'] = str(cached_metadata['name']).strip()
                continue
            if fetch_remote:
                to_upgrade.append(torrent)

        if not fetch_remote or not to_upgrade:
            return

        session = await self._get_session()
        worker_limit = min(24, max(4, int(getattr(Config, 'METADATA_MAX_CONCURRENT', 32) / 4)))

        async def upgrade_one(torrent: Dict) -> None:
            info_hash = str(torrent.get('info_hash') or '').lower()
            if not info_hash:
                return
            try:
                scraper_name = getattr(self, '_current_scraper_name', None)
                title_for_log = (
                    torrent.get('title_processed')
                    or torrent.get('original_title')
                    or torrent.get('title_translated_processed')
                    or torrent.get('magnet_processed')
                    or None
                )
                metadata = await fetch_metadata_from_itorrents_async(
                    session, info_hash, scraper_name=scraper_name, title=title_for_log
                )
                if metadata and metadata.get('name'):
                    torrent['_metadata'] = metadata
                    torrent['_metadata_fetched'] = True
                    upgrade_torrent_title_from_metadata(torrent, metadata)
                    torrent['magnet_original'] = str(metadata['name']).strip()
            except Exception:
                pass

        for i in range(0, len(to_upgrade), worker_limit):
            chunk = to_upgrade[i:i + worker_limit]
            await asyncio.gather(*(upgrade_one(t) for t in chunk), return_exceptions=True)
    
    async def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        from utils.concurrency.metadata_semaphore_async import metadata_slot_async
        from cache.metadata_cache import MetadataCache
        from utils.text.storage import magnet_original_needs_raw_name, can_skip_metadata_fetch
        
        session = await self._get_session()
        metadata_cache = MetadataCache()
        
        torrents_to_fetch = [
            t for t in torrents
            if t.get('magnet_link') and (
                not t.get('_metadata_fetched')
                or magnet_original_needs_raw_name(
                    t.get('magnet_original') or '',
                    t.get('magnet_processed') or '',
                )
            )
        ]
        
        if not torrents_to_fetch:
            return

        cross_data_by_hash = bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents_to_fetch]
        )
        
        async def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            info_hash = torrent.get('info_hash')
            if not info_hash:
                try:
                    magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                    info_hash = magnet_data.get('info_hash')
                except Exception:
                    return (torrent, None)
            
            if not info_hash:
                return (torrent, None)
            
            try:
                cross_data = cross_data_by_hash.get(str(info_hash).lower())
                if can_skip_metadata_fetch(torrent, cross_data):
                    return (torrent, None)
            except Exception:
                pass
            
            try:
                cached_metadata = metadata_cache.get(info_hash.lower())
                if cached_metadata:
                    return (torrent, cached_metadata)
            except Exception:
                pass
            
            async with metadata_slot_async():
                try:
                    scraper_name = getattr(self, '_current_scraper_name', None)
                    title = (torrent.get('title_processed') or 
                            torrent.get('original_title') or 
                            torrent.get('title_translated_processed') or
                            torrent.get('magnet_processed') or
                            None)
                    metadata = await fetch_metadata_from_itorrents_async(session, info_hash, scraper_name=scraper_name, title=title)
                    return (torrent, metadata)
                except Exception:
                    return (torrent, None)
        
        worker_limit = min(32, max(4, int(getattr(Config, 'METADATA_MAX_CONCURRENT', 32) / 4)))
        for i in range(0, len(torrents_to_fetch), worker_limit):
            chunk = torrents_to_fetch[i:i + worker_limit]
            results = await asyncio.gather(
                *(fetch_metadata_for_torrent(t) for t in chunk),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    continue
                if isinstance(result, tuple):
                    torrent, metadata = result
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                        from utils.text.storage import upgrade_torrent_title_from_metadata
                        upgrade_torrent_title_from_metadata(torrent, metadata)
                        if metadata.get('name'):
                            torrent['magnet_original'] = str(metadata['name']).strip()
                        save_metadata_name_to_cross_data(torrent, metadata)
    
    async def _attach_peers(
        self,
        torrents: List[Dict],
        cross_data_by_hash: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Anexa dados de peers (seeds/leechers) via trackers (async)."""
        from utils.parsing.magnet_utils import extract_trackers_from_magnet
        from utils.text.cross_data import save_cross_data_to_redis
        
        scraper_name = getattr(self, '_current_scraper_name', None)
        if cross_data_by_hash is None:
            cross_data_by_hash = bulk_get_cross_data(
                [str(t.get('info_hash') or '').lower() for t in torrents]
            )
        
        infohash_map = {}
        log_id_by_hash = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            log_id = build_tracker_log_id(torrent, scraper_name, info_hash)
            
            cross_data = cross_data_by_hash.get(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
                    logger.debug(f"[Tracker] Buscando: {log_id} → (S:{tracker_seed} L:{tracker_leech}) cache")
                    continue
            
            trackers = torrent.get('trackers') or []
            
            if not trackers:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    trackers = extract_trackers_from_magnet(magnet_link)
            
            if trackers:
                unique_trackers = list(dict.fromkeys(trackers))
                infohash_map.setdefault(info_hash, [])
                infohash_map[info_hash].extend(unique_trackers)
                log_id_by_hash[info_hash] = log_id
        
        if not infohash_map:
            return
        
        try:
            peers_map = await asyncio.to_thread(self.tracker_service.get_peers_bulk, infohash_map)
            tracker_cache = None
            try:
                from cache.tracker_cache import TrackerCache
                tracker_cache = TrackerCache()
            except Exception:
                tracker_cache = None
            for torrent in torrents:
                info_hash = (torrent.get('info_hash') or '').lower()
                if not info_hash or len(info_hash) != 40:
                    continue
                
                leech_seed = peers_map.get(info_hash)
                if not leech_seed:
                    if info_hash in log_id_by_hash:
                        logger.debug(f"[Tracker] Buscando: {log_id_by_hash[info_hash]} → Não encontrado")
                    continue
                leech, seed = leech_seed
                torrent['leech_count'] = leech
                torrent['seed_count'] = seed
                
                if tracker_cache:
                    try:
                        cached = tracker_cache.get(info_hash)
                        if not cached:
                            tracker_cache.set(info_hash, {"leech": leech, "seed": seed})
                    except Exception:
                        pass
                
                saved_to_redis = False
                try:
                    save_cross_data_to_redis(info_hash, {
                        'tracker_seed': seed,
                        'tracker_leech': leech,
                    })
                    saved_to_redis = True
                except Exception:
                    pass
                
                log_id = build_tracker_log_id(torrent, scraper_name, info_hash)
                if saved_to_redis:
                    logger.debug(f"[Tracker] Buscando: {log_id} → (S:{seed} L:{leech}) Salvo no Redis")
                else:
                    logger.debug(f"[Tracker] Buscando: {log_id} → (S:{seed} L:{leech}) Scrape realizado (erro ao salvar no Redis)")
        except Exception:
            pass
    
    async def _save_metadata_name_to_cross_data(self, torrent: Dict, metadata: Dict) -> None:
        save_metadata_name_to_cross_data(torrent, metadata)
