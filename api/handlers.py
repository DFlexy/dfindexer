# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from datetime import datetime

from flask import jsonify, request

from api.handler_helpers import (
    combine_all_scrapers_stats,
    count_unique_hashes,
    format_log_flag,
    get_indexed_torrents_count,
    log_filter_stats,
    log_response_diagnostics,
    parse_request_params,
    sort_torrents_by_date,
    validate_torrent_results,
)
from api.prowlarr_config import is_removed_legacy_id
from api.services.indexer_common import get_scraper_info, validate_scraper_type
from api.services.indexer_service_async import (
    IndexerServiceAsync,
    fetch_all_scrapers_index,
    run_async,
)
from scraper import available_scraper_types
from utils.http.proxy import is_proxy_enabled

logger = logging.getLogger(__name__)

_indexer_service = IndexerServiceAsync()

def index_handler():
    scraper_info = get_scraper_info()
    indexed_count = get_indexed_torrents_count()

    endpoints = {
        '/indexer': {
            'method': 'GET',
            'description': 'Indexador usando o scraper padrão',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'debug_no_filter': 'desligar filtro de similaridade em buscas (true/false, uso interno)',
                'use_flaresolverr': 'usar FlareSolverr para resolver Cloudflare (true/false)',
            },
        },
        '/indexers/<site_name>': {
            'method': 'GET',
            'description': 'Indexador específico (utilize o tipo do scraper)',
            'query_params': {
                'q': 'query de busca',
                'page': 'número da página',
                'debug_no_filter': 'desligar filtro de similaridade em buscas (true/false, uso interno)',
                'use_flaresolverr': 'usar FlareSolverr para resolver Cloudflare (true/false)',
            },
        },
    }

    return jsonify({
        'time': datetime.now().strftime('%A, %d-%b-%y %H:%M:%S UTC'),
        'build': 'Python Torrent Indexer v1.0.0',
        'endpoints': endpoints,
        'configured_sites': scraper_info['configured_sites'],
        'available_types': scraper_info['available_types'],
        'types_info': scraper_info['types_info'],
        'indexed_torrents': indexed_count,
    })

def _run_single_scraper(
    normalized_type: str,
    params: dict,
) -> tuple[list, object]:
    query = params['query']
    page = params['page']
    use_flaresolverr = params['use_flaresolverr']
    filter_results = params['filter_results']
    max_results = params['max_results']
    is_prowlarr_test = params['is_prowlarr_test']

    if query:
        return run_async(
            _indexer_service.search(
                normalized_type,
                query,
                use_flaresolverr,
                filter_results,
                max_results=max_results,
            )
        )
    return run_async(
        _indexer_service.get_page(
            normalized_type,
            page,
            use_flaresolverr,
            is_prowlarr_test,
            max_results=max_results,
        )
    )

def _run_all_scrapers(
    available_types: list,
    types_info: dict,
    params: dict,
) -> tuple[list, object]:
    query = params['query']
    page = params['page']
    use_flaresolverr = params['use_flaresolverr']
    filter_results = params['filter_results']
    max_results = params['max_results']
    is_prowlarr_test = params['is_prowlarr_test']
    has_query = params['has_query']

    log_prefix = '[TODOS]'
    logger.info(
        "%s Query: '%s' | Page: %s | Filter: %s | Proxy: %s | FlareSolverr: %s",
        log_prefix,
        query,
        page,
        format_log_flag(filter_results),
        format_log_flag(is_proxy_enabled()),
        format_log_flag(use_flaresolverr),
    )

    all_torrents, all_filter_stats, rows = run_async(
        fetch_all_scrapers_index(
            available_types,
            query,
            page,
            use_flaresolverr,
            filter_results,
            max_results,
            page_mode=not has_query,
            is_prowlarr_test=is_prowlarr_test,
        )
    )

    for scraper_type, scraper_torrents, scraper_stats in rows:
        scraper_label = types_info.get(scraper_type, {}).get('display_name', scraper_type)
        if not scraper_torrents:
            continue
        if scraper_stats and count_unique_hashes(scraper_torrents) > 0:
            log_filter_stats(
                log_prefix, query, scraper_stats, scraper_torrents, scraper_label,
                filter_results=filter_results,
            )
        logger.info('%s [%s] Encontrados: %s resultados', log_prefix, scraper_label, len(scraper_torrents))

    sort_torrents_by_date(all_torrents)

    filter_stats = None
    if all_torrents:
        query_display = query if query else ''
        combined = combine_all_scrapers_stats(all_filter_stats)
        if combined:
            filter_stats = combined
            logger.info(
                "%s  Query: '%s' | Filter: %s | Total: %s | Rejeitados: %s | Aprovados: %s",
                log_prefix,
                query_display,
                filter_results,
                filter_stats['total'],
                filter_stats['filtered'],
                filter_stats['approved'],
            )
        else:
            logger.info(
                "%s  Query: '%s' | Filter: %s | Total: %s | Rejeitados: 0 | Aprovados: %s",
                log_prefix,
                query_display,
                filter_results,
                len(all_torrents),
                len(all_torrents),
            )

    return all_torrents, filter_stats

def indexer_handler(site_name: str = None):
    display_label = 'UNKNOWN'
    normalized_type = 'UNKNOWN'
    log_prefix = '[UNKNOWN]'

    try:
        params = parse_request_params(request)
        query = params['query']
        page = params['page']
        use_flaresolverr = params['use_flaresolverr']
        has_query = params['has_query']
        is_prowlarr_test = params['is_prowlarr_test']

        types_info = available_scraper_types()
        available_types = list(types_info.keys())

        if site_name:
            is_valid, normalized_type = validate_scraper_type(site_name)
            if not is_valid:
                if is_removed_legacy_id(site_name):
                    logger.warning('Tentativa de usar scraper ID removido: %s', site_name)
                    return jsonify({'results': [], 'count': 0}), 200
                return jsonify({
                    'error': (
                        f'Scraper "{site_name}" não configurado. '
                        f'Tipos disponíveis: {available_types}'
                    ),
                    'results': [],
                    'count': 0,
                }), 404

            display_label = types_info[normalized_type].get('display_name', site_name)
            log_prefix = f'[{display_label}]'
            logger.info(
                "%s Query: '%s' | Page: %s | Filter: %s | Proxy: %s | FlareSolverr: %s",
                log_prefix,
                query,
                page,
                format_log_flag(params['filter_results']),
                format_log_flag(is_proxy_enabled()),
                format_log_flag(use_flaresolverr),
            )

            torrents, filter_stats = _run_single_scraper(normalized_type, params)

            if torrents:
                log_filter_stats(
                    log_prefix, query, filter_stats, torrents,
                    filter_results=params['filter_results'],
                )
        else:
            torrents, filter_stats = _run_all_scrapers(available_types, types_info, params)

        torrents, _ = validate_torrent_results(torrents, log_prefix)
        log_response_diagnostics(torrents, filter_stats, log_prefix)

        response_data = {
            'results': torrents,
            'count': len(torrents),
        }
        if is_prowlarr_test:
            response_data['teste'] = True

        return jsonify(response_data)

    except ValueError as e:
        site_info = f'[{display_label}]' if display_label != 'UNKNOWN' else '[UNKNOWN]'
        error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
        logger.warning('%s Validation error: %s', site_info, error_msg)
        return jsonify({'error': str(e), 'results': [], 'count': 0}), 400
    except KeyError as e:
        site_info = f'[{display_label}]' if display_label != 'UNKNOWN' else '[UNKNOWN]'
        error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
        logger.error('%s Configuration error: %s', site_info, error_msg, exc_info=True)
        return jsonify({'error': 'Configuration error', 'results': [], 'count': 0}), 500
    except Exception as e:
        site_info = f'[{display_label}]' if display_label != 'UNKNOWN' else '[UNKNOWN]'
        error_type = type(e).__name__
        error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
        logger.error('%s Unexpected error: %s - %s', site_info, error_type, error_msg, exc_info=True)
        return jsonify({'error': 'Internal server error', 'results': [], 'count': 0}), 500
