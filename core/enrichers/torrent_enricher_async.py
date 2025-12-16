"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import asyncio
from typing import List, Dict, Optional, Callable
from app.config import Config
from tracker import get_tracker_service
from magnet.metadata_async import fetch_metadata_from_itorrents_async
from magnet.parser import MagnetParser
from utils.text.utils import format_bytes
import aiohttp

logger = logging.getLogger(__name__)


class TorrentEnricherAsync:
    def __init__(self):
        self.tracker_service = get_tracker_service()
        self._last_filter_stats = None
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Obtém ou cria sessão aiohttp reutilizável."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=5)
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=20)
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
        """Fecha a sessão aiohttp."""
        if self._session and not self._session.closed:
            await self._session.close()
    
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
        
        # Removida deduplicação - todos os magnets devem ser mostrados
        # torrents = self._remove_duplicates(torrents)
        
        if not skip_metadata:
            await self._ensure_titles_complete(torrents)
        
        total_before_filter = len(torrents)
        if filter_func:
            torrents = [t for t in torrents if filter_func(t)]
            filtered_count = total_before_filter - len(torrents)
            approved_count = len(torrents)
        else:
            filtered_count = 0
            approved_count = len(torrents)
        
        # Cria estatísticas e retorna imediatamente para evitar race condition
        filter_stats = {
            'total': total_before_filter,
            'filtered': filtered_count,
            'approved': approved_count,
            'scraper_name': scraper_name
        }
        
        # Mantém _last_filter_stats para compatibilidade, mas não depende dele
        self._last_filter_stats = filter_stats.copy()
        
        if not torrents:
            return torrents
        
        if not skip_metadata:
            await self._fetch_metadata_batch(torrents)
        
        self._apply_size_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_date_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_imdb_fallback(torrents)
        
        if not skip_trackers:
            await self._attach_peers(torrents)
        
        return torrents, filter_stats
    
    def _remove_duplicates(self, torrents: List[Dict]) -> List[Dict]:
        """Remove duplicados baseado em info_hash."""
        seen_hashes = set()
        unique_torrents = []
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if info_hash and len(info_hash) == 40:
                if info_hash in seen_hashes:
                    continue
                seen_hashes.add(info_hash)
            unique_torrents.append(torrent)
        return unique_torrents
    
    async def _ensure_titles_complete(self, torrents: List[Dict]) -> None:
        """Garante que títulos estão completos (async)."""
        from utils.text.cross_data import get_cross_data_from_redis
        
        session = await self._get_session()
        
        for torrent in torrents:
            # Preenche original_title e title_translated_processed do cross-data ANTES do filtro
            info_hash = torrent.get('info_hash')
            if info_hash:
                try:
                    cross_data = get_cross_data_from_redis(info_hash)
                    if cross_data:
                        # Preenche original_title se não estiver preenchido
                        if not torrent.get('original_title') and cross_data.get('title_original_html'):
                            torrent['original_title'] = cross_data.get('title_original_html', '')
                        # Preenche title_translated_processed se não estiver preenchido
                        if not torrent.get('title_translated_processed') and cross_data.get('title_translated_html'):
                            torrent['title_translated_processed'] = cross_data.get('title_translated_html', '')
                        # Adiciona release_title_magnet do cross-data
                        if cross_data.get('release_title_magnet'):
                            torrent['release_title_magnet'] = cross_data.get('release_title_magnet')
                except Exception:
                    pass
            
            title = torrent.get('title', '')
            if not title or len(title.strip()) < 10:
                if info_hash:
                    try:
                        scraper_name = getattr(self, '_current_scraper_name', None)
                        # Tenta obter título de múltiplas fontes para melhorar o log
                        title_for_log = (torrent.get('title') or 
                                        torrent.get('original_title') or 
                                        torrent.get('title_translated_processed') or
                                        torrent.get('release_title_magnet') or
                                        None)
                        metadata = await fetch_metadata_from_itorrents_async(session, info_hash, scraper_name=scraper_name, title=title_for_log)
                        if metadata and metadata.get('name'):
                            name = metadata.get('name', '').strip()
                            if name and len(name) >= 3:
                                torrent['title'] = name
                    except Exception:
                        pass
    
    async def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        """Busca metadata em lote com semáforo async para limitar requisições simultâneas."""
        from utils.concurrency.metadata_semaphore_async import metadata_slot_async
        from utils.text.cross_data import get_cross_data_from_redis
        from cache.metadata_cache import MetadataCache
        
        session = await self._get_session()
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        async def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            """Busca metadata para um torrent (async)."""
            # Obtém info_hash ANTES de adquirir slot
            info_hash = torrent.get('info_hash')
            if not info_hash:
                try:
                    magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                    info_hash = magnet_data.get('info_hash')
                except Exception:
                    return (torrent, None)
            
            if not info_hash:
                return (torrent, None)
            
            # Verifica cross_data ANTES de adquirir slot
            try:
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data:
                    has_release_title = cross_data.get('release_title_magnet')
                    has_size = cross_data.get('size')
                    if has_release_title and has_size:
                        return (torrent, None)
            except Exception:
                pass
            
            # Verifica cache de metadata ANTES de adquirir slot
            try:
                metadata_cache = MetadataCache()
                cached_metadata = metadata_cache.get(info_hash.lower())
                if cached_metadata:
                    return (torrent, cached_metadata)
            except Exception:
                pass
            
            # Só adquire slot se realmente precisa buscar metadata
            async with metadata_slot_async():
                try:
                    # Obtém scraper_name e title para o log
                    scraper_name = getattr(self, '_current_scraper_name', None)
                    # Tenta obter título de múltiplas fontes para melhorar o log
                    title = (torrent.get('title') or 
                            torrent.get('original_title') or 
                            torrent.get('title_translated_processed') or
                            torrent.get('release_title_magnet') or
                            None)
                    metadata = await fetch_metadata_from_itorrents_async(session, info_hash, scraper_name=scraper_name, title=title)
                    return (torrent, metadata)
                except Exception:
                    return (torrent, None)
        
        # Executa todas as requisições em paralelo
        tasks = [fetch_metadata_for_torrent(t) for t in torrents_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, tuple):
                torrent, metadata = result
                if metadata:
                    torrent['_metadata'] = metadata
                    torrent['_metadata_fetched'] = True
    
    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """Aplica fallbacks para tamanho (síncrono - usa dados já obtidos)."""
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        metadata_enabled = not skip_metadata
        
        for torrent in torrents:
            html_size = torrent.get('size', '')
            info_hash = torrent.get('info_hash', '').lower()
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            # Primeiro, tenta buscar do cross-data
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
            
            # Tentativa 1: Metadata API
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
            
            # Tentativa 2: Parâmetro 'xl' do magnet
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
            
            # Tentativa 3: Tamanho do HTML (fallback final)
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
            # Só aplica fallback se date estiver vazio
            current_date = torrent.get('date', '')
            if current_date:
                continue  # Já tem data, não precisa de fallback
            
            # Tentativa 1: Metadata API (se habilitado)
            if not skip_metadata:
                if torrent.get('_metadata') and 'created_time' in torrent['_metadata']:
                    try:
                        created_time = torrent['_metadata']['created_time']
                        if created_time:
                            # Se created_time já é string ISO, usa diretamente
                            if isinstance(created_time, str):
                                torrent['date'] = created_time
                            else:
                                # Se é timestamp, converte
                                creation_date = datetime.fromtimestamp(created_time)
                                torrent['date'] = creation_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                            continue  # Encontrou no metadata, não precisa de fallback final
                    except Exception:
                        pass
            
            # Tentativa 2: Fallback final - Data atual (formato ISO 8601 com Z)
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
            """Extrai título base do título finalizado para busca de IMDB."""
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
            title = torrent.get('title', '')
            
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
                # Fallback 1: Cache por info_hash
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
                
                # Fallback 2: Cache por base_title
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
                
                # Fallback 3: Metadata do torrent
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
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Obtém scraper_name para logs
        scraper_name = getattr(self, '_current_scraper_name', None)
        
        infohash_map = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            # Monta identificação para o log
            log_parts = []
            if scraper_name:
                log_parts.append(f"[{scraper_name}]")
            title = torrent.get('title', '')
            if title:
                title_preview = title[:50] if len(title) > 50 else title
                log_parts.append(title_preview)
            log_parts.append(f"(hash: {info_hash})")
            log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
            
            # Tenta buscar do cross-data primeiro
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                # Se ambos estão presentes e não são ambos 0, usa do cross-data para evitar scrape desnecessário
                if tracker_seed is not None and tracker_leech is not None:
                    # Se ambos são 0, prossegue para fazer scrape ao invés de usar os valores
                    if not (tracker_seed == 0 and tracker_leech == 0):
                        torrent['seed_count'] = tracker_seed
                        torrent['leech_count'] = tracker_leech
                        # Log removido - hits do Redis são muito comuns
                        continue
                    else:
                        # Ambos são 0, não usa e prossegue para scrape
                        logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
                else:
                    # Não tem ambos valores, prossegue para scrape
                    logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
            else:
                # Não encontrou no cross-data, prossegue para scrape
                logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
            
            # Se não encontrou no cross-data, adiciona para fazer scrape
            trackers = torrent.get('trackers') or []
            
            if not trackers:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    trackers = extract_trackers_from_magnet(magnet_link)
            
            if trackers:
                infohash_map.setdefault(info_hash, [])
                infohash_map[info_hash].extend(trackers)
        
        if not infohash_map:
            return
        
        # Faz scrape dos trackers (ainda síncrono, mas pode ser migrado depois)
        try:
            peers_map = self.tracker_service.get_peers_bulk(infohash_map)
            for torrent in torrents:
                info_hash = (torrent.get('info_hash') or '').lower()
                if not info_hash or len(info_hash) != 40:
                    continue
                
                leech_seed = peers_map.get(info_hash)
                if leech_seed:
                    leech, seed = leech_seed
                    torrent['leech_count'] = leech
                    torrent['seed_count'] = seed
                    
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
                    
                    # Log com resultado da busca e salvamento
                    log_parts = []
                    if scraper_name:
                        log_parts.append(f"[{scraper_name}]")
                    title = torrent.get('title', '')
                    if title:
                        title_preview = title[:50] if len(title) > 50 else title
                        log_parts.append(title_preview)
                    log_parts.append(f"(hash: {info_hash})")
                    log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
                    
                    if saved_to_redis:
                        logger.debug(f"[Tracker] Buscando tracker: {log_id} → Salvo no Redis")
                    else:
                        logger.debug(f"[Tracker] Buscando tracker: {log_id} → Scrape realizado (erro ao salvar no Redis)")
        except Exception:
            pass

