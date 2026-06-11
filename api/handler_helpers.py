# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from flask import Request

from app.config import Config
from core.processors.torrent_processor import TorrentProcessor

logger = logging.getLogger(__name__)

_indexed_count_cache = {'value': 0, 'ts': 0.0}

def get_indexed_torrents_count() -> int:
    ttl = float(getattr(Config, 'INDEXED_COUNT_CACHE_TTL', 60.0) or 0.0)
    now = time.time()
    if ttl > 0 and (now - _indexed_count_cache['ts']) < ttl:
        return int(_indexed_count_cache['value'])

    try:
        from cache.redis_client import get_redis_client

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
    # Busca com termo sempre filtra por similaridade (Prowlarr, web, etc.).
    # Só desliga com debug_no_filter=true (uso interno / script_api_check).
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
    """Registra estatísticas de filtro no formato padrão do projeto."""
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
    """Logs de diagnóstico antes de retornar a resposta."""
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
