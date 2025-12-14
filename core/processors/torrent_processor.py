"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from bs4 import Tag, NavigableString

logger = logging.getLogger(__name__)


class TorrentProcessor:
    @staticmethod
    def _sanitize_value(value: Any) -> Any:
        # Converte valores não serializáveis para tipos serializáveis (Tag do BeautifulSoup para strings)
        if value is None:
            return None
        
        # Converte objetos Tag do BeautifulSoup para string
        if isinstance(value, Tag):
            return value.get_text(strip=True) if hasattr(value, 'get_text') else str(value)
        
        # Converte NavigableString para string
        if isinstance(value, NavigableString):
            return str(value)
        
        # Se for lista, sanitiza cada item
        if isinstance(value, list):
            return [TorrentProcessor._sanitize_value(item) for item in value]
        
        # Se for dicionário, sanitiza cada valor
        if isinstance(value, dict):
            return {k: TorrentProcessor._sanitize_value(v) for k, v in value.items()}
        
        return value
    
    @staticmethod
    def sanitize_torrents(torrents: List[Dict]) -> None:
        # Sanitiza todos os valores dos torrents para garantir serialização JSON
        for torrent in torrents:
            for key, value in list(torrent.items()):
                sanitized = TorrentProcessor._sanitize_value(value)
                if sanitized != value:
                    torrent[key] = sanitized
    
    @staticmethod
    def remove_internal_fields(torrents: List[Dict]) -> None:
        # Remove apenas campos internos dos torrents
        # Garante que campo 'date' sempre tenha valor (fallback final se necessário)
        from datetime import datetime
        
        for torrent in torrents:
            torrent.pop('_metadata', None)
            torrent.pop('_metadata_fetched', None)
            
            # Garantia final: se date estiver vazio/None, preenche com data atual
            date_value = torrent.get('date')
            if not date_value or (isinstance(date_value, str) and date_value.strip() == ''):
                torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    
    @staticmethod
    def sort_by_date(torrents: List[Dict], reverse: bool = True) -> None:
        # Ordena torrents por data
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

