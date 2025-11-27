"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Dict, Optional
from app.config import Config
from scraper import (
    create_scraper,
    available_scraper_types,
    normalize_scraper_type,
)
from core.enrichers.torrent_enricher import TorrentEnricher
from core.filters.query_filter import QueryFilter
from core.processors.torrent_processor import TorrentProcessor

logger = logging.getLogger(__name__)

# Mapeamento de números para nomes de scrapers (usado pelo Prowlarr)
SCRAPER_NUMBER_MAP = {
    "1": "starck",
    "2": "rede",
    "3": "limao",
    "4": "tfilme",
    "5": "vaca",
    "6": "comand",
    "7": "bludv",
}


# Serviço de indexação - lógica de negócio separada dos handlers
class IndexerService:
    def __init__(self):
        self.enricher = TorrentEnricher()
        self.processor = TorrentProcessor()
    
    def search(self, scraper_type: str, query: str, use_flaresolverr: bool = False, filter_results: bool = False) -> List[Dict]:
        """Busca torrents por query"""
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        filter_func = None
        if filter_results and query:
            filter_func = QueryFilter.create_filter(query)
        
        torrents = scraper.search(query, filter_func=filter_func)
        
        # Remove campos internos
        self.processor.remove_internal_fields(torrents)
        
        # Ordena por data
        self.processor.sort_by_date(torrents)
        
        return torrents
    
    def get_last_filter_stats(self):
        """Retorna as estatísticas do último filtro aplicado"""
        return self.enricher._last_filter_stats if hasattr(self.enricher, '_last_filter_stats') else None
    
    def get_page(self, scraper_type: str, page: str = '1', use_flaresolverr: bool = False, is_test: bool = False) -> List[Dict]:
        """Obtém torrents de uma página"""
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        max_links = None
        if is_test:
            max_links = Config.EMPTY_QUERY_MAX_LINKS if Config.EMPTY_QUERY_MAX_LINKS > 0 else None
        
        torrents = scraper.get_page(page, max_items=max_links)
        
        # Atualiza estatísticas do enricher do IndexerService com as do scraper
        if hasattr(scraper, '_enricher') and hasattr(scraper._enricher, '_last_filter_stats'):
            self.enricher._last_filter_stats = scraper._enricher._last_filter_stats
        
        # Remove campos internos
        self.processor.remove_internal_fields(torrents)
        
        # Para testes com limite, mantém ordem original
        # Para vaca, sempre mantém ordem original do site
        # Caso contrário, ordena por data
        if scraper_type != 'vaca' and not (is_test and Config.EMPTY_QUERY_MAX_LINKS > 0):
            self.processor.sort_by_date(torrents)
        
        return torrents
    
    def get_scraper_info(self) -> Dict:
        """Obtém informações dos scrapers disponíveis"""
        types_info = available_scraper_types()
        sites_dict = {
            scraper_type: meta.get('default_url')
            for scraper_type, meta in types_info.items()
            if meta.get('default_url')
        }
        
        return {
            'configured_sites': sites_dict,
            'available_types': list(types_info.keys()),
            'types_info': types_info
        }
    
    def validate_scraper_type(self, scraper_type: str) -> tuple[bool, Optional[str]]:
        """Valida tipo de scraper e retorna tipo normalizado"""
        # Converte número para nome do scraper se necessário
        if scraper_type in SCRAPER_NUMBER_MAP:
            scraper_type = SCRAPER_NUMBER_MAP[scraper_type]
        
        types_info = available_scraper_types()
        normalized_type = normalize_scraper_type(scraper_type)
        
        if normalized_type not in types_info:
            return False, None
        
        return True, normalized_type

