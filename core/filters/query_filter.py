# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from typing import Dict, Callable
from utils.text.query import check_query_match

logger = logging.getLogger(__name__)

class QueryFilter:
    @staticmethod
    def create_filter(query: str) -> Callable[[Dict], bool]:
        if not query:
            return lambda t: True
        
        def filter_func(torrent: Dict) -> bool:
            title_processed = torrent.get('title_processed') or ''
            original_title = torrent.get('original_title') or ''
            title_translated = torrent.get('title_translated_processed') or ''
            year = torrent.get('year') or ''
            
            title_processed = str(title_processed) if title_processed is not None else ''
            original_title = str(original_title) if original_title is not None else ''
            title_translated = str(title_translated) if title_translated is not None else ''
            year = str(year).strip() if year is not None else ''
            
            result = check_query_match(
                query,
                title_processed,
                original_title,
                f"{title_translated} {year}".strip()
            )
            
            if result:
                logger.debug(f"Resultado Aprovado: Query='{query[:50]}' | Title='{title_processed[:60]}' | Original='{original_title[:40]}' | Translated='{title_translated[:40]}'")
            else:

                query_words = set(query.lower().split())
                title_words = set((title_processed + ' ' + original_title + ' ' + title_translated).lower().split())
                
                common_words = query_words.intersection(title_words)
                common_words = {w for w in common_words if len(w) > 2 and w not in ['the', 'and', 'of', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'de', 'da', 'do', 'e', 'o', 'a', 'os', 'as']}
                
                if common_words:
                    logger.debug(f"Resultado Rejeitado: Query='{query[:50]}' | Title='{title_processed[:60]}' | Original='{original_title[:40]}' | Translated='{title_translated[:40]}'")
            
            return result
        
        return filter_func

