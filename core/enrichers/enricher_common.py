# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

"""Lógica compartilhada entre TorrentEnricher (sync) e TorrentEnricherAsync.

Concentra os fallbacks de size/date/IMDB, o acesso em lote ao cross_data
(pipeline Redis) e a persistência do nome de metadata — antes duplicados
nos dois enrichers.
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from magnet.parser import MagnetParser
from utils.text.utils import format_bytes

logger = logging.getLogger(__name__)


def parse_cross_data(raw_map: Dict[bytes, bytes]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for field, value in (raw_map or {}).items():
        field_str = field.decode('utf-8')
        value_str = value.decode('utf-8')
        if field_str in ('missing_dn', 'has_legenda'):
            parsed[field_str] = value_str.lower() == 'true'
        elif field_str in ('tracker_seed', 'tracker_leech'):
            try:
                parsed[field_str] = int(value_str) if value_str and value_str != 'N/A' else 0
            except (TypeError, ValueError):
                parsed[field_str] = 0
        else:
            parsed[field_str] = value_str if value_str and value_str != 'N/A' else None
    return parsed


def bulk_get_cross_data(info_hashes: List[str]) -> Dict[str, Dict[str, Any]]:
    """Busca cross_data de vários hashes numa única viagem ao Redis (pipeline)."""
    from cache.redis_client import get_redis_client
    from cache.redis_keys import torrent_cross_data_key

    normalized = [
        str(h).strip().lower()
        for h in info_hashes
        if h and len(str(h).strip()) == 40
    ]
    if not normalized:
        return {}
    redis = get_redis_client()
    if not redis:
        return {}
    try:
        pipe = redis.pipeline(transaction=False)
        for h in normalized:
            pipe.hgetall(torrent_cross_data_key(h))
        rows = pipe.execute()
    except Exception:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for info_hash, raw in zip(normalized, rows):
        if raw:
            parsed = parse_cross_data(raw)
            if parsed:
                result[info_hash] = parsed
    return result


def build_tracker_log_id(torrent: Dict, scraper_name: Optional[str], info_hash: str) -> str:
    log_parts = []
    if scraper_name:
        log_parts.append(f"[{scraper_name}]")
    title = torrent.get('title_processed', '')
    if title:
        log_parts.append(title[:120])
    log_parts.append(f"(hash: {info_hash})")
    return " ".join(log_parts)


def apply_size_fallback(
    torrents: List[Dict],
    skip_metadata: bool = False,
    cross_data_by_hash: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Preenche size: cross_data → metadata → param xl do magnet → HTML."""
    from utils.text.cross_data import save_cross_data_to_redis

    metadata_enabled = not skip_metadata
    if cross_data_by_hash is None:
        cross_data_by_hash = bulk_get_cross_data(
            [str(t.get('info_hash') or '').lower() for t in torrents]
        )

    def _save_size(info_hash: str, size: str) -> None:
        if info_hash and len(info_hash) == 40:
            try:
                save_cross_data_to_redis(info_hash, {'size': size})
            except Exception:
                pass

    for torrent in torrents:
        html_size = torrent.get('size', '')
        info_hash = (torrent.get('info_hash') or '').lower()
        magnet_link = torrent.get('magnet_link')
        if not magnet_link:
            continue

        cross_data = cross_data_by_hash.get(info_hash) if info_hash else None
        if cross_data and cross_data.get('size'):
            cross_size = cross_data.get('size')
            if cross_size and cross_size.strip() and cross_size != 'N/A':
                torrent['size'] = cross_size.strip()
                continue

        magnet_data = None
        try:
            magnet_data = MagnetParser.parse(magnet_link)
        except Exception:
            pass

        torrent['size'] = ''

        if metadata_enabled and torrent.get('_metadata') and 'size' in torrent['_metadata']:
            try:
                formatted_size = format_bytes(torrent['_metadata']['size'])
                if formatted_size:
                    torrent['size'] = formatted_size
                    _save_size(info_hash, formatted_size)
                    continue
            except Exception:
                pass

        if magnet_data:
            xl = magnet_data.get('params', {}).get('xl')
            if xl:
                try:
                    formatted_size = format_bytes(int(xl))
                    if formatted_size:
                        torrent['size'] = formatted_size
                        _save_size(info_hash, formatted_size)
                        continue
                except Exception:
                    pass

        if html_size:
            torrent['size'] = html_size
            _save_size(info_hash, html_size)


def apply_date_fallback(torrents: List[Dict], skip_metadata: bool = False) -> None:
    """Preenche date: metadata (creation date do .torrent) → data atual."""
    for torrent in torrents:
        if torrent.get('date', ''):
            continue

        if not skip_metadata and torrent.get('_metadata') and 'created_time' in torrent['_metadata']:
            try:
                created_time = torrent['_metadata']['created_time']
                if created_time:
                    if isinstance(created_time, str):
                        torrent['date'] = created_time
                    else:
                        torrent['date'] = datetime.fromtimestamp(created_time).strftime('%Y-%m-%dT%H:%M:%SZ')
                    continue
            except Exception:
                pass

        torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')


_IMDB_TECHNICAL_PATTERNS = [
    r'\.WEB-DL\.?', r'\.WEBRip\.?', r'\.BluRay\.?', r'\.DVDRip\.?',
    r'\.HDRip\.?', r'\.HDTV\.?', r'\.BDRip\.?', r'\.BRRip\.?',
    r'\.1080p\.?', r'\.720p\.?', r'\.2160p\.?', r'\.4K\.?',
    r'\.HD\.?', r'\.FHD\.?', r'\.UHD\.?', r'\.SD\.?', r'\.HDR\.?',
    r'\.x264\.?', r'\.x265\.?', r'\.HEVC\.?', r'\.AVC\.?',
    r'\.DUAL\.?', r'\.DUBLADO\.?', r'\.NACIONAL\.?',
    r'\.LEGENDADO\.?', r'\.LEGENDA\.?',
]


def extract_base_title_for_imdb(title: str) -> Optional[str]:
    """Normaliza o título para servir de chave de cache do IMDB (sem tags técnicas)."""
    from utils.text.cleaning import remove_accents

    if not title:
        return None

    title = re.sub(r'\s*\[Brazilian\]\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*\[Eng\]\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*\[br-dub\]\s*', '', title, flags=re.IGNORECASE)

    for pattern in _IMDB_TECHNICAL_PATTERNS:
        title = re.sub(pattern, '.', title, flags=re.IGNORECASE)

    title = re.sub(r'\.{2,}', '.', title)
    title = title.strip(' .')
    title = remove_accents(title)
    title = title.lower().strip()
    title = re.sub(r'\.+$', '', title)
    title = re.sub(r'\.+', '.', title)
    title = re.sub(r'\s+', ' ', title).strip()
    title = title.replace(' ', '.')
    title = re.sub(r'\.{2,}', '.', title)
    title = title.strip('.')

    return title if title and len(title) >= 3 else None


def _is_valid_imdb(value: Any) -> bool:
    return isinstance(value, str) and value.startswith('tt') and value[2:].isdigit()


def apply_imdb_fallback(torrents: List[Dict]) -> None:
    """Preenche imdb via cache Redis (por hash e por título) e metadata do .torrent."""
    from app.config import Config
    from cache.redis_client import get_redis_client
    from cache.redis_keys import imdb_key, imdb_title_key

    redis = get_redis_client()
    if not redis:
        return

    ttl = Config.IMDB_CACHE_TTL

    for torrent in torrents:
        imdb = (torrent.get('imdb') or '').strip()
        info_hash = (torrent.get('info_hash') or '').strip().lower()
        title = torrent.get('title_processed', '')
        base_title = extract_base_title_for_imdb(title)

        if _is_valid_imdb(imdb):
            try:
                if info_hash and len(info_hash) == 40:
                    redis.setex(imdb_key(info_hash), ttl, imdb)
                if base_title:
                    redis.setex(imdb_title_key(base_title), ttl, imdb)
            except Exception:
                pass
            continue

        if info_hash and len(info_hash) == 40:
            try:
                cached_imdb = redis.get(imdb_key(info_hash))
                if cached_imdb:
                    cached_imdb_str = cached_imdb.decode('utf-8')
                    if _is_valid_imdb(cached_imdb_str):
                        torrent['imdb'] = cached_imdb_str
                        continue
            except Exception:
                pass

        if base_title:
            try:
                cached_imdb = redis.get(imdb_title_key(base_title))
                if cached_imdb:
                    cached_imdb_str = cached_imdb.decode('utf-8')
                    if _is_valid_imdb(cached_imdb_str):
                        torrent['imdb'] = cached_imdb_str
                        continue
            except Exception:
                pass

        metadata = torrent.get('_metadata')
        if metadata and _is_valid_imdb(metadata.get('imdb')):
            imdb_from_metadata = metadata['imdb']
            torrent['imdb'] = imdb_from_metadata
            try:
                if info_hash and len(info_hash) == 40:
                    redis.setex(imdb_key(info_hash), ttl, imdb_from_metadata)
                if base_title:
                    redis.setex(imdb_title_key(base_title), ttl, imdb_from_metadata)
            except Exception:
                pass


def save_metadata_name_to_cross_data(torrent: Dict, metadata: Dict) -> None:
    """Persiste o nome real do .torrent no cross_data quando é mais completo que o atual."""
    try:
        info_hash = (torrent.get('info_hash') or '').lower()
        if not info_hash or len(info_hash) != 40:
            return

        metadata_name = metadata.get('name', '').strip() if metadata else None
        if not metadata_name or len(metadata_name) < 3:
            return

        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        from utils.text.storage import _is_metadata_more_complete
        from utils.text.title_builder import _normalize_metadata_name

        cross_data = get_cross_data_from_redis(info_hash)
        cross_magnet_processed = None
        if cross_data and cross_data.get('magnet_processed'):
            cross_magnet_processed = str(cross_data.get('magnet_processed')).strip()

        if not cross_magnet_processed or not _is_metadata_more_complete(metadata_name, cross_magnet_processed):
            normalized_metadata = _normalize_metadata_name(metadata_name)
            save_cross_data_to_redis(info_hash, {
                'metadata_name': metadata_name,
                'magnet_original': metadata_name,
                'magnet_processed': normalized_metadata,
            })
    except Exception:
        pass


def hydrate_torrent_from_cross_data(torrent: Dict, cross_data: Optional[Dict[str, Any]]) -> None:
    """Completa títulos/magnet_original do torrent a partir do cross_data do Redis."""
    if not cross_data:
        return
    from utils.text.storage import _looks_like_bludv_processed_release_name

    if not torrent.get('original_title') and cross_data.get('title_original_html'):
        torrent['original_title'] = cross_data.get('title_original_html', '')
    if not torrent.get('title_translated_processed') and cross_data.get('title_translated_html'):
        torrent['title_translated_processed'] = cross_data.get('title_translated_html', '')
    if cross_data.get('magnet_processed'):
        torrent['magnet_processed'] = cross_data.get('magnet_processed')
    if not (torrent.get('magnet_original') or '').strip():
        magnet_from_cross = cross_data.get('metadata_name') or cross_data.get('magnet_original')
        if magnet_from_cross and str(magnet_from_cross).strip() not in ('', 'N/A'):
            candidate = str(magnet_from_cross).strip()
            if not _looks_like_bludv_processed_release_name(candidate):
                torrent['magnet_original'] = candidate
