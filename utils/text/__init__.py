# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import unquote, urlparse

STOP_WORDS = [
    'the', 'my', 'a', 'an', 'and', 'of', 'to', 'in', 'for', 'or', 'as',
    'os', 'o', 'e', 'de', 'do', 'da', 'em', 'que', 'temporada', 'season',
    'gli', 'dei', 'del', 'della', 'delle', 'degli', 'dello', 'dall', 'dalla', 'dalle', 'dallo', 'dall\'',
    'los', 'las', 'del', 'de', 'el', 'la',
    'les', 'des', 'du', 'de', 'le', 'la'
]

RELEASE_CLEAN_REGEX = re.compile(
    r'(?i)(COMANDO\.TO|COMANDOTORRENTS|WWW\.BLUDV\.TV|BLUDV|WWW\.COMANDOTORRENTS|'
    r'TORRENTBR|BAIXEFILMES|\[EZTVx\.to\]|\[TGx\]|\[rartv\]|\[YTS\.MX\]|'
    r'TRUFFLE|ETHEL|FLUX|GalaxyRG|TOONSHUB|ERAI\.RAWS|HIDRATORRENTS\.ORG|NETFLIX|'
    r'WWW\.[A-Z0-9.-]+\.[A-Z]{2,}|\[ACESSE[^\]]*\])\s*-?\s*'
)

REGEX_MULTIPLE_SPACES = re.compile(r'\s+')
REGEX_MULTIPLE_DOTS = re.compile(r'\.{2,}')
REGEX_LEADING_TRAILING_DOTS = re.compile(r'^\.|\.$')
REGEX_SPACE_AROUND_DOTS = re.compile(r'\s*\.\s*')
REGEX_HTML_TAGS = re.compile(r'<[^>]+>')
REGEX_TITULO_TRADUZIDO_START = re.compile(r'(?i)^\s*T[íi]tulo\s+Traduzido\s*:?\s*')
REGEX_TITULO_TRADUZIDO_MIDDLE = re.compile(r'(?i)\s*T[íi]tulo\s+Traduzido\s*:?\s*')
REGEX_ORDINAL_ENTITIES = re.compile(r'&ord[fm];', re.IGNORECASE)
REGEX_TEMPORADA_ORDINAL = re.compile(r'(?i)\s*[0-9]+[ªº]\s*Temporada\s*')
REGEX_TEMPORADA_ORDINAL_ALT = re.compile(r'(?i)\s*[0-9]+[aªº]\s*Temporada\s*')
REGEX_SEASON_EPISODE = re.compile(r'(?i)\s*S\d{1,2}(?:E\d{1,2})?\s*')
REGEX_TEMPORADA_WORD = re.compile(r'(?i)\s*Temporada\s*')
REGEX_TORRENT_WORD = re.compile(r'(?i)\s*Torrent\s*')
REGEX_COMPLETA_NUMBER = re.compile(r'(\d+)\s*Complet[ao]\b', re.IGNORECASE)
REGEX_COMPLETA_WORD = re.compile(r'([A-Za-z]+)Complet[ao]\b', re.IGNORECASE)
REGEX_COMPLETA_STANDALONE = re.compile(r'\bComplet[ao]\b', re.IGNORECASE)
REGEX_AUDIO_WORDS = re.compile(r'(?i)\b(?:Dublado|DUBLADO|Nacional|NACIONAL|Portugues|PORTUGUES|Português|PORTUGUÊS)\b')
REGEX_SITE_WORDS = re.compile(r'(?i)\b(?:Download|DOWNLOAD|Assistir|ASSISTIR|Online|ONLINE|ou|OU|e|E)\b')
REGEX_DUPLICATE_WORDS = re.compile(r'\b(\w+)\s+\1\b', re.IGNORECASE)
CONTAINER_EXTENSIONS = frozenset({'mkv', 'mp4', 'avi', 'mpeg', 'mov'})
REGEX_CONTAINER_TOKEN = re.compile(
    r'(?i)(^|[.\s_-])(?:mkv|mp4|avi|mpeg|mov)(?=$|[.\s_-])'
)
REGEX_YEAR_PARENTHESES = re.compile(r'\s*\(((?:19|20)\d{2}(?:-\d{2})?)\)\s*')
REGEX_YEAR_END = re.compile(r'\s+(19|20)\d{2}\s*$')
REGEX_YEAR_IN_TITLE = re.compile(r'(19|20)\d{2}')
REGEX_SEASON_EPISODE_PATTERN = re.compile(r'(?i)S(\d{1,2})E(\d{1,2})')
REGEX_SEASON_ONLY_PATTERN = re.compile(r'(?i)S(\d{1,2})(?![E\d])')
REGEX_BRACKETS_CONTENT = re.compile(r'\[.*?\]')
REGEX_PARENTHESES_CONTENT = re.compile(r'\s*\([^)]*\)\s*')
REGEX_NON_LATIN_CHARS = re.compile(
    r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f'
    r'\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff'
    r'\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]'
)

def remove_accents(text: str) -> str:
    replacements = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N',
        'İ': 'I',
        'ı': 'i',
        'ş': 's', 'Ş': 'S',
        'ğ': 'g', 'Ğ': 'G',
        'ü': 'u', 'Ü': 'U',
        'ö': 'o', 'Ö': 'O'
    }
    return ''.join(replacements.get(c, c) for c in text)

def clean_title(title: str) -> str:
    cleaned = RELEASE_CLEAN_REGEX.sub('', title)
    cleaned = REGEX_MULTIPLE_SPACES.sub(' ', cleaned)
    cleaned = REGEX_MULTIPLE_DOTS.sub('.', cleaned)
    cleaned = REGEX_LEADING_TRAILING_DOTS.sub('', cleaned)
    cleaned = REGEX_SPACE_AROUND_DOTS.sub('.', cleaned)
    cleaned = REGEX_CONTAINER_TOKEN.sub(r'\1', cleaned)
    cleaned = REGEX_MULTIPLE_DOTS.sub('.', cleaned)
    cleaned = cleaned.strip('.')
    return cleaned.strip()

def clean_title_translated_processed(title_translated_processed: str) -> str:
    if not title_translated_processed:
        return ''

    title_translated_processed = str(title_translated_processed)

    while REGEX_HTML_TAGS.search(title_translated_processed):
        title_translated_processed = REGEX_HTML_TAGS.sub('', title_translated_processed)

    title_translated_processed = html.unescape(title_translated_processed)

    title_translated_processed = REGEX_TITULO_TRADUZIDO_START.sub('', title_translated_processed)
    title_translated_processed = REGEX_TITULO_TRADUZIDO_MIDDLE.sub('', title_translated_processed)

    title_translated_processed = REGEX_ORDINAL_ENTITIES.sub('', title_translated_processed)
    title_translated_processed = html.unescape(title_translated_processed)

    title_translated_processed = REGEX_TEMPORADA_ORDINAL.sub('', title_translated_processed)
    title_translated_processed = REGEX_TEMPORADA_ORDINAL_ALT.sub('', title_translated_processed)
    title_translated_processed = REGEX_SEASON_EPISODE.sub('', title_translated_processed)
    title_translated_processed = REGEX_TEMPORADA_WORD.sub('', title_translated_processed)

    title_translated_processed = REGEX_TORRENT_WORD.sub('', title_translated_processed)

    title_translated_processed = REGEX_COMPLETA_NUMBER.sub(r'\1', title_translated_processed)
    title_translated_processed = REGEX_COMPLETA_WORD.sub(r'\1', title_translated_processed)
    title_translated_processed = REGEX_COMPLETA_STANDALONE.sub('', title_translated_processed)

    title_translated_processed = REGEX_AUDIO_WORDS.sub('', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\b(?:Legendado|LEGENDADO|Legenda|LEGENDA|Leg|LEG)\b', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\b(?:Dual|DUAL)(?![\.\s]?(?:5\.1|2\.0|7\.1))\b', '', title_translated_processed)

    title_translated_processed = REGEX_SITE_WORDS.sub('', title_translated_processed)

    title_translated_processed = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*', '', title_translated_processed)
    title_translated_processed = re.sub(r'\s+(19|20)\d{2}\s*$', '', title_translated_processed)

    title_translated_processed = re.sub(r'(?i)\s*—\s*[^—]+Torrent\s*–\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*—\s*[^—]+$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*–\s*[^–]+$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*', '', title_translated_processed)

    title_translated_processed = re.sub(r'(?i).*?T[íi]tulo\s+Original:.*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i).*?IMDb:.*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i).*?Lançamento.*$', '', title_translated_processed)

    title_translated_processed = re.sub(r'([A-Za-z]+)\1+', r'\1', title_translated_processed, flags=re.IGNORECASE)
    words = title_translated_processed.split()
    if len(words) > 1:
        deduplicated_words = []
        prev_word_lower = None
        for word in words:
            word_lower = word.lower()
            if word_lower != prev_word_lower:
                deduplicated_words.append(word)
                prev_word_lower = word_lower
        title_translated_processed = ' '.join(deduplicated_words)

    title_translated_processed = title_translated_processed.rstrip(' .,:;—–-')

    title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()

    return title_translated_processed

def find_year_from_text(text: str, title: str) -> str:
    year_match = re.search(r'(?:Lançamento|Year):\s*.*?(\d{4})', text)
    if year_match:
        return year_match.group(1)

    year_match = re.search(r'\((\d{4})\)', title)
    if year_match:
        return year_match.group(1)

    return ''

def find_sizes_from_text(text: str) -> List[str]:
    sizes = re.findall(r'(\d+[\.,]?\d+)\s*(GB|MB)', text)
    return [f"{size[0]} {size[1]}" for size in sizes]

def format_bytes(size: int) -> str:
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    value = float(size)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"

logger = logging.getLogger(__name__)

def get_cross_data_from_redis(info_hash: str) -> Optional[Dict[str, Any]]:
    if not info_hash or len(info_hash) != 40:
        return None

    try:
        from cache.store import get_redis_client
        from cache.store import torrent_cross_data_key

        redis = get_redis_client()
        if not redis:
            return None

        info_hash_lower = info_hash.lower()
        key = torrent_cross_data_key(info_hash_lower)
        data = redis.hgetall(key)
        if not data:
            return None

        result = {}
        for field, value in data.items():
            field_str = field.decode('utf-8')
            value_str = value.decode('utf-8')

            if field_str == 'missing_dn':
                result[field_str] = value_str.lower() == 'true'
            elif field_str == 'has_legenda':
                result[field_str] = value_str.lower() == 'true'
            elif field_str in ('tracker_seed', 'tracker_leech'):
                try:
                    result[field_str] = int(value_str) if value_str and value_str != 'N/A' else 0
                except (ValueError, TypeError):
                    result[field_str] = 0
            else:
                result[field_str] = value_str if value_str and value_str != 'N/A' else None

        if result:
            return result
    except Exception:
        pass

    return None

def save_cross_data_to_redis(info_hash: str, data: Dict[str, Any]) -> None:
    if not info_hash or len(info_hash) != 40:
        return

    if not data:
        return

    try:
        from cache.store import get_redis_client
        from cache.store import torrent_cross_data_key

        redis = get_redis_client()
        if not redis:
            return

        info_hash_lower = info_hash.lower()
        key = torrent_cross_data_key(info_hash_lower)

        to_save = {}
        for field, value in data.items():
            if value is None:
                continue

            if field in ('tracker_seed', 'tracker_leech'):
                if value != '' and value != 'N/A':
                    if isinstance(value, int):
                        to_save[field] = str(value)
                    elif isinstance(value, str) and value.strip().isdigit():
                        to_save[field] = value.strip()
            else:
                if isinstance(value, bool):
                    to_save[field] = 'true' if value else 'false'
                elif isinstance(value, int):
                    to_save[field] = str(value)
                else:
                    value_str = str(value).strip()
                    if value_str and value_str != 'N/A' and len(value_str) >= 1:
                        to_save[field] = value_str

        if not to_save:
            return

        redis.hset(key, mapping=to_save)

        from app.config import Config
        has_tracker_data = 'tracker_seed' in to_save or 'tracker_leech' in to_save

        current_ttl = redis.ttl(key)

        if has_tracker_data:
            if current_ttl == -1 or current_ttl > Config.CROSS_DATA_TTL_WITH_TRACKER:
                redis.expire(key, Config.CROSS_DATA_TTL_WITH_TRACKER)
        else:
            if current_ttl == -1 or current_ttl < Config.CROSS_DATA_TTL_DEFAULT:
                redis.expire(key, Config.CROSS_DATA_TTL_DEFAULT)
    except Exception:
        pass

def get_release_title_from_redis(info_hash: str) -> Optional[str]:
    from app.config import Config
    if not info_hash or len(info_hash) != Config.INFO_HASH_LENGTH:
        return None

    try:
        from cache.store import get_redis_client
        from cache.store import release_title_key

        redis = get_redis_client()
        if not redis:
            return None

        key = release_title_key(info_hash)
        cached = redis.get(key)
        if cached:
            release_title = cached.decode('utf-8').strip()
            if release_title and len(release_title) >= 3:
                return release_title
    except Exception:
        pass

    return None

def save_release_title_to_redis(info_hash: str, release_title: str) -> None:
    if not info_hash or len(info_hash) != 40:
        return

    if not release_title or len(release_title.strip()) < 3:
        return

    try:
        from cache.store import get_redis_client
        from cache.store import release_title_key

        redis = get_redis_client()
        if not redis:
            return

        key = release_title_key(info_hash)
        from app.config import Config
        redis.setex(key, Config.RELEASE_TITLE_CACHE_TTL, release_title.strip())
    except Exception:
        pass

_RELEASE_SOURCE_MARKERS = (
    'web-dl', 'webrip', 'bluray', 'bdrip', 'brrip', 'dvdrip', 'hdrip', 'hdtv',
)
_RESOLUTION_CODEC_MARKERS = (
    '1080p', '720p', '480p', '2160p', '4k', 'uhd', 'fhd', 'fullhd',
    'x264', 'x265', 'hevc', 'h.264', 'h.265', 'h264', 'h265', 'avc',
)

def is_release_title_incomplete(title: str) -> bool:
    if not title or len(title.strip()) < 3:
        return True
    lower = title.lower()
    has_source = any(m in lower for m in _RELEASE_SOURCE_MARKERS)
    has_quality = any(m in lower for m in _RESOLUTION_CODEC_MARKERS)
    if has_source and not has_quality:
        return True
    return False

def _is_metadata_more_complete(metadata_name: str, cross_magnet_processed: str) -> bool:
    if not metadata_name or not cross_magnet_processed:
        return False

    metadata_lower = metadata_name.lower()
    cross_lower = cross_magnet_processed.lower()

    technical_indicators = [
        's01e', 's02e', 's03e', 's04e', 's05e',
        '1080p', '720p', '480p', '2160p', '4k',
        'x264', 'x265', 'hevc', 'h.264', 'h.265',
        'web-dl', 'webrip', 'bluray', 'bdrip',
        'dual', 'dublado', 'legendado'
    ]

    metadata_count = sum(1 for indicator in technical_indicators if indicator in metadata_lower)
    cross_count = sum(1 for indicator in technical_indicators if indicator in cross_lower)

    if metadata_count > cross_count:
        return True

    if metadata_count == cross_count and len(metadata_name) > len(cross_magnet_processed):
        return True

    return False

def _looks_like_bludv_processed_release_name(name: str) -> bool:
    if not name:
        return False
    stripped = name.strip()
    if not re.match(r'^-S\d{1,2}E\d{1,2}-', stripped, re.IGNORECASE):
        return False
    return stripped.count('.') >= 3

def magnet_original_needs_raw_name(name: str, magnet_processed: str = '') -> bool:
    stripped = (name or '').strip()
    if not stripped or len(stripped) < 3:
        return True
    if _looks_like_bludv_processed_release_name(stripped):
        return True
    processed = (magnet_processed or '').strip()
    if processed and stripped.lower() == processed.lower():
        return True
    return False

def resolve_magnet_original_for_torrent(torrent: Dict, fetch_remote: bool = True) -> bool:
    info_hash = str(torrent.get('info_hash') or '').strip().lower()
    current = (torrent.get('magnet_original') or '').strip()
    processed = (torrent.get('magnet_processed') or '').strip()

    metadata = torrent.get('_metadata') or {}
    meta_name = (metadata.get('name') or '').strip()
    if meta_name and not magnet_original_needs_raw_name(meta_name, processed):
        torrent['magnet_original'] = meta_name
        return True

    if current and not magnet_original_needs_raw_name(current, processed):
        return False

    if info_hash and len(info_hash) == 40:
        raw = get_raw_torrent_name(info_hash, skip_metadata=not fetch_remote)
        if raw:
            torrent['magnet_original'] = raw
            return True

    return False

def can_skip_metadata_fetch(torrent: Dict, cross_data: Optional[Dict]) -> bool:
    if not cross_data:
        return False
    if not cross_data.get('magnet_processed') or not cross_data.get('size'):
        return False
    meta_name = (cross_data.get('metadata_name') or '').strip()
    if meta_name and not magnet_original_needs_raw_name(meta_name):
        return True
    mo = (torrent.get('magnet_original') or cross_data.get('magnet_original') or '').strip()
    mp = (torrent.get('magnet_processed') or cross_data.get('magnet_processed') or '').strip()
    return bool(mo) and not magnet_original_needs_raw_name(mo, mp)

def get_raw_torrent_name(info_hash: str, skip_metadata: bool = False) -> Optional[str]:
    if skip_metadata or not info_hash or len(info_hash) != 40:
        return None

    try:
        cross_data = get_cross_data_from_redis(info_hash)
        if cross_data:
            for key in ('metadata_name', 'magnet_original'):
                value = cross_data.get(key)
                if not value:
                    continue
                name = str(value).strip()
                if not name or name == 'N/A' or len(name) < 3:
                    continue
                if _looks_like_bludv_processed_release_name(name):
                    continue
                return name
    except Exception:
        pass

    try:
        from cache.store import MetadataCache
        cached = MetadataCache().get(info_hash.lower())
        if cached and cached.get('name'):
            name = str(cached['name']).strip()
            if name and len(name) >= 3 and not _looks_like_bludv_processed_release_name(name):
                return name
    except Exception:
        pass

    try:
        from magnet.metadata import fetch_metadata_from_itorrents
        metadata = fetch_metadata_from_itorrents(info_hash)
        if metadata and metadata.get('name'):
            name = str(metadata['name']).strip()
            if name and len(name) >= 3:
                try:
                    save_cross_data_to_redis(info_hash, {'metadata_name': name, 'magnet_original': name})
                except Exception:
                    pass
                return name
    except Exception:
        pass

    return None

def get_metadata_name(info_hash: str, skip_metadata: bool = False) -> Optional[str]:
    if skip_metadata:
        return None

    try:
        release_title = get_release_title_from_redis(info_hash)
        if release_title and len(release_title.strip()) >= 3:
            return release_title.strip()
    except Exception:
        pass

    cross_data_magnet_processed = None
    try:
        cross_data = get_cross_data_from_redis(info_hash)
        if cross_data:
            if cross_data.get('metadata_name'):
                metadata_name = str(cross_data.get('metadata_name')).strip()
                if metadata_name and metadata_name != 'N/A' and len(metadata_name) >= 3:
                    return metadata_name

            if cross_data.get('magnet_processed'):
                candidate = str(cross_data.get('magnet_processed')).strip()
                if candidate and candidate != 'N/A' and len(candidate) >= 3:
                    cross_data_magnet_processed = candidate
    except Exception:
        pass

    try:
        from cache.store import MetadataCache
        metadata_cache = MetadataCache()
        cached_metadata = metadata_cache.get(info_hash.lower())
        if cached_metadata and cached_metadata.get('name'):
            metadata_name = cached_metadata.get('name', '').strip()
            if metadata_name and len(metadata_name) >= 3:
                if cross_data_magnet_processed:
                    if _is_metadata_more_complete(metadata_name, cross_data_magnet_processed):
                        try:

                            normalized_metadata = _normalize_metadata_name(metadata_name)

                            save_cross_data_to_redis(info_hash, {'metadata_name': metadata_name, 'magnet_processed': normalized_metadata})
                        except Exception:
                            pass
                        return metadata_name
                    else:
                        return cross_data_magnet_processed
                else:
                    try:

                        normalized_metadata = _normalize_metadata_name(metadata_name)

                        save_cross_data_to_redis(info_hash, {'metadata_name': metadata_name, 'magnet_processed': normalized_metadata})
                    except Exception:
                        pass
                    return metadata_name
    except Exception:
        pass

    if cross_data_magnet_processed:
        return cross_data_magnet_processed

    try:
        from magnet.metadata import fetch_metadata_from_itorrents
        metadata = fetch_metadata_from_itorrents(info_hash)
        if metadata and metadata.get('name'):
            name = metadata.get('name', '').strip()
            if name and len(name) >= 3:
                return name
    except Exception:
        pass

    return None

def upgrade_torrent_title_from_metadata(torrent: Dict, metadata: Optional[dict]) -> bool:
    if not metadata:
        return False
    metadata_name = (metadata.get('name') or '').strip()
    if not metadata_name or len(metadata_name) < 3:
        return False
    current = (
        torrent.get('title_processed')
        or torrent.get('magnet_original')
        or torrent.get('magnet_processed')
        or ''
    )
    if not _is_metadata_more_complete(metadata_name, current):
        return False

    from utils.parsing import add_audio_tag_if_needed

    year = str(torrent.get('year') or '')
    original = torrent.get('original_title') or ''
    translated = torrent.get('title_translated_processed') or ''
    magnet_original = torrent.get('magnet_original') or metadata_name
    base_for_fallback = original or translated or ''

    release = prepare_release_title(
        metadata_name,
        base_for_fallback,
        year,
        missing_dn=False,
        info_hash=torrent.get('info_hash'),
        skip_metadata=True,
    )
    standardized = create_standardized_title(
        original or translated or base_for_fallback,
        year,
        release,
        title_translated_html=translated or None,
        magnet_original=magnet_original,
    )
    torrent['title_processed'] = add_audio_tag_if_needed(
        standardized,
        release,
        info_hash=torrent.get('info_hash'),
        skip_metadata=True,
    )
    torrent['magnet_processed'] = release
    if metadata_name and magnet_original_needs_raw_name(torrent.get('magnet_original') or '', release):
        torrent['magnet_original'] = metadata_name
    elif not (torrent.get('magnet_original') or '').strip():
        torrent['magnet_original'] = metadata_name
    return True

def torrent_needs_metadata_title_upgrade(torrent: Dict) -> bool:
    if torrent.get('_metadata_fetched'):
        return False
    info_hash = torrent.get('info_hash')
    if not info_hash:
        return False
    title = (torrent.get('title_processed') or '').strip()
    magnet = (torrent.get('magnet_original') or torrent.get('magnet_processed') or '').strip()
    if not title or len(title) < 10:
        return True
    if is_release_title_incomplete(title) or is_release_title_incomplete(magnet):
        return True
    return False

_RE_YEAR = re.compile(r'\b((?:19|20)\d{2})\b')
_RE_CATALOG_DATE_SUFFIX = re.compile(
    r'-(?:\d{1,2}-\d{1,2}-(?:19|20)\d{2}|(?:19|20)\d{2}-\d{1,2}-\d{1,2})$'
)
_RE_QUERY_TEMPORADA = re.compile(
    r'(?i)\b(?:temporada|season)\s*(\d{1,2})\b'
)
_RE_QUERY_SXX = re.compile(r'(?i)\bs(\d{1,2})(?:e\d{1,2})?\b')
_RE_TITLE_TEMPORADA = re.compile(
    r'(?i)\b(\d{1,2})\s*[ªºa]?\s*temporada\b'
    r'|\btemporada\s*(\d{1,2})\b'
    r'|\bseason\s*(\d{1,2})\b'
)
_RE_TITLE_SXX = re.compile(r'(?i)\bs(\d{1,2})(?:e\d{1,2}|[\W_]|$)')
_RE_SLUG_TEMPORADA = re.compile(
    r'(?i)(?:^|[-_/])(\d{1,2})a?-?temporada(?:[-_/]|$)'
    r'|(?:^|[-_/])temporada-?(\d{1,2})(?:[-_/]|$)'
    r'|(?:^|[-_/])s(\d{1,2})(?:e\d{1,2})?(?:[-_/]|$)'
)
_SEASON_KEEP_WORDS = frozenset({'temporada', 'season'})


def strip_stop_words_keep_season(query: str) -> str:
    if not query or not str(query).strip():
        return ''
    words = []
    for w in str(query).split():
        low = w.lower()
        if low in _SEASON_KEEP_WORDS or low not in STOP_WORDS:
            words.append(w)
    return ' '.join(words)

def extract_query_year(query: str) -> Optional[str]:
    if not query or not query.strip():
        return None
    for word in query.lower().split():
        clean = re.sub(r'[^\w]', '', word, flags=re.UNICODE)
        if clean.isdigit() and len(clean) == 4 and clean.startswith(('19', '20')):
            return clean
    return None


def extract_query_season(query: str) -> Optional[int]:
    if not query or not str(query).strip():
        return None
    q = str(query).strip()

    m = _RE_QUERY_TEMPORADA.search(q)
    if m:
        try:
            season = int(m.group(1))
            if 1 <= season <= 99:
                return season
        except (TypeError, ValueError):
            pass

    m = _RE_QUERY_SXX.search(q)
    if m:
        try:
            season = int(m.group(1))
            if 1 <= season <= 99:
                return season
        except (TypeError, ValueError):
            pass

    words = q.lower().split()
    trailing = []
    for word in reversed(words):
        clean = re.sub(r'[^\w]', '', word, flags=re.UNICODE)
        if not clean:
            continue
        if clean.isdigit() and len(clean) <= 2:
            trailing.append(clean)
            continue
        break
    if len(trailing) == 1:
        has_season_hint = any(
            re.sub(r'[^\w]', '', w, flags=re.UNICODE).lower() in _SEASON_KEEP_WORDS
            for w in words
        )
        if has_season_hint:
            try:
                season = int(trailing[0])
                if 1 <= season <= 99:
                    return season
            except (TypeError, ValueError):
                pass
    return None


def title_has_season(text: str, season: int) -> bool:
    if not text or season is None:
        return False
    normalized = remove_accents(str(text).lower().replace('.', ' '))
    normalized = re.sub(r'\s+', ' ', normalized)

    for m in _RE_TITLE_TEMPORADA.finditer(normalized):
        for g in m.groups():
            if g is None:
                continue
            try:
                if int(g) == season:
                    return True
            except (TypeError, ValueError):
                continue

    padded = f'{int(season):02d}'
    bare = str(int(season))
    for m in _RE_TITLE_SXX.finditer(normalized):
        try:
            if int(m.group(1)) == season:
                return True
        except (TypeError, ValueError):
            continue

    if re.search(rf'(?i)(?<![0-9a-z])s{re.escape(padded)}(?![0-9a-z])', normalized):
        return True
    if re.search(rf'(?i)(?<![0-9a-z])s{re.escape(bare)}(?![0-9a-z])', normalized):
        return True
    return False


def extract_years_from_text(text: str) -> set[str]:
    if not text:
        return set()
    return set(_RE_YEAR.findall(text))


def _url_slug(url: str) -> str:
    if not url:
        return ''
    path = urlparse(url).path if '://' in url else url
    slug = path.rstrip('/').split('/')[-1].split('?')[0]
    return slug


def _normalize_url_slug_for_year(url: str) -> str:
    return _RE_CATALOG_DATE_SUFFIX.sub('', _url_slug(url))


def slug_has_season(url: str, season: int) -> Optional[bool]:
    if not url or season is None:
        return None
    slug = remove_accents(_normalize_url_slug_for_year(url).lower())
    found: Set[int] = set()
    for m in _RE_SLUG_TEMPORADA.finditer(slug):
        for g in m.groups():
            if g is None:
                continue
            try:
                found.add(int(g))
            except (TypeError, ValueError):
                continue
    if not found:
        return None
    return season in found


def filter_urls_by_query_season(query: str, urls: List[str]) -> List[str]:
    season = extract_query_season(query)
    if season is None or not urls:
        return urls
    filtered: List[str] = []
    for url in urls:
        verdict = slug_has_season(url, season)
        if verdict is False:
            continue
        filtered.append(url)
    return filtered

def slug_year_matches_query_year(
    slug_year: str,
    query_year: str,
    tolerance: int = 1,
) -> bool:
    try:
        return abs(int(slug_year) - int(query_year)) <= tolerance
    except (TypeError, ValueError):
        return False

def filter_urls_by_query_year(
    query: str,
    urls: List[str],
    tolerance: int = 1,
) -> List[str]:
    query_year = extract_query_year(query)
    if not query_year:
        return urls
    filtered = []
    for url in urls:
        slug = _normalize_url_slug_for_year(url)
        years = extract_years_from_text(slug)
        if not years:
            filtered.append(url)
            continue
        if any(slug_year_matches_query_year(y, query_year, tolerance) for y in years):
            filtered.append(url)
    return filtered

def _query_word_spans_title_words(title_normalized: str, query_word: str) -> bool:
    query_compact = re.sub(r'[^a-z0-9]', '', remove_accents(query_word.lower()))
    if len(query_compact) < 4:
        return False
    words = re.findall(r'[a-z0-9]+', title_normalized)
    for start in range(len(words)):
        joined = ''
        for word in words[start:start + 4]:
            joined += word
            if joined == query_compact:
                return True
            if len(joined) > len(query_compact):
                break
    return False

def check_query_match(query: str, title: str, title_original_html: str = '', title_translated_html: str = '') -> bool:
    query = str(query) if query is not None else ''
    title = str(title) if title is not None else ''
    title_original_html = str(title_original_html) if title_original_html is not None else ''
    title_translated_html = str(title_translated_html) if title_translated_html is not None else ''

    if not query or not query.strip():
        return True

    query_lower = query.lower().strip()
    query_words = query_lower.split()

    clean_query_words = []
    for word in query_words:
        clean_word = re.sub(r'[^\w]', '', word, flags=re.UNICODE)
        if len(clean_word) >= 1:
            if clean_word.isascii() and clean_word.lower() in STOP_WORDS:
                continue
            clean_query_words.append(clean_word.lower() if clean_word.isascii() else clean_word)

    if len(clean_query_words) == 0:
        return True

    non_year_words = [w for w in clean_query_words if not (w.isdigit() and len(w) == 4 and w.startswith(('19', '20')))]
    if non_year_words:
        clean_query_words = non_year_words

    first_title_word = None
    for word in clean_query_words:
        if not word.isdigit():
            first_title_word = word
            break
        elif len(word) >= 3:
            first_title_word = word
            break

    combined_title = f"{title} {title_original_html} {title_translated_html}".lower()
    combined_title = combined_title.replace('.', ' ')
    combined_title = re.sub(r'\s+', ' ', combined_title)

    combined_title = remove_accents(combined_title)

    query_season = extract_query_season(query)
    if query_season is not None and not title_has_season(combined_title, query_season):
        return False

    query_episode_match = re.search(r'(?i)s(\d{1,2})e(\d{1,2})', query)
    if query_episode_match:
        query_season = query_episode_match.group(1).zfill(2)
        query_episode_num = int(query_episode_match.group(2))

        title_season_ep_pattern = rf'(?i)s{query_season}e(\d{{1,2}})(?:[\.\-\sE]|$)'
        title_season_ep_match = re.search(title_season_ep_pattern, title)

        if not title_season_ep_match:
            return False

        episode_pattern = rf'(?i)s{query_season}e(\d{{1,2}})(?:[\.\-\sE]+(\d{{1,2}}))*'
        episode_match = re.search(episode_pattern, title)
        episodes_in_title = []

        if episode_match:
            first_ep = int(episode_match.group(1))
            episodes_in_title = [first_ep]

            match_text = episode_match.group(0)
            first_ep_str = episode_match.group(1)
            remaining_text = match_text[len(f's{query_season}e{first_ep_str}'):]
            episode_numbers = re.findall(r'(\d{1,2})', remaining_text)

            for ep_str in episode_numbers:
                try:
                    ep_num = int(ep_str)
                    if ep_num > episodes_in_title[-1]:
                        episodes_in_title.append(ep_num)
                except (ValueError, TypeError):
                    break
        else:
            return False

        if len(episodes_in_title) == 1:
            if episodes_in_title[0] != query_episode_num:
                return False
        else:
            if query_episode_num not in episodes_in_title:
                if len(episodes_in_title) >= 2:
                    start_ep = episodes_in_title[0]
                    end_ep = episodes_in_title[-1]
                    if not (start_ep <= query_episode_num <= end_ep):
                        return False
                else:
                    return False

    title_normalized = combined_title

    matches = 0
    matched_words = []
    first_title_word_matched = False

    for query_word in clean_query_words:
        query_word_normalized = remove_accents(query_word)

        pattern = r'\b' + re.escape(query_word_normalized) + r'\b'
        if re.search(pattern, title_normalized, re.IGNORECASE | re.UNICODE):
            matches += 1
            matched_words.append(query_word)
            if query_word == first_title_word:
                first_title_word_matched = True
            continue

        partial_pattern = r'\b' + re.escape(query_word_normalized) + r'(?=\w)'
        if re.search(partial_pattern, title_normalized, re.IGNORECASE | re.UNICODE):
            matches += 1
            matched_words.append(query_word)
            if query_word == first_title_word:
                first_title_word_matched = True
            continue

        if query_word_normalized.isdigit():
            season_patterns = [f"s{query_word_normalized}", f"s{query_word_normalized.zfill(2)}"]
            if any(sp in title_normalized for sp in season_patterns):
                matches += 1
                matched_words.append(query_word)

    if len(clean_query_words) > 1 and first_title_word and not first_title_word_matched:
        return False


    if len(clean_query_words) == 1:
        if matches == 1:
            return True
        return _query_word_spans_title_words(title_normalized, clean_query_words[0])
    elif len(clean_query_words) == 2:
        return matches == 2
    else:
        has_title_match = False
        for word in matched_words:
            if not word.isdigit():
                has_title_match = True
                break
            elif len(word) >= 3:
                has_title_match = True
                break

        total_words = len(clean_query_words)
        if total_words >= 5:
            first_words_to_check = clean_query_words[:min(4, total_words)]
            first_words_matches = sum(1 for w in first_words_to_check if w in matched_words)

            min_matches_percent = max(2, int(total_words * 0.3))
            if first_words_matches >= 2 or matches >= min_matches_percent:
                return has_title_match

            return False

        title_words_in_query = [w for w in clean_query_words if not w.isdigit() or len(w) >= 3]
        title_words_count = len(title_words_in_query)

        title_word_matches = sum(1 for w in matched_words if not w.isdigit() or len(w) >= 3)

        season_match_count = 0
        for word in clean_query_words:
            if word.isdigit() and len(word) <= 2:
                season_patterns = [f"s{word}", f"s{word.zfill(2)}"]
                if any(sp in title_normalized for sp in season_patterns):
                    season_match_count += 1

        total_valid_matches = title_word_matches + season_match_count

        if total_words == 3:
            if total_valid_matches < title_words_count:
                return False
            return True

        if total_words == 4:
            if total_valid_matches < 3:
                return False
            return True

        return matches >= 2 and has_title_match

def _extract_base_title_from_release(magnet_processed: str) -> str:
    clean_release = clean_title(magnet_processed)
    clean_release = remove_accents(clean_release)

    clean_release = re.sub(r'^(19|20)\d{2}\.', '', clean_release)

    tech_patterns = [
        r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip)\.',
        r'^(1080p|720p|480p|2160p|4K)\.',
        r'^(x264|x265|H\.264|H\.265)\.',
    ]
    for pattern in tech_patterns:
        clean_release = re.sub(pattern, '', clean_release, flags=re.IGNORECASE)

    if '.' in clean_release:
        clean_release = re.sub(r'\s*\.\s*', '.', clean_release)
        clean_release = re.sub(r'\s+', '.', clean_release)
    else:
        clean_release = re.sub(r'\s+', '.', clean_release)

    clean_release = re.sub(r'\.{2,}', '.', clean_release)

    clean_release = re.sub(r'([A-Za-z0-9]+)(?<!\.)(S\d{1,2}(?:E\d{1,2})?)', r'\1.\2', clean_release, flags=re.IGNORECASE)

    parts = clean_release.split('.')
    base_parts = []
    for part in parts:
        if re.match(r'^S\d{1,2}(?:E\d{1,2})?$', part, re.IGNORECASE):
            break
        if re.match(r'^(19|20)\d{2}$', part):
            break
        if re.match(r'^(WEB-DL|WEBRip|BluRay|1080p|720p|2160p|FULLHD|x264|x265|DUAL|DUBLADO|HDR)', part, re.IGNORECASE):
            break
        if part.lower() in CONTAINER_EXTENSIONS:
            continue
        if part and len(part) > 1:
            base_parts.append(part)

    base_title = '.'.join(base_parts)
    base_title = base_title.replace('-', '.').replace('/', '.')
    base_title = re.sub(r'[^\w\.]', '', base_title)
    base_title = base_title.strip('.')
    base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))

    return base_title

def _split_technical_components(text: str) -> str:
    if not text:
        return text

    if re.search(r'S\d{1,2}(?:E\d{1,2})?', text, re.IGNORECASE):
        if (re.search(r'\.S\d{1,2}E\d{1,2}\.', text, re.IGNORECASE) or
            re.search(r'\.S\d{1,2}(?![E\d])\.', text, re.IGNORECASE) or
            re.search(r'\.\d{3,4}p\.', text, re.IGNORECASE)):
            if not re.search(r'(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)(1080p|720p|2160p|480p|4K|UHD|FHD|FULLHD|HD|SD|HDR|x264|x265|H\.264|H\.265|AVC|HEVC)', text, re.IGNORECASE):
                return text

    if '.' in text:
        parts = text.split('.')
        if len(parts) >= 3:
            has_colados = any(
                (re.search(r'(WEB-DL|WEBRip|1080p|720p|x264|x265|LEGENDADO|DUAL)', part, re.IGNORECASE)
                 and len(part) > 10)
                or '-' in part
                for part in parts
            )
            if not has_colados:
                return text

    result = text

    year_placeholders = {}
    season_placeholders = {}
    dual_audio_placeholders = {}
    year_counter = 0
    season_counter = 0
    dual_audio_counter = 0

    def replace_year(match):
        nonlocal year_counter
        year = match.group(0)
        placeholder = f'__YEAR_{year_counter}__'
        year_placeholders[placeholder] = year
        year_counter += 1
        return placeholder

    def replace_season(match):
        nonlocal season_counter
        season = match.group(0)
        placeholder = f'__SEASON_{season_counter}__'
        season_placeholders[placeholder] = season
        season_counter += 1
        return placeholder

    def replace_dual_audio(match):
        nonlocal dual_audio_counter
        dual_audio = match.group(0)
        placeholder = f'__DUAL_AUDIO_{dual_audio_counter}__'
        dual_audio_placeholders[placeholder] = dual_audio
        dual_audio_counter += 1
        return placeholder

    result = re.sub(r'\bDUAL\.(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?\b', replace_dual_audio, result, flags=re.IGNORECASE)

    result = re.sub(r'\bS(\d{1,2})(?![E\d])\b', replace_season, result, flags=re.IGNORECASE)

    result = re.sub(r'\b(19|20)\d{2}\b', replace_year, result)

    result = re.sub(r'\bH(264|265)\b', r'H.\1', result, flags=re.IGNORECASE)

    result = re.sub(r'(?<!\.)(x264|x265|H\.264|H\.265|AVC|HEVC)(?=-)', r'\1.', result, flags=re.IGNORECASE)

    patterns = [
        (r'(?<!\.)(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|DVDScr)(?![A-Za-z])', r'.\1.', re.IGNORECASE),
        (r'(?<![A-Za-z\.])(CAMRip|CAM|TSRip|TS|TC|R5|SCR)(?![A-Za-z])', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(?<!E)(2160p|1080p|720p|480p|4K|UHD|FHD|FULLHD)(?![A-Za-z0-9])', r'.\1.', re.IGNORECASE),
        (r'(?<![A-Za-z])(HD|SD|HDR)(?![A-Za-z])', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)(?![A-Za-z0-9])', r'.\1.', re.IGNORECASE),

        (r'(?<!\.)(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado|DTS-HD|TrueHD)(?![A-Za-z])', r'.\1.', re.IGNORECASE),
        (r'(?<!\.)(AAC|AC3|DTS|DDP)\d+\.\d+(?!\.)', r'.\1.', re.IGNORECASE),

        (r'(?<!\.)(\d+\.\d+)(?!\.)(?!\d)', r'.\1.', re.IGNORECASE),
    ]

    for pattern, replacement, flags in patterns:
        result = re.sub(pattern, replacement, result, flags=flags)

    for placeholder, dual_audio in dual_audio_placeholders.items():
        result = result.replace(placeholder, dual_audio)

    for placeholder, season in season_placeholders.items():
        result = result.replace(placeholder, season)

    for placeholder, year in year_placeholders.items():
        result = result.replace(placeholder, year)

    result = re.sub(r'(?<!\.)(S\d{1,2})(?![E\d])(?!\.)', r'.\1.', result, flags=re.IGNORECASE)

    result = re.sub(r'(?<!\.)((19|20)\d{2})(?!\.)', r'.\1.', result)

    result = re.sub(r'\.{2,}', '.', result)
    result = result.strip('.')

    return result

def _extract_technical_info(text: str) -> str:
    if not text:
        return ''

    text = re.sub(r'\s+', '.', text)

    text = re.sub(r'(WEB-DL|DTS-HD)', lambda m: m.group(1).replace('-', '___HYPHEN___'), text, flags=re.IGNORECASE)

    text = text.replace('-', '.')

    text = text.replace('___HYPHEN___', '-')

    text = re.sub(r'\.{2,}', '.', text)
    text = text.strip('.')

    if not text:
        return ''

    text = _split_technical_components(text)

    technical_parts = []
    parts = text.split('.')

    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue

        if re.match(r'^S\d{1,2}$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(19|20)\d{2}$', part_clean):
            technical_parts.append(part_clean)
        elif re.match(r'^(1080p|720p|480p|2160p|4K|HD|FHD|UHD|SD|HDR|FULLHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(x264|x265|H\.264|H\.265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(AAC|AC3|DTS|DDP)\d+\.\d+$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^\d+\.\d+-[A-Z0-9]+$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)
        elif re.match(r'^-[A-Z0-9]+$', part_clean):
            technical_parts.append(part_clean)
        elif re.match(r'^\d+\.?\d*\s*(GB|MB)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

    return '.'.join(technical_parts)

def _clean_remaining(processed_magnet_text: str) -> str:
    if not processed_magnet_text:
        return ''

    processed_magnet_text = processed_magnet_text.strip('.')
    if not processed_magnet_text:
        return ''

    processed_magnet_text = re.sub(r'\.{2,}', '.', processed_magnet_text)

    if processed_magnet_text and not processed_magnet_text.startswith('.'):
        processed_magnet_text = '.' + processed_magnet_text

    return processed_magnet_text

def _ensure_default_format(title: str) -> str:
    if not title:
        return title
    normalized = title.lower()
    if re.search(r'(web[-\.\s]?dl|webrip|bluray|bdrip|hdrip|hdtv|dvdrip|2160p|1080p|720p|480p|4k|camrip|cam|tsrip|ts|uhd|fullhd|hdr)', normalized, re.IGNORECASE):
        return title
    if title.endswith('.'):
        return f"{title}WEB-DL"
    return f"{title}.WEB-DL"

def _apply_season_temporada_tags(title: str, magnet_processed: str, original_title_html: str, year: str) -> str:
    if not title:
        return title

    context_parts = []
    if magnet_processed:
        context_parts.append(magnet_processed)
    if original_title_html:
        context_parts.append(original_title_html)
    if not context_parts:
        return title

    release_clean = remove_accents(' '.join(context_parts).lower())
    release_clean = release_clean.replace('ª', 'a').replace('º', 'o')

    if 'temporada' not in release_clean:
        return title

    has_completo = 'completo' in release_clean or 'completa' in release_clean

    result = title
    season_match = re.search(r'(\d+)\s*(?:a)?\s*temporada', release_clean)
    if not season_match:
        season_match = re.search(r'temporada\s*(?:-|:)?\s*(\d+)', release_clean)
    year_str = str(year) if year else ''
    year_in_title = year_str and year_str in result
    if season_match:
        season_number_raw = season_match.group(1)
        try:
            season_num = int(season_number_raw)
            if season_num <= 0:
                if not year_in_title and year_str:
                    result = f"{result}.{year_str}"
                return result
        except (ValueError, TypeError):
            if not year_in_title and year_str:
                result = f"{result}.{year_str}"
            return result

        season_number = season_number_raw.zfill(2)
        has_season_info = re.search(rf'S0*{season_number_raw}(?:E\d+(?:-\d+)?|$)', result, re.IGNORECASE)
        has_any_season_ep = re.search(r'S\d{1,2}E\d{1,2}', result, re.IGNORECASE)

        if has_completo and has_any_season_ep:
            result = re.sub(rf'S{season_number}E\d+', f'S{season_number}', result, flags=re.IGNORECASE)
            has_any_season_ep = False

        if not has_season_info and not has_any_season_ep:
            if year_in_title:
                result = result.replace(f".{year_str}", '')
                result = f"{result}.S{season_number}.{year_str}"
            else:
                result = f"{result}.S{season_number}"
        elif not year_in_title and year_str:
            result = f"{result}.{year_str}"

        result = re.sub(r'\.?\b\d+\s*(?:a)?\s*temporada\s*complet[ao]?\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?\b\d+\s*(?:a)?\s*temporada\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?temporada\s*complet[ao]?\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?temporada\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.?complet[ao]\b', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\.{2,}', '.', result)
        result = result.strip('.')
    elif year_str and year_str not in result:
        result = f"{result}.{year_str}"

    return result

def _reorder_title_components(title: str) -> str:
    if not title:
        return title

    title = _split_technical_components(title)

    parts = [part for part in title.split('.') if part]
    if not parts:
        return title

    season_episode = None
    season_only = None
    year = None
    base_parts: List[str] = []
    quality_parts: List[str] = []
    source_parts: List[str] = []
    codec_parts: List[str] = []
    audio_parts: List[str] = []
    other_parts: List[str] = []
    structure_started = False

    quality_tokens = {
        '1080P', '720P', '480P', '2160P', '4K', 'HD', 'FHD', 'UHD', 'SD', 'HDR', 'FULLHD'
    }
    source_tokens = {
        'WEB-DL', 'WEBRIP', 'BLURAY', 'DVDRIP', 'HDRIP', 'HDTV', 'BDRIP',
        'BRRIP', 'CAMRIP', 'CAM', 'TSRIP', 'TS', 'TC', 'R5', 'SCR', 'DVDSCR'
    }
    codec_tokens = {
        'X264', 'X265', 'H.264', 'H.265', 'H264', 'H265', 'AVC', 'HEVC'
    }
    audio_tokens = {
        'DUAL', 'DUBLADO', 'DDP5.1', 'ATMOS', 'AC3', 'AAC', 'MP3', 'FLAC', 'DTS', 'NACIONAL', 'LEGENDADO'
    }

    combined_parts = []
    i = 0
    while i < len(parts):
        part = parts[i]
        clean_part = part.strip()

        if i + 1 < len(parts) and re.match(r'^DUAL$', clean_part, re.IGNORECASE):
            next_part = parts[i + 1].strip()
            if re.match(r'^(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?$', next_part, re.IGNORECASE):
                combined_parts.append(f"{clean_part}.{next_part}")
                i += 2
                continue

        combined_parts.append(part)
        i += 1

    parts = combined_parts

    for part in parts:
        clean_part = part.strip()
        if not clean_part:
            continue

        match_episode_multi = re.match(r'^S(\d{1,2})E(\d{1,2})(?:[\.\-E](\d{1,2}))+$', clean_part, re.IGNORECASE)
        if match_episode_multi:
            season = match_episode_multi.group(1).zfill(2)
            episode1 = int(match_episode_multi.group(2))
            episodes = [episode1]

            episode_numbers = re.findall(r'[\.\-E](\d{1,2})', clean_part)
            for ep_str in episode_numbers:
                try:
                    ep_num = int(ep_str)
                    from app.config import Config
                    if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                        episodes.append(ep_num)
                    else:
                        break
                except (ValueError, TypeError):
                    break

            if len(episodes) >= 2:


                if len(episodes) == 2:
                    episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                elif len(episodes) >= 5:

                    first_ep = str(episodes[0]).zfill(2)
                    last_ep = str(episodes[-1]).zfill(2)
                    season_episode = f"S{season}E{first_ep}-E{last_ep}"
                elif len(episodes) >= 3:

                    episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                else:
                    episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                    season_episode = f"S{season}E{episode_str}"
                structure_started = True
                continue

        match_episode_hyphen = re.match(r'^S(\d{1,2})E(\d{1,2})-(\d{1,2})$', clean_part, re.IGNORECASE)
        if match_episode_hyphen:
            season = match_episode_hyphen.group(1).zfill(2)
            episode1 = int(match_episode_hyphen.group(2))
            episode2 = int(match_episode_hyphen.group(3))
            if episode2 > episode1 and episode2 <= 99:
                episode_str = f"{str(episode1).zfill(2)}-{str(episode2).zfill(2)}"
                season_episode = f"S{season}E{episode_str}"
                structure_started = True
                continue

        match_episode = re.match(r'^S(\d{1,2})E(\d{1,2})$', clean_part, re.IGNORECASE)
        if match_episode:
            season_episode = f"S{match_episode.group(1).zfill(2)}E{match_episode.group(2).zfill(2)}"
            structure_started = True
            continue

        match_season = re.match(r'^S(\d{1,2})$', clean_part, re.IGNORECASE)
        if match_season:
            season_only = f"S{match_season.group(1).zfill(2)}"
            structure_started = True
            continue

        if re.match(r'^(19|20)\d{2}$', clean_part):
            if not year:
                year = clean_part
            structure_started = True
            continue

        upper_part = clean_part.upper()

        if upper_part in quality_tokens:
            normalized_quality = clean_part.lower()
            if normalized_quality not in [q.lower() for q in quality_parts]:
                quality_parts.append(clean_part)
            structure_started = True
            continue
        elif upper_part in source_tokens:
            normalized_source = 'WEB-DL' if upper_part == 'WEB-DL' else clean_part
            if normalized_source not in source_parts:
                source_parts.append(normalized_source)
            structure_started = True
            continue
        elif upper_part in codec_tokens or re.match(r'^(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)$', clean_part, re.IGNORECASE):
            if re.match(r'^H(264|265)$', clean_part, re.IGNORECASE):
                clean_part = f'H.{clean_part[1:]}'
            normalized_codec = clean_part.lower()
            if normalized_codec not in [c.lower() for c in codec_parts]:
                codec_parts.append(clean_part)
            structure_started = True
            continue
        elif upper_part in audio_tokens or re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', clean_part, re.IGNORECASE):

            normalized_audio = clean_part.upper()
            if normalized_audio not in [a.upper() for a in audio_parts]:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^DUAL\.(5\.1|2\.0|7\.1)(?:-[A-Z0-9]+)?$', clean_part, re.IGNORECASE):
            if clean_part not in audio_parts:
                audio_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', clean_part, re.IGNORECASE):
            if clean_part not in other_parts:
                other_parts.append(clean_part)
            structure_started = True
            continue
        elif re.match(r'^\d+\.?\d*(GB|MB)$', clean_part, re.IGNORECASE):
            structure_started = True
            continue
        elif clean_part.lower() in CONTAINER_EXTENSIONS:
            continue

        if re.match(r'^-[A-Z0-9]+$', clean_part, re.IGNORECASE) or (re.match(r'^[A-Z0-9]+$', clean_part, re.IGNORECASE) and structure_started):
            if clean_part not in other_parts:
                other_parts.append(clean_part)
            structure_started = True
            continue

        if structure_started:
            if clean_part not in other_parts:
                other_parts.append(clean_part)
        else:
            base_parts.append(clean_part)

    if not base_parts and parts:
        base_parts.append(parts[0])

    ordered_parts = []
    ordered_parts.extend(base_parts)

    if season_episode:
        ordered_parts.append(season_episode)
    elif season_only:
        ordered_parts.append(season_only)

    if year:
        ordered_parts.append(year)

    ordered_parts.extend(source_parts)
    ordered_parts.extend(quality_parts)
    ordered_parts.extend(codec_parts)
    ordered_parts.extend(audio_parts)

    dedup_other = []
    seen = set()
    for part in other_parts:
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup_other.append(part)

    ordered_parts.extend(dedup_other)

    return '.'.join(ordered_parts)

def _normalize_metadata_name(metadata_name: str) -> str:
    normalized = metadata_name.strip()
    normalized = html.unescape(normalized)
    try:
        normalized = unquote(normalized)
    except Exception:
        pass
    normalized = normalized.strip()
    normalized = clean_title(normalized)
    normalized = re.sub(r'\[[^\]]*\]', '', normalized)
    normalized = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), normalized)
    temp_normalized = re.sub(r'\s+', '.', normalized.strip())
    temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)
    parts = temp_normalized.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part
    return '.'.join(cleaned_parts).strip('.')

def prepare_release_title(
    magnet_processed: str,
    fallback_title: str,
    year: str = '',
    missing_dn: bool = False,
    info_hash: Optional[str] = None,
    skip_metadata: bool = False
) -> str:
    fallback_title = (fallback_title or '').strip()
    original_release_title = None
    final_missing_dn = missing_dn

    magnet_processed = (magnet_processed or '').strip()

    if magnet_processed and len(magnet_processed) >= 3:
        normalized = magnet_processed
        normalized = html.unescape(normalized)
        try:
            normalized = unquote(normalized)
        except Exception:
            pass
        normalized = normalized.strip()

        normalized = clean_title(normalized)

        technical_in_brackets = []

        bracket_patterns = [
            r'\[(1080p|720p|480p|2160p|4K|UHD|FHD|FULLHD|HD|SD|HDR)\]',
            r'\[(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)\]',
            r'\[(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)\]',
            r'\[(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)\]',
        ]

        for pattern in bracket_patterns:
            matches = re.finditer(pattern, normalized, re.IGNORECASE)
            for match in matches:
                technical_in_brackets.append(match.group(1))

        normalized = re.sub(r'\[[^\]]*\]', '', normalized)

        if technical_in_brackets:
            normalized = re.sub(r'\s+', '.', normalized.strip())
            if normalized:
                normalized += '.' + '.'.join(technical_in_brackets)
            else:
                normalized = '.'.join(technical_in_brackets)

        normalized = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), normalized)

        temp_normalized = re.sub(r'\s+', '.', normalized.strip())
        temp_normalized = re.sub(r'\.{2,}', '.', temp_normalized)

        parts = temp_normalized.split('.')
        combined_parts = []
        for part in parts:
            clean_part = part.strip()
            if clean_part:
                combined_parts.append(clean_part)

        cleaned_parts = []
        prev_part = None
        for part in combined_parts:
            part = part.strip()
            if not part:
                continue
            part_lower = part.lower()
            prev_lower = prev_part.lower() if prev_part else None
            if part_lower != prev_lower:
                cleaned_parts.append(part)
                prev_part = part

        original_release_title = '.'.join(cleaned_parts).strip('.')
        if info_hash and not skip_metadata:
            if is_release_title_incomplete(original_release_title):
                metadata_name = get_metadata_name(info_hash, skip_metadata=skip_metadata)
                if metadata_name and _is_metadata_more_complete(
                    metadata_name, original_release_title
                ):
                    original_release_title = _normalize_metadata_name(metadata_name)
        final_missing_dn = False
    else:
        if missing_dn:

            if info_hash:
                if not skip_metadata:
                    metadata_name = get_metadata_name(info_hash, skip_metadata=skip_metadata)
                    if metadata_name and len(metadata_name.strip()) >= 3:
                        original_release_title = _normalize_metadata_name(metadata_name)
                        final_missing_dn = False
                    else:
                        original_release_title = fallback_title
                        final_missing_dn = True
                else:
                    original_release_title = fallback_title
                    final_missing_dn = True
            else:
                original_release_title = fallback_title
                final_missing_dn = True
        else:

            original_release_title = fallback_title
            final_missing_dn = False

    if not original_release_title or len(original_release_title.strip()) < 3:
        original_release_title = fallback_title
        final_missing_dn = True

    if '.' in original_release_title:
        original_release_title = re.sub(r'\s+', ' ', original_release_title)
        original_release_title = re.sub(r'\s*\.\s*', '.', original_release_title)
    else:
        original_release_title = re.sub(r'\s+', ' ', original_release_title).strip()

    if year:
        year_str = str(year)
        if year_str and year_str not in original_release_title:
            if '.' in original_release_title:
                original_release_title = f"{original_release_title}.{year_str}".strip()
            else:
                original_release_title = f"{original_release_title} {year_str}".strip()
        else:
            pass

    if final_missing_dn and original_release_title:
        lower_title = original_release_title.lower()
        already_web_dl = 'web-dl' in lower_title or 'webrip' in lower_title
        has_other_source = re.search(
            r'(?:^|[^a-z])(camrip|cam|tsrip|ts|tc|r5|scr|dvdscr|dvdrip|hdrip|bdrip|brrip|bluray|hdtv)(?:[^a-z]|$)',
            lower_title,
        ) is not None
        if not already_web_dl and not has_other_source:
            if '.' in original_release_title:
                original_release_title = f"{original_release_title}.WEB-DL".strip()
            else:
                original_release_title = f"{original_release_title} WEB-DL".strip()
        elif already_web_dl and has_other_source:
            original_release_title = re.sub(r'(?i)\.?WEB-?DL\.?', '.', original_release_title)
            original_release_title = re.sub(r'(?i)\.?WEBRip\.?', '.', original_release_title)
            original_release_title = re.sub(r'\.{2,}', '.', original_release_title).strip(' .')

    result = original_release_title.strip()
    return result

def create_standardized_title(title_original_html: str, year: str, magnet_processed: str, title_translated_html: Optional[str] = None, magnet_original: Optional[str] = None) -> str:

    def finalize_title(value: str) -> str:
        release_for_season_detection = magnet_original if magnet_original else magnet_processed
        value = _apply_season_temporada_tags(value, release_for_season_detection, title_original_html, year)
        value = _reorder_title_components(value)
        return _ensure_default_format(value)
    base_title = ''

    if title_original_html and title_original_html.strip():
        has_non_latin = bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]', title_original_html))

        if not has_non_latin:
            base_title = clean_title(title_original_html)
            base_title = remove_accents(base_title)
            base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)
            base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)
            base_title = base_title.replace(' ', '.').replace('-', '.').replace('/', '.')
            base_title = re.sub(r'[^\w\.]', '', base_title)
            base_title = base_title.strip('.')
            base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))

        else:
            if title_translated_html and title_translated_html.strip():
                base_title = clean_title(title_translated_html)
                base_title = remove_accents(base_title)
                base_title = re.sub(r'(?i)\s*\(?\s*S\d{1,2}(E\d{1,2})?.*$', '', base_title)
                base_title = re.sub(r'(?i)\s*\(?\s*(19|20)\d{2}\s*\)?\s*$', '', base_title)
                base_title = base_title.replace(' ', '.').replace('-', '.').replace('/', '.')
                base_title = re.sub(r'[^\w\.]', '', base_title)
                base_title = base_title.strip('.')
                base_title = '.'.join(word.capitalize() if word else '' for word in base_title.split('.'))
            else:
                base_title = _extract_base_title_from_release(magnet_processed)
    else:
        base_title = _extract_base_title_from_release(magnet_processed)
        result = finalize_title(base_title)
        return result

    if magnet_original and magnet_original.strip():
        clean_release = clean_title(magnet_original)
    elif magnet_processed and magnet_processed.strip():
        clean_release = clean_title(magnet_processed)
    else:
        result = finalize_title(base_title)
        return result
    clean_release = remove_accents(clean_release)

    technical_in_brackets = []

    bracket_patterns = [
        r'\[(1080p|720p|480p|2160p|4K|UHD|FHD|FULLHD|HD|SD|HDR)\]',
        r'\[(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)\]',
        r'\[(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)\]',
        r'\[(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)\]',
    ]

    for pattern in bracket_patterns:
        matches = re.finditer(pattern, clean_release, re.IGNORECASE)
        for match in matches:
            technical_in_brackets.append(match.group(1))

    clean_release = re.sub(r'\[[^\]]*\]', '', clean_release)

    if technical_in_brackets:
        clean_release = re.sub(r'\s+', '.', clean_release.strip())
        if clean_release:
            clean_release += '.' + '.'.join(technical_in_brackets)
        else:
            clean_release = '.'.join(technical_in_brackets)

    clean_release = re.sub(r'\(([^)]+)\)', lambda m: m.group(1).replace(' ', '.'), clean_release)

    base_title_normalized = re.sub(r'[\.\s]', '', base_title).lower()
    clean_release_normalized = re.sub(r'[\.\s]', '', clean_release).lower()

    if clean_release_normalized.startswith(base_title_normalized):
        base_no_dots = base_title.replace('.', '')
        if len(base_no_dots) > 0:
            base_pattern = re.escape(base_no_dots[0])
            for char in base_no_dots[1:]:
                base_pattern += rf'\.?{re.escape(char)}'

            match = re.match(rf'^{base_pattern}(\.)', clean_release, flags=re.IGNORECASE)
            if match:
                clean_release = clean_release[match.end():]
            else:
                clean_release = re.sub(rf'^{base_pattern}(?=S\d|(?<!\d)\d)', '', clean_release, flags=re.IGNORECASE)

        clean_release = re.sub(r'^\.+', '', clean_release)

    temp_clean = re.sub(r'\s+', '.', clean_release.strip())
    temp_clean = re.sub(r'\.{2,}', '.', temp_clean)

    parts = temp_clean.split('.')
    cleaned_parts = []
    prev_part = None
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_lower = part.lower()
        prev_lower = prev_part.lower() if prev_part else None
        if part_lower != prev_lower:
            cleaned_parts.append(part)
            prev_part = part

    clean_release = '.'.join(cleaned_parts).strip('.')


    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:\s*[\.\-]\s*\d{1,2}){1,}(?![0-9])', clean_release)

    if not season_ep_multi_match:
        alt_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)
        if alt_match:
            season_ep_multi_match = alt_match

    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))

        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]

        episode_numbers = re.findall(r'[\.\-]\s*(\d{1,2})', full_match)

        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            from app.config import Config
            if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                episodes.append(ep_num)
            else:
                break

        if len(episodes) >= 2:


            if len(episodes) == 2:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:

                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:

                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"

            year_from_release = None
            text_before_season = clean_release[:season_ep_multi_match.start()]
            if text_before_season:
                year_match = re.search(r'(19|20)\d{2}', text_before_season)
                if year_match:
                    year_from_release = year_match.group(0)

            original_magnet_text = clean_release[season_ep_multi_match.end():]
            original_magnet_text = re.sub(r'\s+', '.', original_magnet_text)
            original_magnet_text = re.sub(r'\.{2,}', '.', original_magnet_text)
            original_magnet_text = original_magnet_text.strip('.')
            original_magnet_text = _split_technical_components(original_magnet_text)

            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)

            if year_from_release:
                result = finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
            else:
                result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")

            return result

    clean_release = re.sub(r'\s+', '.', clean_release)
    clean_release = re.sub(r'\.{2,}', '.', clean_release)
    clean_release = clean_release.strip('.')


    season_ep_multi_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})(?:[\.\-]\d{1,2}){1,}(?![0-9])', clean_release)

    if season_ep_multi_match:
        season = season_ep_multi_match.group(1).zfill(2)
        episode1 = int(season_ep_multi_match.group(2))

        full_match = season_ep_multi_match.group(0)
        episodes = [episode1]

        episode_numbers = re.findall(r'[\.\-](\d{1,2})', full_match)
        for ep_str in episode_numbers:
            ep_num = int(ep_str)
            from app.config import Config
            if ep_num > episodes[-1] and ep_num <= Config.MAX_EPISODE_NUMBER and (ep_num - episodes[-1]) <= Config.MAX_EPISODE_DIFF:
                episodes.append(ep_num)
            else:
                break

        if len(episodes) >= 2:


            if len(episodes) == 2:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            elif len(episodes) >= 5:

                first_ep = str(episodes[0]).zfill(2)
                last_ep = str(episodes[-1]).zfill(2)
                season_ep_str = f"S{season}E{first_ep}-E{last_ep}"
            elif len(episodes) >= 3:

                episode_str = 'E'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"
            else:
                episode_str = '-'.join(str(ep).zfill(2) for ep in episodes)
                season_ep_str = f"S{season}E{episode_str}"

            year_from_release = None
            text_before_season = clean_release[:season_ep_multi_match.start()]
            if text_before_season:
                year_match = re.search(r'(19|20)\d{2}', text_before_season)
                if year_match:
                    year_from_release = year_match.group(0)

            original_magnet_text = clean_release[season_ep_multi_match.end():]
            original_magnet_text = _split_technical_components(original_magnet_text)
            processed_magnet_text = _extract_technical_info(original_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)

            if year_from_release:
                result = finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
            else:
                result = finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")

            return result

    season_ep_match = re.search(r'(?i)S(\d{1,2})E(\d{1,2})', clean_release)

    if season_ep_match:
        season = season_ep_match.group(1).zfill(2)
        episode = season_ep_match.group(2).zfill(2)
        season_ep_str = f"S{season}E{episode}"

        year_from_release = None
        text_before_season = clean_release[:season_ep_match.start()]
        if text_before_season:
            year_match = re.search(r'(19|20)\d{2}', text_before_season)
            if year_match:
                year_from_release = year_match.group(0)

        original_magnet_text = clean_release[season_ep_match.end():]
        original_magnet_text = _split_technical_components(original_magnet_text)
        processed_magnet_text = _extract_technical_info(original_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)

        if year_from_release:
            return finalize_title(f"{base_title}.{season_ep_str}.{year_from_release}{processed_magnet_text}")
        else:
            return finalize_title(f"{base_title}.{season_ep_str}{processed_magnet_text}")

    technical_parts = []
    parts = clean_release.split('.')

    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue


        if re.match(r'^S\d{1,2}$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

        elif re.match(r'^(19|20)\d{2}$', part_clean):
            technical_parts.append(part_clean)

        elif re.match(r'^(1080p|720p|480p|2160p|4K|HD|FHD|UHD|SD|HDR|FULLHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

        elif re.match(r'^(x264|x265|H\.264|H\.265|H264|H265|AVC|HEVC)$', part_clean, re.IGNORECASE):
            if re.match(r'^H(264|265)$', part_clean, re.IGNORECASE):
                part_clean = f'H.{part_clean[1:]}'
            technical_parts.append(part_clean)

        elif re.match(r'^(WEB-DL|WEBRip|BluRay|DVDRip|HDRip|HDTV|BDRip|BRRip|CAMRip|CAM|TSRip|TS|TC|R5|SCR|DVDScr)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

        elif re.match(r'^(DUAL|DUBLADO|DDP5\.1|Atmos|AC3|AAC|MP3|FLAC|DTS|NACIONAL|Legendado)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

        elif re.match(r'^(HDR|5\.1|2\.0|7\.1|DTS-HD|TrueHD)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

        elif re.match(r'^\d+\.\d+-[A-Z0-9]+$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

        elif re.match(r'^-[A-Z0-9]+$', part_clean):
            technical_parts.append(part_clean)

        elif re.match(r'^\d+\.?\d*\s*(GB|MB)$', part_clean, re.IGNORECASE):
            technical_parts.append(part_clean)

    clean_release = '.'.join(technical_parts)

    season_only_match = re.search(r'(?i)S(\d{1,2})(?![E\d])(?:[^E]|$)', clean_release)
    if season_only_match:
        season_num_raw = season_only_match.group(1)
        try:
            season_num = int(season_num_raw)
            if season_num <= 0:
                season_only_match = None
            else:
                season = season_num_raw.zfill(2)
                season_str = f"S{season}"
        except (ValueError, TypeError):
            season_only_match = None

    if season_only_match:

        year_from_release = year
        if not year_from_release:
            year_match = re.search(r'(19|20)\d{2}', clean_release)
            if year_match:
                year_from_release = year_match.group(0)

        if year_from_release:
            processed_magnet_text = clean_release[season_only_match.end():]
            processed_magnet_text = re.sub(r'(19|20)\d{2}', '', processed_magnet_text)
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}.{year_from_release}{processed_magnet_text}")
        else:
            processed_magnet_text = clean_release[season_only_match.end():]
            processed_magnet_text = _clean_remaining(processed_magnet_text)
            return finalize_title(f"{base_title}.{season_str}{processed_magnet_text}")

    year_from_release = year
    if not year_from_release:
        year_match = re.search(r'(19|20)\d{2}', clean_release)
        if year_match:
            year_from_release = year_match.group(0)

    if year_from_release:
        processed_magnet_text = re.sub(r'(19|20)\d{2}', '', clean_release)
        processed_magnet_text = _split_technical_components(processed_magnet_text)
        processed_magnet_text = _extract_technical_info(processed_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}.{year_from_release}{processed_magnet_text}")

    if clean_release:
        processed_magnet_text = _split_technical_components(clean_release)
        processed_magnet_text = _extract_technical_info(processed_magnet_text)
        processed_magnet_text = _clean_remaining(processed_magnet_text)
        return finalize_title(f"{base_title}{processed_magnet_text}")

    return finalize_title(base_title)
