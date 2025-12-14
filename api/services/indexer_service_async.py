"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import asyncio
from typing import List, Dict, Optional, Callable
from app.config import Config
from scraper import (
    create_scraper,
    available_scraper_types,
    normalize_scraper_type,
)
from core.enrichers.torrent_enricher_async import TorrentEnricherAsync
from core.filters.query_filter import QueryFilter
from core.processors.torrent_processor import TorrentProcessor

logger = logging.getLogger(__name__)

SCRAPER_NUMBER_MAP = {
    "1": "starck",
    "2": "rede",
    "3": "baixafilmes",
    "4": "tfilme",
    "5": None,
    "6": "comand",
    "7": "bludv",
    "8": "nerd",
}


def get_valid_scraper_ids() -> Dict[str, str]:
    """Retorna apenas os IDs válidos do mapeamento."""
    return {k: v for k, v in SCRAPER_NUMBER_MAP.items() if v is not None}


class IndexerServiceAsync:
    def __init__(self):
        self.enricher = TorrentEnricherAsync()
        self.processor = TorrentProcessor()
    
    async def search(
        self,
        scraper_type: str,
        query: str,
        use_flaresolverr: bool = False,
        filter_results: bool = False,
        max_results: Optional[int] = None
    ) -> tuple[List[Dict], Optional[Dict]]:
        """
        Busca torrents por query (async).
        
        Nota: Por enquanto, os scrapers ainda são síncronos.
        Apenas o enriquecimento é async.
        """
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        # Cria filtro se necessário
        filter_func = None
        if filter_results and query:
            filter_func = QueryFilter.create_filter(query)
        
        # Busca com filtro se filter_results=True, caso contrário sem filtro
        torrents = scraper.search(query, filter_func=filter_func)
        
        # Limita ANTES do enriquecimento para economizar processamento de metadata/trackers
        if max_results and max_results > 0:
            torrents = torrents[:max_results]
        
        # Enriquece torrents (async) com filtro se necessário
        enriched_torrents = await self._enrich_torrents_async(
            torrents,
            scraper_type,
            filter_func  # Aplica filtro no enriquecimento se fornecido
        )
        
        # Calcula estatísticas do filtro
        filter_stats = None
        if hasattr(self.enricher, '_last_filter_stats'):
            # Usa estatísticas do enricher (já calculadas durante o enriquecimento)
            stats = self.enricher._last_filter_stats
            if stats:
                filter_stats = {
                    'total': stats.get('total', 0),
                    'filtered': stats.get('filtered', 0),
                    'approved': stats.get('approved', 0),
                    'scraper_name': stats.get('scraper_name', '')
                }
        elif filter_func and enriched_torrents:
            # Fallback: calcula estatísticas manualmente se não foram calculadas pelo enricher
            total_before_filter = len(enriched_torrents)
            filtered_count = sum(1 for t in enriched_torrents if not filter_func(t))
            approved_count = total_before_filter - filtered_count
            
            filter_stats = {
                'total': total_before_filter,
                'filtered': filtered_count,
                'approved': approved_count,
                'scraper_name': scraper.SCRAPER_TYPE if hasattr(scraper, 'SCRAPER_TYPE') else ''
            }
        
        self.processor.sanitize_torrents(enriched_torrents)
        self.processor.remove_internal_fields(enriched_torrents)
        self.processor.sort_by_date(enriched_torrents)
        
        return enriched_torrents, filter_stats
    
    async def get_page(
        self,
        scraper_type: str,
        page: str = '1',
        use_flaresolverr: bool = False,
        is_test: bool = False,
        max_results: Optional[int] = None
    ) -> tuple[List[Dict], Optional[Dict]]:
        """Obtém torrents de uma página (async)."""
        scraper = create_scraper(scraper_type, use_flaresolverr=use_flaresolverr)
        
        max_links = None
        if is_test:
            max_links = Config.EMPTY_QUERY_MAX_LINKS if Config.EMPTY_QUERY_MAX_LINKS > 0 else None
        
        # Busca torrents (ainda síncrono)
        torrents = scraper.get_page(page, max_items=max_links)
        
        # Limita ANTES do enriquecimento para economizar processamento de metadata/trackers
        if max_results and max_results > 0:
            torrents = torrents[:max_results]
        
        # Enriquece torrents (async)
        enriched_torrents = await self._enrich_torrents_async(
            torrents,
            scraper_type,
            None,
            is_test=is_test
        )
        
        filter_stats = None
        if hasattr(self.enricher, '_last_filter_stats'):
            stats = self.enricher._last_filter_stats
            if stats:
                filter_stats = {
                    'total': stats.get('total', 0),
                    'filtered': stats.get('filtered', 0),
                    'approved': stats.get('approved', 0),
                    'scraper_name': stats.get('scraper_name', '')
                }
        
        self.processor.sanitize_torrents(enriched_torrents)
        self.processor.remove_internal_fields(enriched_torrents)
        
        if not (is_test and Config.EMPTY_QUERY_MAX_LINKS > 0):
            self.processor.sort_by_date(enriched_torrents)
        
        return enriched_torrents, filter_stats
    
    async def _enrich_torrents_async(
        self,
        torrents: List[Dict],
        scraper_type: str,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        is_test: bool = False
    ) -> List[Dict]:
        """Enriquece torrents usando enricher async."""
        from scraper import available_scraper_types
        
        scraper_name = None
        types_info = available_scraper_types()
        normalized_type = scraper_type.lower().strip()
        if normalized_type in types_info:
            scraper_name = types_info[normalized_type].get('display_name', scraper_type)
        else:
            scraper_name = scraper_type
        
        skip_metadata = False
        skip_trackers = False
        
        if is_test:
            skip_metadata = True
            skip_trackers = True
        
        enriched = await self.enricher.enrich(
            torrents,
            skip_metadata=skip_metadata,
            skip_trackers=skip_trackers,
            filter_func=filter_func,
            scraper_name=scraper_name
        )
        
        return enriched
    
    def get_scraper_info(self) -> Dict:
        """Obtém informações dos scrapers disponíveis."""
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
        """Valida tipo de scraper e retorna tipo normalizado."""
        if scraper_type in SCRAPER_NUMBER_MAP:
            mapped_type = SCRAPER_NUMBER_MAP[scraper_type]
            if mapped_type is None:
                return False, None
            scraper_type = mapped_type
        
        types_info = available_scraper_types()
        normalized_type = normalize_scraper_type(scraper_type)
        
        if normalized_type not in types_info:
            return False, None
        
        return True, normalized_type
    
    async def close(self):
        """Fecha recursos async."""
        await self.enricher.close()


# Função helper para executar código async em contexto síncrono
def run_async(coro):
    """Executa corrotina em loop de eventos existente ou cria novo."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Se já há um loop rodando, cria task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # Não há loop, cria novo
        return asyncio.run(coro)

