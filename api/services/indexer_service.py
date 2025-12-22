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

SCRAPER_NUMBER_MAP = {
    "1": "starck",
    "2": "rede",
    "3": "xfilmes",
    "4": "tfilme",
    "5": None,  # Removido (vaca)
    "6": "comand",
    "7": "bludv",
    "8": "portal",
}


# Retorna apenas os IDs válidos (não None) do mapeamento
# Usado para garantir que IDs removidos não apareçam em nenhum lugar
def get_valid_scraper_ids() -> Dict[str, str]:
    return {k: v for k, v in SCRAPER_NUMBER_MAP.items() if v is not None}


class IndexerService:
    def __init__(self):
        self.enricher = TorrentEnricher()
        self.processor = TorrentProcessor()
    
    # Busca torrents por query
    def search(self, scraper_type: str, query: str, use_flaresolverr: bool = False, filter_results: bool = False, max_results: Optional[int] = None) -> tuple[List[Dict], Optional[Dict]]:
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        # IMPORTANTE: Aplica filtro automaticamente quando há query para evitar resultados irrelevantes
        # Os sites retornam muitos resultados que não correspondem à busca, então o filtro é essencial
        filter_func = None
        if query:
            # Sempre aplica filtro quando há query, independente de filter_results
            # Isso garante que apenas resultados relevantes sejam retornados
            filter_func = QueryFilter.create_filter(query)
        
        # Busca com filtro se filter_results=True, caso contrário sem filtro
        torrents = scraper.search(query, filter_func=filter_func)
        
        # Limita ANTES do enriquecimento para economizar processamento de metadata/trackers
        if max_results and max_results > 0:
            torrents = torrents[:max_results]
        
        # Calcula estatísticas do filtro - faz cópia imediatamente para evitar race condition
        filter_stats = None
        if hasattr(scraper, '_enricher') and hasattr(scraper._enricher, '_last_filter_stats'):
            # Faz cópia imediata das estatísticas para evitar que sejam sobrescritas por outras requisições
            stats = scraper._enricher._last_filter_stats
            if stats:
                # Cria cópia profunda para evitar race condition entre requisições simultâneas
                # IMPORTANTE: Coleta ANTES de qualquer outra operação que possa sobrescrever
                filter_stats = {
                    'total': stats.get('total', 0),
                    'filtered': stats.get('filtered', 0),
                    'approved': stats.get('approved', 0),
                    'scraper_name': stats.get('scraper_name', '')
                }
        elif filter_func and torrents:
            # Fallback: calcula estatísticas manualmente se não foram calculadas pelo enricher
            total_before_filter = len(torrents)
            filtered_count = sum(1 for t in torrents if not filter_func(t))
            approved_count = total_before_filter - filtered_count
            
            filter_stats = {
                'total': total_before_filter,
                'filtered': filtered_count,
                'approved': approved_count,
                'scraper_name': scraper.SCRAPER_TYPE if hasattr(scraper, 'SCRAPER_TYPE') else ''
                }
        
        self.processor.sanitize_torrents(torrents)
        self.processor.remove_internal_fields(torrents)
        self.processor.sort_by_date(torrents)
        
        return torrents, filter_stats
    
    # Retorna as estatísticas do último filtro aplicado
    def get_last_filter_stats(self):
        return self.enricher._last_filter_stats if hasattr(self.enricher, '_last_filter_stats') else None
    
    # Obtém torrents de uma página
    def get_page(self, scraper_type: str, page: str = '1', use_flaresolverr: bool = False, is_test: bool = False, max_results: Optional[int] = None) -> tuple[List[Dict], Optional[Dict]]:
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        max_links = None
        if is_test:
            max_links = Config.EMPTY_QUERY_MAX_LINKS if Config.EMPTY_QUERY_MAX_LINKS > 0 else None
        
        # IMPORTANTE: Passa is_test=True para o scraper quando query está vazia
        # Isso garante que _is_test=True no scraper, fazendo com que o cache HTML não seja usado
        # Assim, consultas sem query sempre buscam HTML fresco e veem novos links atualizados
        torrents = scraper.get_page(page, max_items=max_links, is_test=is_test)
        
        # Limita ANTES do processamento para economizar processamento de metadata/trackers
        if max_results and max_results > 0:
            torrents = torrents[:max_results]
        
        # Obtém estatísticas imediatamente após o enriquecimento (evita race condition)
        filter_stats = None
        if hasattr(scraper, '_enricher') and hasattr(scraper._enricher, '_last_filter_stats'):
            # Faz cópia das estatísticas para evitar que sejam sobrescritas por outras requisições
            stats = scraper._enricher._last_filter_stats
            if stats:
                filter_stats = {
                    'total': stats.get('total', 0),
                    'filtered': stats.get('filtered', 0),
                    'approved': stats.get('approved', 0),
                    'scraper_name': stats.get('scraper_name', '')
                }
        
        self.processor.sanitize_torrents(torrents)
        self.processor.remove_internal_fields(torrents)
        
        if not (is_test and Config.EMPTY_QUERY_MAX_LINKS > 0):
            self.processor.sort_by_date(torrents)
        
        return torrents, filter_stats
    
    # Obtém informações dos scrapers disponíveis
    def get_scraper_info(self) -> Dict:
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
    
    # Valida tipo de scraper e retorna tipo normalizado
    def validate_scraper_type(self, scraper_type: str) -> tuple[bool, Optional[str]]:
        if scraper_type in SCRAPER_NUMBER_MAP:
            mapped_type = SCRAPER_NUMBER_MAP[scraper_type]
            # Se o mapeamento for None (scraper removido), retorna inválido
            # Isso permite remover scrapers sem precisar reajustar IDs no prowlarr.yml
            if mapped_type is None:
                return False, None
            scraper_type = mapped_type
        
        types_info = available_scraper_types()
        normalized_type = normalize_scraper_type(scraper_type)
        
        if normalized_type not in types_info:
            return False, None
        
        return True, normalized_type

