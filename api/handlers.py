"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from datetime import datetime
from typing import Dict
from flask import jsonify, request
from app.config import Config
from scraper import (
    create_scraper,
    available_scraper_types,
    normalize_scraper_type,
)
from utils.text_processing import check_query_match

logger = logging.getLogger(__name__)


def index_handler():
    """Handler para endpoint raiz - informações da API"""
    types_info = available_scraper_types()
    sites_dict = {
        scraper_type: meta.get('default_url')
        for scraper_type, meta in types_info.items()
        if meta.get('default_url')
    }
    endpoints = {
        '/indexer': {
            'method': 'GET',
            'description': 'Indexador usando o scraper padrão',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'filter_results': 'filtrar resultados com similaridade zero (true/false)'
            }
        },
        '/indexers/<site_name>': {
            'method': 'GET',
            'description': 'Indexador específico (utilize o tipo do scraper)',
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
        'configured_sites': sites_dict,
        'available_types': list(types_info.keys())
    })


def indexer_handler(site_name: str = None):
    """Handler principal do indexador"""
    display_label = 'UNKNOWN'
    normalized_type = 'UNKNOWN'
    
    try:
        query = request.args.get('q', '')
        page = request.args.get('page', '1')
        filter_results = request.args.get('filter_results', 'false').lower() == 'true'
        types_info = available_scraper_types()
        available_types = list(types_info.keys())
        
        # Determina qual site usar
        if site_name:
            normalized_type = normalize_scraper_type(site_name)
            if normalized_type not in types_info:
                return jsonify({
                    'error': (
                        f'Scraper "{site_name}" não configurado. '
                        f'Tipos disponíveis: {available_types}'
                    ),
                    'results': [],
                    'count': 0
                }), 404
            display_label = types_info[normalized_type].get('display_name', site_name)
        else:
            # Usa scraper padrão configurado
            normalized_type = normalize_scraper_type(Config.DEFAULT_SCRAPER_TYPE)
            if normalized_type not in types_info:
                normalized_type = available_types[0] if available_types else ''
            metadata = types_info.get(normalized_type, {})
            display_label = metadata.get('display_name', normalized_type or 'UNKNOWN')
            if not normalized_type:
                raise ValueError('Nenhum scraper disponível para processar a requisição.')

        metadata = types_info.get(normalized_type, {})
        display_label = metadata.get('display_name', display_label or normalized_type)
        log_prefix = f"[{display_label}]"

        # Log com tipo de site
        logger.info(f"{log_prefix} Query: '{query}' | Page: {page} | Filter: {filter_results}")
        
        # Obtém o scraper correto baseado no tipo
        scraper = create_scraper(normalized_type)
        
        # Detecta se é teste do Prowlarr (query vazia)
        is_prowlarr_test = not query
        
        # Prepara função de filtro se necessário (para aplicar ANTES do enriquecimento)
        filter_func = None
        if filter_results and query:
            def filter_func(torrent: Dict) -> bool:
                return check_query_match(
                    query,
                    torrent.get('title', ''),
                    torrent.get('original_title', '')
                )
        
        if query:
            # Busca - passa filtro para aplicar antes do enriquecimento
            torrents = scraper.search(query, filter_func=filter_func)
        else:
            # Lista da página - para teste do Prowlarr, usa limite padrão do BaseScraper (3)
            if is_prowlarr_test:
                # Para teste do Prowlarr, usa limite padrão (3) definido no BaseScraper
                torrents = scraper.get_page(page)  # max_items=None usa padrão de 3
                logger.info(f"{log_prefix} TEST - Processando apenas 3 itens (padrão)")
            else:
                torrents = scraper.get_page(page)
        
        logger.info(f"{log_prefix} Extraídos {len(torrents)} torrents antes do filtro")
        
        # Filtra resultados se solicitado - verifica se tem pelo menos uma palavra da query
        # NOTA: O filtro ainda é aplicado aqui para compatibilidade, mas idealmente deveria
        # ser aplicado dentro do scraper antes do enrich_torrents para melhor performance
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
        
        suffix = " filtrados" if filter_results and query else ""
        logger.info(f"{log_prefix} Retornando {len(torrents)} resultados{suffix}")
        
        # Remove campos internos antes de retornar
        for torrent in torrents:
            torrent.pop('_metadata', None)
            torrent.pop('_metadata_fetched', None)
        
        return jsonify({
            'results': torrents,
            'count': len(torrents)
        })
    
    except Exception as e:
        site_info = f"[{display_label}]" if 'display_label' in locals() else "[UNKNOWN]"
        logger.error(f"{site_info} Erro no handler indexer: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'results': [],
            'count': 0
        }), 500

