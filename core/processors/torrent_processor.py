# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from typing import List, Dict, Any
from datetime import datetime
from bs4 import Tag, NavigableString

logger = logging.getLogger(__name__)

class TorrentProcessor:
    @staticmethod
    def _sanitize_value(value: Any) -> Any:

        if value is None:
            return None
        
        if isinstance(value, Tag):
            return value.get_text(strip=True) if hasattr(value, 'get_text') else str(value)
        
        if isinstance(value, NavigableString):
            return str(value)
        
        if isinstance(value, list):
            return [TorrentProcessor._sanitize_value(item) for item in value]
        
        if isinstance(value, dict):
            return {k: TorrentProcessor._sanitize_value(v) for k, v in value.items()}
        
        return value
    
    @staticmethod
    def sanitize_torrents(torrents: List[Dict]) -> None:

        for torrent in torrents:
            for key, value in list(torrent.items()):
                sanitized = TorrentProcessor._sanitize_value(value)
                if sanitized != value:
                    torrent[key] = sanitized
    
    @staticmethod
    def remove_internal_fields(torrents: List[Dict]) -> None:
        from datetime import datetime
        
        for torrent in torrents:
            torrent.pop('_metadata', None)
            torrent.pop('_metadata_fetched', None)
            torrent.pop('_original_order', None)
            

            if 'title_processed' in torrent and 'title' not in torrent:
                torrent['title'] = torrent.get('title_processed', '')
            
            date_value = torrent.get('date')
            if not date_value or (isinstance(date_value, str) and date_value.strip() == ''):
                torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
            

            if torrent.get('seed_count') is None:
                torrent['seed_count'] = 0
            else:
                try:
                    torrent['seed_count'] = int(torrent['seed_count'])
                except (ValueError, TypeError):
                    torrent['seed_count'] = 0
            
            if torrent.get('leech_count') is None:
                torrent['leech_count'] = 0
            else:
                try:
                    torrent['leech_count'] = int(torrent['leech_count'])
                except (ValueError, TypeError):
                    torrent['leech_count'] = 0
            
            if not torrent.get('magnet_link') and torrent.get('magnet'):
                torrent['magnet_link'] = torrent['magnet']
            
            if not torrent.get('details'):
                torrent['details'] = torrent.get('magnet_link', '')
            
            if not torrent.get('info_hash'):
                magnet_link = torrent.get('magnet_link', '')
                if magnet_link and 'xt=urn:btih:' in magnet_link.lower():
                    try:
                        import re
                        match = re.search(r'xt=urn:btih:([a-f0-9]{40})', magnet_link, re.IGNORECASE)
                        if match:
                            torrent['info_hash'] = match.group(1).lower()
                    except Exception:
                        pass
    
    @staticmethod
    def sort_by_date(torrents: List[Dict], reverse: bool = True) -> None:
        def sort_key(torrent: Dict) -> datetime:
            date_str = torrent.get('date', '')
            if not date_str:
                return datetime.min.replace(tzinfo=None)
            
            try:
                dt = None
                if 'T' in date_str:
                    if '+' in date_str or 'Z' in date_str:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(date_str)
                else:
                    dt = datetime.strptime(date_str.split('T')[0], '%Y-%m-%d')
                
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                
                return dt
            except (ValueError, AttributeError, TypeError):
                return datetime.min.replace(tzinfo=None)
        
        torrents.sort(key=sort_key, reverse=reverse)

