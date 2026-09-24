# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, Request, jsonify, make_response, render_template, request

from api.indexer_service import (
    IndexerServiceAsync,
    fetch_all_scrapers_index,
    get_scraper_info,
    is_removed_legacy_id,
    run_async,
    validate_scraper_type,
)
from app.config import Config
from core.torrent_processor import TorrentProcessor
from scraper import available_scraper_types
from utils.http import is_proxy_enabled

logger = logging.getLogger(__name__)

def format_log_flag(value: bool) -> str:
    return 'ON' if value else 'OFF'

_indexed_count_cache = {'value': 0, 'ts': 0.0}

def get_indexed_torrents_count() -> int:
    ttl = float(getattr(Config, 'INDEXED_COUNT_CACHE_TTL', 60.0) or 0.0)
    now = time.time()
    if ttl > 0 and (now - _indexed_count_cache['ts']) < ttl:
        return int(_indexed_count_cache['value'])

    try:
        from cache.store import get_redis_client

        redis = get_redis_client()
        if not redis:
            return 0

        count = 0
        cursor = 0
        pattern = 'cross:torrent:*'

        while True:
            cursor, keys = redis.scan(cursor, match=pattern, count=1000)
            count += len(keys)
            if cursor == 0:
                break

        _indexed_count_cache['value'] = count
        _indexed_count_cache['ts'] = now
        return count
    except Exception as e:
        logger.debug('Erro ao contar torrents indexados: %s', type(e).__name__)
        return 0

def parse_request_params(req: Request) -> Dict[str, Any]:
    query = req.args.get('q', '')
    page = req.args.get('page', '1')
    has_query = bool(query and query.strip())
    debug_no_filter = req.args.get('debug_no_filter', 'false').lower() == 'true'
    filter_results = has_query and not debug_no_filter
    use_flaresolverr = req.args.get('use_flaresolverr', 'false').lower() == 'true'

    max_results = None
    max_results_raw = req.args.get('max_results', None)
    if max_results_raw:
        try:
            max_results = int(str(max_results_raw).strip())
            if max_results <= 0:
                max_results = None
        except (ValueError, TypeError):
            max_results = None

    return {
        'query': query,
        'page': page,
        'filter_results': filter_results,
        'use_flaresolverr': use_flaresolverr,
        'max_results': max_results,
        'is_prowlarr_test': not query,
        'has_query': has_query,
    }

def count_unique_hashes(torrents: List[Dict]) -> int:
    unique_hashes = set()
    for torrent in torrents:
        info_hash = torrent.get('info_hash', '')
        if info_hash:
            unique_hashes.add(info_hash.lower())
    return len(unique_hashes)

def log_filter_stats(
    log_prefix: str,
    query: str,
    filter_stats: Optional[Dict],
    torrents: List[Dict],
    scraper_label: Optional[str] = None,
    filter_results: bool = False,
) -> None:
    prefix = log_prefix
    if scraper_label:
        prefix = f'{log_prefix} [{scraper_label}]'

    query_display = query if query else ''

    if filter_stats:
        total_unique = count_unique_hashes(torrents)
        total_stats = filter_stats.get('total', total_unique)
        filtered_stats = filter_stats.get('filtered', 0)
        approved_stats = filter_stats.get('approved', total_unique)
        logger.info(
            '%s  Query: \'%s\' | Filter: %s | Total: %s | Rejeitados: %s | Aprovados: %s',
            prefix,
            query_display,
            filter_results,
            total_stats,
            filtered_stats,
            approved_stats,
        )
    else:
        total_unique = count_unique_hashes(torrents)
        logger.info(
            '%s  Query: \'%s\' | Filter: %s | Total: %s | Rejeitados: 0 | Aprovados: %s',
            prefix,
            query_display,
            filter_results,
            total_unique,
            total_unique,
        )

def validate_torrent_results(
    torrents: List[Dict],
    log_prefix: str,
) -> Tuple[List[Dict], Optional[Dict]]:
    valid_torrents: List[Dict] = []
    removed_count = 0
    removed_details: List[str] = []

    for torrent in torrents:
        has_title = torrent.get('title') or torrent.get('title_processed')
        has_magnet = torrent.get('magnet_link') or torrent.get('magnet')
        has_info_hash = torrent.get('info_hash')
        has_details = torrent.get('details')

        if not has_title or not has_magnet or not has_info_hash or not has_details:
            removed_count += 1
            title_preview = (torrent.get('title') or torrent.get('title_processed') or 'N/A')[:60]
            missing_fields = []
            if not has_title:
                missing_fields.append('title')
            if not has_magnet:
                missing_fields.append('magnet')
            if not has_info_hash:
                missing_fields.append('info_hash')
            if not has_details:
                missing_fields.append('details')

            removed_details.append(f'{title_preview} (faltam: {", ".join(missing_fields)})')
            logger.warning(
                '%s Removendo resultado inválido: %s | Faltam campos: %s',
                log_prefix,
                title_preview,
                ', '.join(missing_fields),
            )
            continue

        valid_torrents.append(torrent)

    if removed_count > 0:
        logger.warning(
            '%s %s resultados removidos na validação final. Antes: %s, Depois: %s',
            log_prefix,
            removed_count,
            len(torrents) + removed_count,
            len(valid_torrents),
        )
        for detail in removed_details[:5]:
            logger.warning('%s   - %s', log_prefix, detail)

    return valid_torrents, {'removed_count': removed_count} if removed_count else None

def log_response_diagnostics(
    torrents: List[Dict],
    filter_stats: Optional[Dict],
    log_prefix: str,
) -> None:
    if torrents and filter_stats and filter_stats.get('approved', 0) > len(torrents):
        logger.warning(
            '%s DISCREPÂNCIA: %s aprovados pelo filtro, mas apenas %s resultados válidos após validação final',
            log_prefix,
            filter_stats.get('approved', 0),
            len(torrents),
        )
        titles_list = [t.get('title') or t.get('title_processed', 'N/A')[:50] for t in torrents]
        logger.info(
            '%s Resultados que serão retornados (%s): %s',
            log_prefix,
            len(torrents),
            ', '.join(titles_list),
        )

    if torrents:
        sample_torrent = torrents[0]
        required_fields = ['title', 'magnet_link', 'info_hash', 'details', 'seed_count', 'leech_count']
        missing_fields = [
            field for field in required_fields
            if not sample_torrent.get(field) and sample_torrent.get(field) != 0
        ]
        if missing_fields:
            logger.warning('%s Campos obrigatórios faltando no resultado: %s', log_prefix, missing_fields)
    elif filter_stats and filter_stats.get('approved', 0) > 0:
        logger.warning(
            '%s %s resultados aprovados, mas nenhum válido após validação final',
            log_prefix,
            filter_stats.get('approved', 0),
        )

def combine_all_scrapers_stats(all_filter_stats: List[Optional[Dict]]) -> Optional[Dict]:
    if not all_filter_stats:
        return None
    return {
        'total': sum(s.get('total', 0) for s in all_filter_stats),
        'filtered': sum(s.get('filtered', 0) for s in all_filter_stats),
        'approved': sum(s.get('approved', 0) for s in all_filter_stats),
        'scraper_name': 'TODOS',
    }

def sort_torrents_by_date(torrents: List[Dict]) -> None:
    processor = TorrentProcessor()
    processor.sort_by_date(torrents)

_indexer_service = IndexerServiceAsync()

def health_handler():
    return jsonify({'status': 'ok'}), 200

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

    except TimeoutError as e:
        site_info = f'[{display_label}]' if display_label != 'UNKNOWN' else '[UNKNOWN]'
        error_msg = str(e).split('\n')[0][:100] if str(e) else 'tempo limite excedido'
        logger.warning('%s Site indisponível ou lento: %s', site_info, error_msg)
        return jsonify({'results': [], 'count': 0}), 200
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

def register_routes(app: Flask):
    app.add_url_rule('/', 'index', index_handler, methods=['GET'])
    app.add_url_rule('/health', 'health', health_handler, methods=['GET'])
    app.add_url_rule('/indexer', 'indexer', lambda: indexer_handler(None), methods=['GET'])
    app.add_url_rule('/indexers/<site_name>', 'indexer_by_site', indexer_handler, methods=['GET'])
    app.add_url_rule('/api', 'search_page', search_page_handler, methods=['GET'])

def search_page_handler():
    response = make_response(render_template('search.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
