# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from typing import List, Dict, Optional, Callable
from tracker import get_tracker_service
from magnet.metadata import fetch_metadata_from_itorrents
from magnet.parser import MagnetParser
from core.enrichers.enricher_common import (
    apply_date_fallback,
    apply_imdb_fallback,
    apply_size_fallback,
    build_tracker_log_id,
    bulk_get_cross_data,
    hydrate_torrent_from_cross_data,
    save_metadata_name_to_cross_data,
)

logger = logging.getLogger(__name__)

class TorrentEnricher:
    def __init__(self):
        self.tracker_service = get_tracker_service()
    
    def enrich(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None, scraper_name: Optional[str] = None) -> List[Dict]:
        if not torrents:
            return torrents
        
        if not skip_metadata:
            self._ensure_titles_complete(torrents, fetch_remote=False)
        
        if filter_func:
            torrents = [t for t in torrents if filter_func(t)]
        
        if not torrents:
            return torrents
        
        if not skip_metadata:
            self._current_scraper_name = scraper_name
            self._ensure_titles_complete(torrents, fetch_remote=True)
        
        from concurrent.futures import ThreadPoolExecutor
        
        metadata_future = None
        tracker_future = None
        
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="enrich") as pool:
            if not skip_metadata:
                metadata_future = pool.submit(self._fetch_metadata_batch, torrents)
            
            if not skip_trackers:
                tracker_future = pool.submit(self._attach_peers, torrents)
            
            if metadata_future:
                try:
                    metadata_future.result(timeout=45)
                except Exception:
                    pass
                finally:
                    if hasattr(self, '_current_scraper_name'):
                        delattr(self, '_current_scraper_name')
            
            if tracker_future:
                try:
                    tracker_future.result(timeout=60)
                except Exception:
                    pass
        
        apply_size_fallback(torrents, skip_metadata=skip_metadata)
        apply_date_fallback(torrents, skip_metadata=skip_metadata)
        apply_imdb_fallback(torrents)

        if not skip_metadata:
            self._resolve_magnet_display_names(torrents)
        
        return torrents
    
    def _resolve_magnet_display_names(self, torrents: List[Dict]) -> None:
        from utils.text.storage import (
            magnet_original_needs_raw_name,
            resolve_magnet_original_for_torrent,
        )
        for torrent in torrents:
            current = (torrent.get('magnet_original') or '').strip()
            processed = (torrent.get('magnet_processed') or '').strip()
            if magnet_original_needs_raw_name(current, processed):
                resolve_magnet_original_for_torrent(torrent, fetch_remote=True)
    
    def _ensure_titles_complete(self, torrents: List[Dict], fetch_remote: bool = True) -> None:
        from utils.text.storage import (
            resolve_magnet_original_for_torrent,
            torrent_needs_metadata_title_upgrade,
            upgrade_torrent_title_from_metadata,
        )
        from cache.metadata_cache import MetadataCache

        metadata_cache = MetadataCache()
        cross_data_by_hash = bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )
        
        for torrent in torrents:
            info_hash = torrent.get('info_hash')
            if info_hash:
                try:
                    cross_data = cross_data_by_hash.get(str(info_hash).lower())
                    hydrate_torrent_from_cross_data(torrent, cross_data)
                except Exception:
                    pass
                resolve_magnet_original_for_torrent(torrent, fetch_remote=fetch_remote)

            if torrent_needs_metadata_title_upgrade(torrent) and info_hash:
                try:
                    metadata = metadata_cache.get(info_hash.lower())
                    if fetch_remote and (not metadata or not metadata.get('name')):
                        scraper_name = getattr(self, '_current_scraper_name', None)
                        title_for_log = (
                            torrent.get('title_processed')
                            or torrent.get('original_title')
                            or torrent.get('title_translated_processed')
                            or torrent.get('magnet_processed')
                            or None
                        )
                        metadata = fetch_metadata_from_itorrents(
                            info_hash, scraper_name=scraper_name, title=title_for_log
                        )
                    if metadata and metadata.get('name'):
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                        upgrade_torrent_title_from_metadata(torrent, metadata)
                        torrent['magnet_original'] = str(metadata['name']).strip()
                except Exception:
                    pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.concurrency.metadata_semaphore import metadata_slot
        from utils.text.storage import magnet_original_needs_raw_name, can_skip_metadata_fetch
        from cache.metadata_cache import MetadataCache
        
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

        metadata_cache = MetadataCache()
        cross_data_by_hash = bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents_to_fetch]
        )
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
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
            
            with metadata_slot():
                try:
                    scraper_name = getattr(self, '_current_scraper_name', None)
                    title = (torrent.get('title_processed') or 
                            torrent.get('original_title') or 
                            torrent.get('title_translated_processed') or
                            torrent.get('magnet_processed') or
                            None)
                    metadata = fetch_metadata_from_itorrents(info_hash, scraper_name=scraper_name, title=title)
                    return (torrent, metadata)
                except Exception:
                    return (torrent, None)

        def apply_metadata(torrent: Dict, metadata: Optional[Dict]) -> None:
            if not metadata:
                return
            from utils.text.storage import upgrade_torrent_title_from_metadata
            torrent['_metadata'] = metadata
            torrent['_metadata_fetched'] = True
            upgrade_torrent_title_from_metadata(torrent, metadata)
            if metadata.get('name'):
                torrent['magnet_original'] = str(metadata['name']).strip()
            save_metadata_name_to_cross_data(torrent, metadata)
        
        if len(torrents_to_fetch) > 1:
            max_workers = min(16, len(torrents_to_fetch))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_torrent = {
                    executor.submit(fetch_metadata_for_torrent, t): t
                    for t in torrents_to_fetch
                }
                
                for future in as_completed(future_to_torrent):
                    try:
                        torrent, metadata = future.result(timeout=10)
                        apply_metadata(torrent, metadata)
                    except Exception:
                        pass
        else:
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    apply_metadata(torrent, metadata)
                except Exception:
                    pass
    
    def _attach_peers(self, torrents: List[Dict]) -> None:
        from utils.parsing.magnet_utils import extract_trackers_from_magnet
        from utils.text.cross_data import save_cross_data_to_redis
        
        scraper_name = getattr(self, '_current_scraper_name', None)
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
            
            cross_data = cross_data_by_hash.get(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
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
                log_id_by_hash[info_hash] = build_tracker_log_id(torrent, scraper_name, info_hash)
        
        if not infohash_map:
            return
        
        try:
            from cache.tracker_cache import TrackerCache
            tracker_cache = TrackerCache()
            peers_map = self.tracker_service.get_peers_bulk(infohash_map)
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
                
                try:
                    if not tracker_cache.get(info_hash):
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
    
    def _save_metadata_name_to_cross_data(self, torrent: Dict, metadata: Dict) -> None:
        save_metadata_name_to_cross_data(torrent, metadata)
