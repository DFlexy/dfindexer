"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from typing import Dict, Callable
from utils.text.text_processing import check_query_match


class QueryFilter:
    @staticmethod
    def create_filter(query: str) -> Callable[[Dict], bool]:
        # Cria função de filtro baseada na query
        if not query:
            return lambda t: True
        
        def filter_func(torrent: Dict) -> bool:
            return check_query_match(
                query,
                torrent.get('title', ''),
                torrent.get('original_title', ''),
                torrent.get('translated_title', '')
            )
        
        return filter_func

