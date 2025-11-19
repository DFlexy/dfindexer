"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Dict, Optional, Callable
from app.config import Config
from tracker import get_tracker_service
from magnet.metadata import fetch_metadata_from_itorrents
from magnet.parser import MagnetParser
from utils.text.text_processing import format_bytes

logger = logging.getLogger(__name__)


# Enricher de torrents - adiciona metadata, trackers, etc.
class TorrentEnricher:
    def __init__(self):
        self.tracker_service = get_tracker_service()
    
    def enrich(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        """Enriquece lista de torrents com metadata e trackers"""
        if not torrents:
            return torrents
        
        # Remove duplicados baseado em info_hash
        torrents = self._remove_duplicates(torrents)
        
        # Busca metadata para títulos primeiro (se necessário)
        if Config.MAGNET_METADATA_ENABLED and not skip_metadata:
            self._ensure_titles_complete(torrents)
        
        # Aplica filtro após títulos completos
        if filter_func:
            torrents = [t for t in torrents if filter_func(t)]
            if not torrents:
                return torrents
        
        # Busca metadata para size e date
        if Config.MAGNET_METADATA_ENABLED and not skip_metadata:
            self._fetch_metadata_batch(torrents)
        
        # Aplica fallbacks
        self._apply_size_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_date_fallback(torrents, skip_metadata=skip_metadata)
        
        # Busca trackers
        if not skip_trackers:
            self._attach_peers(torrents)
        
        return torrents
    
    def _remove_duplicates(self, torrents: List[Dict]) -> List[Dict]:
        """Remove duplicados baseado em info_hash"""
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
    
    def _ensure_titles_complete(self, torrents: List[Dict]) -> None:
        """Garante que títulos estão completos"""
        for torrent in torrents:
            title = torrent.get('title', '')
            if not title or len(title.strip()) < 10:
                info_hash = torrent.get('info_hash')
                if info_hash:
                    try:
                        metadata = fetch_metadata_from_itorrents(info_hash)
                        if metadata and metadata.get('name'):
                            name = metadata.get('name', '').strip()
                            if name and len(name) >= 3:
                                torrent['title'] = name
                    except Exception:
                        pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        """Busca metadata em lote"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            try:
                info_hash = torrent.get('info_hash')
                if not info_hash:
                    try:
                        magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                        info_hash = magnet_data.get('info_hash')
                    except Exception:
                        return (torrent, None)
                
                if not info_hash:
                    return (torrent, None)
                
                metadata = fetch_metadata_from_itorrents(info_hash)
                return (torrent, metadata)
            except Exception:
                return (torrent, None)
        
        if len(torrents_to_fetch) > 1:
            max_workers = min(6, len(torrents_to_fetch))
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
                    except Exception:
                        pass
        else:
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                except Exception:
                    pass
    
    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """Aplica fallbacks para tamanho"""
        metadata_enabled = Config.MAGNET_METADATA_ENABLED and not skip_metadata
        
        for torrent in torrents:
            html_size = torrent.get('size', '')
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            magnet_data = None
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                pass
            
            # Tentativa 1: Metadata API
            if metadata_enabled:
                if torrent.get('_metadata') and 'size' in torrent['_metadata']:
                    try:
                        size_bytes = torrent['_metadata']['size']
                        formatted_size = format_bytes(size_bytes)
                        if formatted_size:
                            torrent['size'] = formatted_size
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
                            continue
                    except Exception:
                        pass
            
            # Tentativa 3: Tamanho do HTML (fallback final)
            if html_size:
                torrent['size'] = html_size
    
    def _apply_date_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """Aplica fallbacks para data"""
        metadata_enabled = Config.MAGNET_METADATA_ENABLED and not skip_metadata
        
        for torrent in torrents:
            html_date = torrent.get('date', '')
            
            # Tentativa 1: Metadata API
            if metadata_enabled:
                if torrent.get('_metadata') and 'created_time' in torrent['_metadata']:
                    try:
                        created_time = torrent['_metadata']['created_time']
                        if created_time:
                            torrent['date'] = created_time
                            continue
                    except Exception:
                        pass
            
            # Tentativa 2: Data do HTML (fallback final)
            if html_date:
                torrent['date'] = html_date
    
    def _attach_peers(self, torrents: List[Dict]) -> None:
        """Anexa dados de peers (seeds/leechers) via trackers"""
        from utils.parsing.magnet_utils import extract_trackers_from_magnet
        
        # Agrupa por info_hash para usar get_peers_bulk (mais eficiente)
        infohash_map = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            
            # Extrai trackers do torrent primeiro
            trackers = torrent.get('trackers') or []
            
            # Se não tem trackers no torrent, tenta extrair do magnet_link usando função utilitária
            if not trackers:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    trackers = extract_trackers_from_magnet(magnet_link)
            
            if trackers:
                infohash_map.setdefault(info_hash, [])
                infohash_map[info_hash].extend(trackers)
        
        if not infohash_map:
            return
        
        # Busca peers em lote
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
        except Exception:
            pass

