# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import asyncio
from typing import List, Dict, Optional, Callable, Any
from app.config import Config
from tracker import get_tracker_service
from magnet.metadata_async import fetch_metadata_from_itorrents_async
from magnet.parser import MagnetParser
from utils.text.utils import format_bytes
from utils.http.proxy import get_aiohttp_proxy_connector
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

    @staticmethod
    def _parse_cross_data(raw_map: Dict[bytes, bytes]) -> Dict[str, Any]:
        parsed: Dict[str, Any] = {}
        for field, value in (raw_map or {}).items():
            field_str = field.decode('utf-8')
            value_str = value.decode('utf-8')
            if field_str in ('missing_dn', 'has_legenda'):
                parsed[field_str] = value_str.lower() == 'true'
            elif field_str in ('tracker_seed', 'tracker_leech'):
                try:
                    parsed[field_str] = int(value_str) if value_str and value_str != 'N/A' else 0
                except (TypeError, ValueError):
                    parsed[field_str] = 0
            else:
                parsed[field_str] = value_str if value_str and value_str != 'N/A' else None
        return parsed

    def _bulk_get_cross_data(self, info_hashes: List[str]) -> Dict[str, Dict[str, Any]]:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import torrent_cross_data_key

        normalized = [
            str(h).strip().lower()
            for h in info_hashes
            if h and len(str(h).strip()) == 40
        ]
        if not normalized:
            return {}
        redis = get_redis_client()
        if not redis:
            return {}
        try:
            pipe = redis.pipeline(transaction=False)
            for h in normalized:
                pipe.hgetall(torrent_cross_data_key(h))
            rows = pipe.execute()
        except Exception:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for info_hash, raw in zip(normalized, rows):
            if raw:
                parsed = self._parse_cross_data(raw)
                if parsed:
                    result[info_hash] = parsed
        return result
    
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
        
        self._apply_size_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_date_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_imdb_fallback(torrents)
        
        if not skip_trackers:
            await self._attach_peers(torrents)
        
        return torrents, filter_stats
    
    async def _ensure_titles_complete(
        self,
        torrents: List[Dict],
        fetch_remote: bool = True,
    ) -> None:
        """Hidrata títulos via Redis/cache; opcionalmente busca iTorrents (fetch_remote)."""
        from cache.metadata_cache import MetadataCache
        
        metadata_cache = MetadataCache()
        cross_data_by_hash = self._bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )
        from utils.text.storage import (
            torrent_needs_metadata_title_upgrade,
            upgrade_torrent_title_from_metadata,
        )
        to_upgrade: List[Dict] = []
        
        for torrent in torrents:
            info_hash = str(torrent.get('info_hash') or '').lower()
            cross_data = cross_data_by_hash.get(info_hash)
            if cross_data:
                if not torrent.get('original_title') and cross_data.get('title_original_html'):
                    torrent['original_title'] = cross_data.get('title_original_html', '')
                if not torrent.get('title_translated_processed') and cross_data.get('title_translated_html'):
                    torrent['title_translated_processed'] = cross_data.get('title_translated_html', '')
                if cross_data.get('magnet_processed'):
                    torrent['magnet_processed'] = cross_data.get('magnet_processed')

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
            except Exception:
                pass

        for i in range(0, len(to_upgrade), worker_limit):
            chunk = to_upgrade[i:i + worker_limit]
            await asyncio.gather(*(upgrade_one(t) for t in chunk), return_exceptions=True)
    
    async def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        from utils.concurrency.metadata_semaphore_async import metadata_slot_async
        from cache.metadata_cache import MetadataCache
        
        session = await self._get_session()
        metadata_cache = MetadataCache()
        cross_data_by_hash = self._bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
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
                if cross_data:
                    has_release_title = cross_data.get('magnet_processed')
                    has_size = cross_data.get('size')
                    if has_release_title and has_size:
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
                        await self._save_metadata_name_to_cross_data(torrent, metadata)
    
    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """Aplica fallbacks para tamanho (síncrono - usa dados já obtidos)."""
        from utils.text.cross_data import save_cross_data_to_redis
        
        metadata_enabled = not skip_metadata
        cross_data_by_hash = self._bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )
        
        for torrent in torrents:
            html_size = torrent.get('size', '')
            info_hash = torrent.get('info_hash', '').lower()
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            

            if info_hash and len(info_hash) == 40:
                cross_data = cross_data_by_hash.get(info_hash)
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
        """Aplica fallbacks para data: 1) Metadata API, 2) Data atual"""
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
        """Aplica fallback de IMDB (síncrono - usa dados já obtidos)."""
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
    
    async def _attach_peers(self, torrents: List[Dict]) -> None:
        """Anexa dados de peers (seeds/leechers) via trackers (async)."""
        from utils.parsing.magnet_utils import extract_trackers_from_magnet
        from utils.text.cross_data import save_cross_data_to_redis
        import logging
        
        logger = logging.getLogger(__name__)
        
        scraper_name = getattr(self, '_current_scraper_name', None)
        cross_data_by_hash = self._bulk_get_cross_data(
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
            
            log_parts = []
            if scraper_name:
                log_parts.append(f"[{scraper_name}]")
            title = torrent.get('title_processed', '')
            if title:
                title_preview = title[:120] if len(title) > 120 else title
                log_parts.append(title_preview)
            log_parts.append(f"(hash: {info_hash})")
            log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
            
            cross_data = cross_data_by_hash.get(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
                    logger.debug(f"[Tracker] Buscando: {log_id} → (S:{tracker_seed} L:{tracker_leech}) cache")
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
    
    async def _save_metadata_name_to_cross_data(self, torrent: Dict, metadata: Dict) -> None:
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

