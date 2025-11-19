"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from typing import List, Dict
from datetime import datetime


# Processador de torrents - ordenação, limpeza, etc.
class TorrentProcessor:
    @staticmethod
    def remove_internal_fields(torrents: List[Dict]) -> None:
        """Remove campos internos dos torrents"""
        for torrent in torrents:
            torrent.pop('_metadata', None)
            torrent.pop('_metadata_fetched', None)
    
    @staticmethod
    def sort_by_date(torrents: List[Dict], reverse: bool = True) -> None:
        """Ordena torrents por data"""
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

