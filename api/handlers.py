"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from datetime import datetime
from typing import List, Dict, Optional
from flask import jsonify, request
from app.config import Config
from scraper.starck import StarckScraper
from scraper.rede_torrent import RedeTorrentScraper
from scraper.torrent_dos_filmes import TorrentDosFilmesScraper
from scraper.vaca_torrent import VacaTorrentScraper
from scraper.limaotorrent import LimaotorrentScraper
from scraper.base import BaseScraper
from utils.text_processing import check_query_match

logger = logging.getLogger(__name__)


def get_scraper(site_type: str, site_url: str) -> BaseScraper:
    """Retorna o scraper correto baseado no tipo do site"""
    scraper_map = {
        'starck': StarckScraper,
        'rede_torrent': RedeTorrentScraper,
        'torrent_dos_filmes': TorrentDosFilmesScraper,
        'vaca_torrent': VacaTorrentScraper,
        'limaotorrent': LimaotorrentScraper,
    }
    
    scraper_class = scraper_map.get(site_type.lower(), StarckScraper)
    return scraper_class(site_url)


def index_handler():
    """Handler para endpoint raiz - informações da API"""
    sites_dict = Config.get_sites_dict()
    endpoints = {
        '/indexer': {
            'method': 'GET',
            'description': 'Indexador usando site padrão (SITE1)',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'filter_results': 'filtrar resultados com similaridade zero (true/false)'
            }
        },
        '/indexers/<site_name>': {
            'method': 'GET',
            'description': 'Indexador específico (site1, site2, etc.)',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'filter_results': 'filtrar resultados com similaridade zero (true/false)'
            }
        }
    }
    
    return jsonify({
        'time': datetime.now().strftime('%A, %d-%b-%y %H:%M:%S UTC'),
        'build': 'Python Torrent Indexer v1.0.0',
        'endpoints': endpoints,
        'configured_sites': sites_dict
    })


def indexer_handler(site_name: str = None):
    """Handler principal do indexador"""
    display_site = 'UNKNOWN'
    site_type = 'UNKNOWN'
    
    try:
        query = request.args.get('q', '')
        page = request.args.get('page', '1')
        filter_results = request.args.get('filter_results', 'false').lower() == 'true'
        
        # Determina qual site usar
        if site_name:
            # Usa site específico do path
            site_url, site_type = Config.get_site_by_name(site_name)
            if not site_url:
                return jsonify({
                    'error': f'Site "{site_name}" não configurado. Sites disponíveis: {list(Config.get_sites_dict().keys())}',
                    'results': [],
                    'count': 0
                }), 404
            display_site = site_name
        else:
            # Usa SITE1 como padrão
            site_url = Config.SITE1
            site_type = Config.SITE1_TYPE
            display_site = 'site1'
            if not site_url:
                return jsonify({
                    'error': 'Nenhum site configurado. Configure SITE1, SITE2, etc.',
                    'results': [],
                    'count': 0
                }), 500
        
        # Log com tipo de site
        logger.info(f"[{display_site.upper()}:{site_type.upper()}] Query: '{query}' | Page: {page} | Filter: {filter_results}")
        
        # Obtém o scraper correto baseado no tipo
        scraper = get_scraper(site_type, site_url)
        
        # Detecta se é teste do Prowlarr (query vazia)
        is_prowlarr_test = not query
        
        if query:
            # Busca
            torrents = scraper.search(query)
        else:
            # Lista da página - para teste do Prowlarr, limita processamento
            if is_prowlarr_test:
                # Para teste do Prowlarr, limita links processados para melhor performance
                torrents = scraper.get_page(page, max_items=5)
                logger.info(f"[{display_site.upper()}:{site_type.upper()}] TEST - Processando apenas 5 itens")
            else:
                torrents = scraper.get_page(page)
        
        logger.info(f"[{display_site.upper()}:{site_type.upper()}] Extraídos {len(torrents)} torrents antes do filtro")
        
        # Filtra resultados se solicitado - verifica se tem pelo menos uma palavra da query
        if filter_results and query:
            # Filtra apenas quando filter_results=true E há query
            torrents = [
                t for t in torrents 
                if check_query_match(
                    query, 
                    t.get('title', ''), 
                    t.get('original_title', '')
                )
            ]
        elif is_prowlarr_test:
            # Se não há query (teste do Prowlarr), garante máximo de 5 resultados
            torrents = torrents[:5]
            if len(torrents) < 5:
                logger.info(f"[{display_site.upper()}:{site_type.upper()}] TEST - Retornando {len(torrents)} resultados")
        
        logger.info(f"[{display_site.upper()}:{site_type.upper()}] Retornando {len(torrents)} resultados")
        
        return jsonify({
            'results': torrents,
            'count': len(torrents)
        })
    
    except Exception as e:
        site_info = f"[{display_site.upper()}:{site_type.upper()}]" if 'display_site' in locals() else "[UNKNOWN]"
        logger.error(f"{site_info} Erro no handler indexer: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'results': [],
            'count': 0
        }), 500

