# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from typing import List, Dict, Optional, Callable
from tracker import get_tracker_service
from magnet.metadata import fetch_metadata_from_itorrents
from magnet.parser import MagnetParser
from utils.text.utils import format_bytes

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
        
        from concurrent.futures import ThreadPoolExecutor, wait
        
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
        
        self._apply_size_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_date_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_imdb_fallback(torrents)
        
        return torrents
    
    def _ensure_titles_complete(self, torrents: List[Dict], fetch_remote: bool = True) -> None:
        from utils.text.cross_data import get_cross_data_from_redis
        
        for torrent in torrents:
            info_hash = torrent.get('info_hash')
            if info_hash:
                try:
                    cross_data = get_cross_data_from_redis(info_hash)
                    if cross_data:
                        if not torrent.get('original_title') and cross_data.get('title_original_html'):
                            torrent['original_title'] = cross_data.get('title_original_html', '')
                        if not torrent.get('title_translated_processed') and cross_data.get('title_translated_html'):
                            torrent['title_translated_processed'] = cross_data.get('title_translated_html', '')
                        if cross_data.get('magnet_processed'):
                            torrent['magnet_processed'] = cross_data.get('magnet_processed')
                except Exception:
                    pass
            
            from utils.text.storage import (
                torrent_needs_metadata_title_upgrade,
                upgrade_torrent_title_from_metadata,
            )

            if torrent_needs_metadata_title_upgrade(torrent) and info_hash:
                try:
                    from cache.metadata_cache import MetadataCache
                    metadata_cache = MetadataCache()
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
                except Exception:
                    pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.concurrency.metadata_semaphore import metadata_slot
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            info_hash = torrent.get('info_hash')
            if not info_hash:
                try:
                    from magnet.parser import MagnetParser
                    magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                    info_hash = magnet_data.get('info_hash')
                except Exception:
                    return (torrent, None)
            
            if not info_hash:
                return (torrent, None)
                
            try:
                from utils.text.cross_data import get_cross_data_from_redis
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data:
                    has_release_title = cross_data.get('magnet_processed')
                    has_size = cross_data.get('size')
                    if has_release_title and has_size:
                        return (torrent, None)
            except Exception:
                pass
            
            try:
                from cache.metadata_cache import MetadataCache
                metadata_cache = MetadataCache()
                cached_metadata = metadata_cache.get(info_hash.lower())
                if cached_metadata:
                    return (torrent, cached_metadata)
            except Exception:
                pass
            
            from utils.concurrency.metadata_semaphore import metadata_slot
            with metadata_slot():
                try:
                    from magnet.metadata import fetch_metadata_from_itorrents
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
                        if metadata:
                            torrent['_metadata'] = metadata
                            torrent['_metadata_fetched'] = True
                            from utils.text.storage import upgrade_torrent_title_from_metadata
                            upgrade_torrent_title_from_metadata(torrent, metadata)
                            self._save_metadata_name_to_cross_data(torrent, metadata)
                    except Exception:
                        pass
        else:
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                        from utils.text.storage import upgrade_torrent_title_from_metadata
                        upgrade_torrent_title_from_metadata(torrent, metadata)
                        self._save_metadata_name_to_cross_data(torrent, metadata)
                except Exception:
                    pass
    
    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        metadata_enabled = not skip_metadata
        
        for torrent in torrents:
            html_size = torrent.get('size', '')
            info_hash = torrent.get('info_hash', '').lower()
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            

            if info_hash and len(info_hash) == 40:
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data and cross_data.get('size'):
                    cross_size = cross_data.get('size')
                    if cross_size and cross_size.strip() and cross_size != 'N/A':
                        torrent['size'] = cross_size.strip()
                        continue
            
            magnet_data = None
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                pass
            
            torrent['size'] = ''
            
            if metadata_enabled:
                if torrent.get('_metadata') and 'size' in torrent['_metadata']:
                    try:
                        size_bytes = torrent['_metadata']['size']
                        formatted_size = format_bytes(size_bytes)
                        if formatted_size:
                            torrent['size'] = formatted_size
                            if info_hash and len(info_hash) == 40:
                                try:
                                    save_cross_data_to_redis(info_hash, {'size': formatted_size})
                                except Exception:
                                    pass
                            continue
                    except Exception:
                        pass
            
            if magnet_data:
                xl = magnet_data.get('params', {}).get('xl')
                if xl:
                    try:
                        formatted_size = format_bytes(int(xl))
                        if formatted_size:
                            torrent['size'] = formatted_size
                            if info_hash and len(info_hash) == 40:
                                try:
                                    save_cross_data_to_redis(info_hash, {'size': formatted_size})
                                except Exception:
                                    pass
                            continue
                    except Exception:
                        pass
            
            if html_size:
                torrent['size'] = html_size
                if info_hash and len(info_hash) == 40:
                    try:
                        save_cross_data_to_redis(info_hash, {'size': html_size})
                    except Exception:
                        pass
    
    def _apply_date_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        from datetime import datetime
        
        for torrent in torrents:
            current_date = torrent.get('date', '')
            if current_date:
                continue
            
            if not skip_metadata:
                if torrent.get('_metadata') and 'created_time' in torrent['_metadata']:
                    try:
                        created_time = torrent['_metadata']['created_time']
                        if created_time:
                            if isinstance(created_time, str):
                                torrent['date'] = created_time
                            else:
                                creation_date = datetime.fromtimestamp(created_time)
                                torrent['date'] = creation_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                            continue
                    except Exception:
                        pass
            
            torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    
    def _apply_imdb_fallback(self, torrents: List[Dict]) -> None:
        """Aplica fallback de IMDB quando não encontrado no HTML"""
        from cache.redis_client import get_redis_client
        from cache.redis_keys import imdb_key, imdb_title_key
        from utils.text.cleaning import remove_accents
        import re
        
        redis = get_redis_client()
        if not redis:
            return
        
        def extract_base_title_for_imdb(title: str) -> Optional[str]:
            if not title:
                return None
            
            title = re.sub(r'\s*\[Brazilian\]\s*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\[Eng\]\s*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\[br-dub\]\s*', '', title, flags=re.IGNORECASE)
            
            technical_patterns = [
                r'\.WEB-DL\.?', r'\.WEBRip\.?', r'\.BluRay\.?', r'\.DVDRip\.?',
                r'\.HDRip\.?', r'\.HDTV\.?', r'\.BDRip\.?', r'\.BRRip\.?',
                r'\.1080p\.?', r'\.720p\.?', r'\.2160p\.?', r'\.4K\.?',
                r'\.HD\.?', r'\.FHD\.?', r'\.UHD\.?', r'\.SD\.?', r'\.HDR\.?',
                r'\.x264\.?', r'\.x265\.?', r'\.HEVC\.?', r'\.AVC\.?',
                r'\.DUAL\.?', r'\.DUBLADO\.?', r'\.NACIONAL\.?',
                r'\.LEGENDADO\.?', r'\.LEGENDA\.?',
            ]
            
            for pattern in technical_patterns:
                title = re.sub(pattern, '.', title, flags=re.IGNORECASE)
            
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip(' .')
            
            title = remove_accents(title)
            
            title = title.lower().strip()
            
            title = re.sub(r'\.+$', '', title)
            title = re.sub(r'\.+', '.', title)
            title = re.sub(r'\s+', ' ', title).strip()
            
            title = title.replace(' ', '.')
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
            
            return title if title and len(title) >= 3 else None
        
        for torrent in torrents:
            imdb = torrent.get('imdb', '').strip()
            info_hash = torrent.get('info_hash', '').strip().lower()
            title = torrent.get('title_processed', '')
            
            if imdb and imdb.startswith('tt') and imdb[2:].isdigit():
                if info_hash and len(info_hash) == 40:
                    try:
                        key = imdb_key(info_hash)
                        redis.setex(key, 7 * 24 * 3600, imdb)
                    except Exception:
                        pass
                
                base_title = extract_base_title_for_imdb(title)
                if base_title and len(base_title) >= 3:
                    try:
                        title_key = imdb_title_key(base_title)
                        redis.setex(title_key, 7 * 24 * 3600, imdb)
                    except Exception:
                        pass
            
            if not torrent.get('imdb'):
                if info_hash and len(info_hash) == 40:
                    try:
                        key = imdb_key(info_hash)
                        cached_imdb = redis.get(key)
                        if cached_imdb:
                            cached_imdb_str = cached_imdb.decode('utf-8')
                            if cached_imdb_str.startswith('tt') and cached_imdb_str[2:].isdigit():
                                torrent['imdb'] = cached_imdb_str
                                continue
                    except Exception:
                        pass
                
                base_title = extract_base_title_for_imdb(title)
                if base_title and len(base_title) >= 3:
                    try:
                        title_key = imdb_title_key(base_title)
                        cached_imdb = redis.get(title_key)
                        if cached_imdb:
                            cached_imdb_str = cached_imdb.decode('utf-8')
                            if cached_imdb_str.startswith('tt') and cached_imdb_str[2:].isdigit():
                                torrent['imdb'] = cached_imdb_str
                                continue
                    except Exception:
                        pass
                
                try:
                    magnet_link = torrent.get('magnet_link')
                    if magnet_link and info_hash:
                        metadata = torrent.get('_metadata')
                        if metadata and metadata.get('imdb'):
                            imdb_from_metadata = metadata.get('imdb')
                            if isinstance(imdb_from_metadata, str) and imdb_from_metadata.startswith('tt') and imdb_from_metadata[2:].isdigit():
                                torrent['imdb'] = imdb_from_metadata
                                if redis:
                                    try:
                                        if info_hash and len(info_hash) == 40:
                                            key = imdb_key(info_hash)
                                            redis.setex(key, 7 * 24 * 3600, imdb_from_metadata)
                                        
                                        if base_title and len(base_title) >= 3:
                                            title_key = imdb_title_key(base_title)
                                            redis.setex(title_key, 7 * 24 * 3600, imdb_from_metadata)
                                        
                                    except Exception:
                                        pass
                except Exception:
                    pass
    
    def _attach_peers(self, torrents: List[Dict]) -> None:
        from utils.parsing.magnet_utils import extract_trackers_from_magnet
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        import logging
        
        logger = logging.getLogger(__name__)
        
        scraper_name = getattr(self, '_current_scraper_name', None)
        

        infohash_map = {}
        log_id_by_hash = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            log_parts = []
            if scraper_name:
                log_parts.append(f"[{scraper_name}]")
            title = torrent.get('title_processed', '')
            if title:
                title_preview = title[:120] if len(title) > 120 else title
                log_parts.append(title_preview)
            log_parts.append(f"(hash: {info_hash})")
            log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
            
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
                    continue
                else:
                    pass
            else:
                pass
            
            trackers = torrent.get('trackers') or []
            if not trackers:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    trackers = extract_trackers_from_magnet(magnet_link)
            
            if trackers:
                infohash_map.setdefault(info_hash, [])
                infohash_map[info_hash].extend(trackers)
                log_id_by_hash[info_hash] = log_id
        
        if not infohash_map:
            return
        
        try:
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
                    from cache.tracker_cache import TrackerCache
                    tracker_cache = TrackerCache()
                    cached = tracker_cache.get(info_hash)
                    if not cached:
                        tracker_data = {"leech": leech, "seed": seed}
                        tracker_cache.set(info_hash, tracker_data)
                except Exception:
                    pass
                
                saved_to_redis = False
                try:
                    cross_data_to_save = {
                        'tracker_seed': seed,
                        'tracker_leech': leech
                    }
                    save_cross_data_to_redis(info_hash, cross_data_to_save)
                    saved_to_redis = True
                except Exception:
                    pass
                
                log_parts = []
                if scraper_name:
                    log_parts.append(f"[{scraper_name}]")
                title = torrent.get('title_processed', '')
                if title:
                    title_preview = title[:120] if len(title) > 120 else title
                    log_parts.append(title_preview)
                log_parts.append(f"(hash: {info_hash})")
                log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
                
                if saved_to_redis:
                    logger.debug(f"[Tracker] Buscando: {log_id} → (S:{seed} L:{leech}) Salvo no Redis")
                else:
                    logger.debug(f"[Tracker] Buscando: {log_id} → (S:{seed} L:{leech}) Scrape realizado (erro ao salvar no Redis)")
        except Exception:
            pass
    
    def _save_metadata_name_to_cross_data(self, torrent: Dict, metadata: Dict) -> None:
        try:
            info_hash = torrent.get('info_hash', '').lower()
            if not info_hash or len(info_hash) != 40:
                return
            
            metadata_name = metadata.get('name', '').strip() if metadata else None
            if not metadata_name or len(metadata_name) < 3:
                return
            
            from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
            from utils.text.storage import _is_metadata_more_complete
            from utils.text.title_builder import _normalize_metadata_name
            
            cross_data = get_cross_data_from_redis(info_hash)
            cross_magnet_processed = None
            if cross_data and cross_data.get('magnet_processed'):
                cross_magnet_processed = str(cross_data.get('magnet_processed')).strip()
            
            if not cross_magnet_processed or not _is_metadata_more_complete(metadata_name, cross_magnet_processed):
                normalized_metadata = _normalize_metadata_name(metadata_name)
                save_cross_data_to_redis(info_hash, {'metadata_name': metadata_name, 'magnet_processed': normalized_metadata})
        except Exception:
            pass

