"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import asyncio
from datetime import datetime
from flask import jsonify, request
from app.config import Config
from api.services.indexer_service import IndexerService, SCRAPER_NUMBER_MAP
from api.services.indexer_service_async import IndexerServiceAsync, run_async
from scraper import available_scraper_types

logger = logging.getLogger(__name__)

_indexer_service = IndexerService()
_indexer_service_async = IndexerServiceAsync()

# Flag para habilitar async (pode ser controlado por variável de ambiente)
USE_ASYNC = True  # Habilita async por padrão


def _get_indexed_torrents_count() -> int:
    """
    Obtém a contagem total de torrents indexados no Redis.
    Conta as chaves cross:torrent:* que representam torrents únicos.
    """
    try:
        from cache.redis_client import get_redis_client
        
        redis = get_redis_client()
        if not redis:
            return 0
        
        # Conta todas as chaves que começam com "cross:torrent:"
        # Usa SCAN para evitar bloquear o Redis em produção
        count = 0
        cursor = 0
        pattern = "cross:torrent:*"
        
        while True:
            cursor, keys = redis.scan(cursor, match=pattern, count=1000)
            count += len(keys)
            if cursor == 0:
                break
        
        return count
    except Exception as e:
        logger.debug(f"Erro ao contar torrents indexados: {type(e).__name__}")
        return 0


def index_handler():
    scraper_info = _indexer_service.get_scraper_info()
    indexed_count = _get_indexed_torrents_count()
    
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
        'available_types': scraper_info['available_types'],
        'indexed_torrents': indexed_count
    })


def indexer_handler(site_name: str = None):
    display_label = 'UNKNOWN'
    normalized_type = 'UNKNOWN'
    
    try:
        query = request.args.get('q', '')
        page = request.args.get('page', '1')
        filter_results = request.args.get('filter_results', 'false').lower() == 'true'
        use_flaresolverr = request.args.get('use_flaresolverr', 'false').lower() == 'true'
        
        # Limita quantidade de resultados processados/enriquecidos (útil para scripts de debug)
        max_results = None
        max_results_raw = request.args.get('max_results', None)
        if max_results_raw:
            try:
                max_results = int(str(max_results_raw).strip())
                if max_results <= 0:
                    max_results = None
            except (ValueError, TypeError):
                max_results = None
        
        types_info = available_scraper_types()
        available_types = list(types_info.keys())
        
        if site_name:
            is_valid, normalized_type = _indexer_service.validate_scraper_type(site_name)
            if not is_valid:
                # Verifica se é um ID removido (None no mapeamento)
                # Para IDs removidos, retorna resposta vazia (200) em vez de 404
                # Isso evita que o Prowlarr marque o indexer como indisponível
                if site_name in SCRAPER_NUMBER_MAP and SCRAPER_NUMBER_MAP[site_name] is None:
                    logger.warning(f"Tentativa de usar scraper ID removido: {site_name}")
                    return jsonify({
                        'results': [],
                        'count': 0
                    }), 200
                else:
                    return jsonify({
                        'error': (
                            f'Scraper "{site_name}" não configurado. '
                            f'Tipos disponíveis: {available_types}'
                        ),
                        'results': [],
                        'count': 0
                    }), 404
            display_label = types_info[normalized_type].get('display_name', site_name)
            log_prefix = f"[{display_label}]"
            # Mostra se o filtro será aplicado (sempre True quando há query, independente do parâmetro)
            filter_will_be_applied = bool(query and len(query.strip()) > 0)
            logger.info(f"{log_prefix} Query: '{query}' | Page: {page} | Filter: {filter_will_be_applied} | FlareSolverr: {use_flaresolverr}")
        
        is_prowlarr_test = not query
        
        if site_name:
            # Busca apenas no scraper especificado
            if USE_ASYNC:
                if query:
                    torrents, filter_stats = run_async(
                        _indexer_service_async.search(normalized_type, query, use_flaresolverr, filter_results, max_results=max_results)
                    )
                else:
                    torrents, filter_stats = run_async(
                        _indexer_service_async.get_page(normalized_type, page, use_flaresolverr, is_prowlarr_test, max_results=max_results)
                    )
            else:
                # Fallback para versão síncrona
                if query:
                    torrents, filter_stats = _indexer_service.search(normalized_type, query, use_flaresolverr, filter_results, max_results=max_results)
                else:
                    torrents, filter_stats = _indexer_service.get_page(normalized_type, page, use_flaresolverr, is_prowlarr_test, max_results=max_results)
            
            # Log apenas após processamento completo e quando há resultados
            if torrents:
                if filter_stats:
                    # Conta hashes únicos (ignora duplicados do mesmo scraper)
                    unique_hashes = set()
                    for torrent in torrents:
                        info_hash = torrent.get('info_hash', '')
                        if info_hash:
                            unique_hashes.add(info_hash.lower())
                    
                    total_unique = len(unique_hashes)
                    
                    # Formato: Query: '...' | Filter: True/False | Total: X | Filtrados: Y | Aprovados: Z
                    query_display = query if query else ''
                    filter_status = 'True' if query and query.strip() else 'False'
                    logger.info(f"{log_prefix}  Query: '{query_display}' | Filter: {filter_status} | Total: {total_unique} | Filtrados: {filter_stats['filtered']} | Aprovados: {total_unique}")
                else:
                    # Conta hashes únicos (ignora duplicados do mesmo scraper)
                    unique_hashes = set()
                    for torrent in torrents:
                        info_hash = torrent.get('info_hash', '')
                        if info_hash:
                            unique_hashes.add(info_hash.lower())
                    
                    total_unique = len(unique_hashes)
                    
                    # Formato: Query: '...' | Filter: True/False | Total: X | Filtrados: Y | Aprovados: Z
                    query_display = query if query else ''
                    filter_status = 'True' if query and query.strip() else 'False'
                    logger.info(f"{log_prefix}  Query: '{query_display}' | Filter: {filter_status} | Total: {total_unique} | Filtrados: 0 | Aprovados: {total_unique}")
        else:
            # Busca em TODOS os scrapers quando não especificado
            log_prefix = "[TODOS]"
            # Mostra se o filtro será aplicado (sempre True quando há query, independente do parâmetro)
            filter_will_be_applied = bool(query and len(query.strip()) > 0)
            logger.info(f"{log_prefix} Query: '{query}' | Page: {page} | Filter: {filter_will_be_applied} | FlareSolverr: {use_flaresolverr}")
            
            is_prowlarr_test = not query
            all_torrents = []
            all_filter_stats = []
            
            # Busca em cada scraper disponível
            for scraper_type in available_types:
                try:
                    scraper_label = types_info[scraper_type].get('display_name', scraper_type)
                    logger.info(f"{log_prefix} Buscando em [{scraper_label}]...")
                    
                    if USE_ASYNC:
                        if query:
                            scraper_torrents, scraper_stats = run_async(
                                _indexer_service_async.search(scraper_type, query, use_flaresolverr, filter_results, max_results=max_results)
                            )
                        else:
                            scraper_torrents, scraper_stats = run_async(
                                _indexer_service_async.get_page(scraper_type, page, use_flaresolverr, is_prowlarr_test, max_results=max_results)
                            )
                    else:
                        if query:
                            scraper_torrents, scraper_stats = _indexer_service.search(scraper_type, query, use_flaresolverr, filter_results, max_results=max_results)
                        else:
                            scraper_torrents, scraper_stats = _indexer_service.get_page(scraper_type, page, use_flaresolverr, is_prowlarr_test, max_results=max_results)
                    
                    if scraper_torrents:
                        all_torrents.extend(scraper_torrents)
                        if scraper_stats:
                            all_filter_stats.append(scraper_stats)
                            
                            # Log individual por scraper apenas quando há resultados
                            # Conta hashes únicos neste scraper (ignora duplicados do mesmo scraper)
                            unique_hashes_in_scraper = set()
                            for torrent in scraper_torrents:
                                info_hash = torrent.get('info_hash', '')
                                if info_hash:
                                    unique_hashes_in_scraper.add(info_hash.lower())
                            
                            total_unique = len(unique_hashes_in_scraper)
                            
                            # Log individual por scraper - mostra apenas únicos (sem duplicados internos)
                            # Formato: Query: '...' | Filter: True/False | Total: X | Filtrados: Y | Aprovados: Z
                            if total_unique > 0:
                                query_display = query if query else ''
                                filter_status = 'True' if query and query.strip() else 'False'
                                logger.info(f"{log_prefix} [{scraper_label}]  Query: '{query_display}' | Filter: {filter_status} | Total: {total_unique} | Filtrados: {scraper_stats.get('filtered', 0)} | Aprovados: {total_unique}")
                        if scraper_torrents:
                            logger.info(f"{log_prefix} [{scraper_label}] Encontrados: {len(scraper_torrents)} resultados")
                except Exception as e:
                    logger.warning(f"{log_prefix} Erro ao buscar em [{scraper_type}]: {e}")
                    continue
            
            # Não remove duplicados - mantém todos os magnets encontrados
            # Ordena por data (mais recente primeiro)
            from core.processors.torrent_processor import TorrentProcessor
            processor = TorrentProcessor()
            processor.sort_by_date(all_torrents)
            
            torrents = all_torrents
            
            # Combina estatísticas de todos os scrapers
            # Log apenas após processamento completo e quando há resultados
            if torrents:
                # Formato: Query: '...' | Filter: True/False | Total: X | Filtrados: Y | Aprovados: Z
                query_display = query if query else ''
                filter_status = 'True' if query and query.strip() else 'False'
                if all_filter_stats:
                    total_combined = sum(s.get('total', 0) for s in all_filter_stats)
                    filtered_combined = sum(s.get('filtered', 0) for s in all_filter_stats)
                    approved_combined = sum(s.get('approved', 0) for s in all_filter_stats)
                    filter_stats = {
                        'total': total_combined,
                        'filtered': filtered_combined,
                        'approved': approved_combined,
                        'scraper_name': 'TODOS'
                    }
                    logger.info(f"{log_prefix}  Query: '{query_display}' | Filter: {filter_status} | Total: {filter_stats['total']} | Filtrados: {filter_stats['filtered']} | Aprovados: {filter_stats['approved']}")
                else:
                    logger.info(f"{log_prefix}  Query: '{query_display}' | Filter: {filter_status} | Total: {len(torrents)} | Filtrados: 0 | Aprovados: {len(torrents)}")
                    filter_stats = None
            else:
                filter_stats = None
        
        # Validação final: garante que todos os resultados tenham campos obrigatórios
        # Remove resultados inválidos que não podem ser exibidos no Prowlarr
        valid_torrents = []
        for torrent in torrents:
            # Campos obrigatórios para Prowlarr
            has_title = torrent.get('title') or torrent.get('title_processed')
            has_magnet = torrent.get('magnet_link') or torrent.get('magnet')
            has_info_hash = torrent.get('info_hash')
            has_details = torrent.get('details')
            
            # Se faltar algum campo crítico, remove o resultado
            if not has_title or not has_magnet or not has_info_hash or not has_details:
                logger.debug(f"{log_prefix if 'log_prefix' in locals() else '[UNKNOWN]'} Removendo resultado inválido (faltam campos obrigatórios): title={bool(has_title)}, magnet={bool(has_magnet)}, info_hash={bool(has_info_hash)}, details={bool(has_details)}")
                continue
            
            valid_torrents.append(torrent)
        
        # Atualiza lista de torrents com apenas os válidos
        torrents = valid_torrents
        
        response_data = {
            'results': torrents,
            'count': len(torrents)
        }
        
        if is_prowlarr_test:
            response_data['teste'] = True
        
        # Log de debug: verifica se há resultados e se têm campos obrigatórios
        if torrents:
            sample_torrent = torrents[0] if torrents else {}
            required_fields = ['title', 'magnet_link', 'info_hash', 'details', 'seed_count', 'leech_count']
            missing_fields = [field for field in required_fields if not sample_torrent.get(field) and sample_torrent.get(field) != 0]
            if missing_fields:
                logger.warning(f"{log_prefix if 'log_prefix' in locals() else '[UNKNOWN]'} Campos obrigatórios faltando no resultado: {missing_fields}")
        elif len(torrents) == 0 and filter_stats and filter_stats.get('approved', 0) > 0:
            # Se há resultados aprovados mas nenhum válido, loga aviso
            logger.warning(f"{log_prefix if 'log_prefix' in locals() else '[UNKNOWN]'} {filter_stats.get('approved', 0)} resultados aprovados, mas nenhum válido após validação final")
        
        return jsonify(response_data)
    
    except ValueError as e:
        # Erro de validação (scraper inválido, query inválida, etc.)
        site_info = f"[{display_label}]" if 'display_label' in locals() else "[UNKNOWN]"
        error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
        logger.warning(f"{site_info} Validation error: {error_msg}")
        return jsonify({
            'error': str(e),
            'results': [],
            'count': 0
        }), 400
    except KeyError as e:
        # Erro de chave ausente (configuração, etc.)
        site_info = f"[{display_label}]" if 'display_label' in locals() else "[UNKNOWN]"
        error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
        logger.error(f"{site_info} Configuration error: {error_msg}", exc_info=True)
        return jsonify({
            'error': 'Configuration error',
            'results': [],
            'count': 0
        }), 500
    except Exception as e:
        # Erro genérico (manter como fallback, mas logar detalhadamente)
        site_info = f"[{display_label}]" if 'display_label' in locals() else "[UNKNOWN]"
        error_type = type(e).__name__
        error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
        logger.error(f"{site_info} Unexpected error: {error_type} - {error_msg}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'results': [],
            'count': 0
        }), 500

