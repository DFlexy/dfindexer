"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from datetime import datetime
from flask import jsonify, request
from app.config import Config
from api.services.indexer_service import IndexerService
from scraper import available_scraper_types

logger = logging.getLogger(__name__)

# Instância do serviço de indexação
_indexer_service = IndexerService()


# Handler para endpoint raiz - informações da API
def index_handler():
    scraper_info = _indexer_service.get_scraper_info()
    endpoints = {
        '/indexer': {
            'method': 'GET',
            'description': 'Indexador usando o scraper padrão',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'filter_results': 'filtrar resultados com similaridade zero (true/false)',
                'use_flaresolverr': 'usar FlareSolverr para resolver Cloudflare (true/false)'
            }
        },
        '/indexers/<site_name>': {
            'method': 'GET',
            'description': 'Indexador específico (utilize o tipo do scraper)',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'filter_results': 'filtrar resultados com similaridade zero (true/false)',
                'use_flaresolverr': 'usar FlareSolverr para resolver Cloudflare (true/false)'
            }
        }
    }
    
    return jsonify({
        'time': datetime.now().strftime('%A, %d-%b-%y %H:%M:%S UTC'),
        'build': 'Python Torrent Indexer v1.0.0',
        'endpoints': endpoints,
        'configured_sites': scraper_info['configured_sites'],
        'available_types': scraper_info['available_types']
    })


# Handler principal do indexador
def indexer_handler(site_name: str = None):
    display_label = 'UNKNOWN'
    normalized_type = 'UNKNOWN'
    
    try:
        query = request.args.get('q', '')
        page = request.args.get('page', '1')
        filter_results = request.args.get('filter_results', 'false').lower() == 'true'
        use_flaresolverr = request.args.get('use_flaresolverr', 'false').lower() == 'true'
        
        types_info = available_scraper_types()
        available_types = list(types_info.keys())
        
        # Determina qual site usar
        if site_name:
            is_valid, normalized_type = _indexer_service.validate_scraper_type(site_name)
            if not is_valid:
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
            is_valid, normalized_type = _indexer_service.validate_scraper_type(Config.DEFAULT_SCRAPER_TYPE)
            if not is_valid:
                normalized_type = available_types[0] if available_types else ''
            if not normalized_type:
                raise ValueError('Nenhum scraper disponível para processar a requisição.')
            display_label = types_info[normalized_type].get('display_name', normalized_type)

        log_prefix = f"[{display_label}]"
        logger.info(f"{log_prefix} Query: '{query}' | Page: {page} | Filter: {filter_results} | FlareSolverr: {use_flaresolverr}")
        
        # Detecta se é teste do Prowlarr (query vazia)
        is_prowlarr_test = not query
        
        # Usa serviço para buscar torrents
        if query:
            torrents = _indexer_service.search(normalized_type, query, use_flaresolverr, filter_results)
        else:
            torrents = _indexer_service.get_page(normalized_type, page, use_flaresolverr, is_prowlarr_test)
        
        # Log de estatísticas do filtro (sempre mostra quando disponível)
        filter_stats = _indexer_service.get_last_filter_stats()
        if filter_stats:
            logger.info(f"{log_prefix} [Filtro Aplicado] Total: {filter_stats['total']} | Filtrados: {filter_stats['filtered']} | Aprovados: {filter_stats['approved']}")
        else:
            # Se não há estatísticas disponíveis, mostra log simples com contagem
            logger.info(f"{log_prefix} [Filtro Aplicado] Total: {len(torrents)} | Filtrados: 0 | Aprovados: {len(torrents)}")
        
        # Prepara resposta JSON
        response_data = {
            'results': torrents,
            'count': len(torrents)
        }
        
        # Adiciona indicador de teste quando for query de teste
        if is_prowlarr_test:
            response_data['teste'] = True
        
        return jsonify(response_data)
    
    except Exception as e:
        site_info = f"[{display_label}]" if 'display_label' in locals() else "[UNKNOWN]"
        logger.error(f"{site_info} Erro no handler indexer: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'results': [],
            'count': 0
        }), 500

