# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
from typing import Optional, Dict

def get_release_title_from_redis(info_hash: str) -> Optional[str]:
    from app.config import Config
    if not info_hash or len(info_hash) != Config.INFO_HASH_LENGTH:
        return None
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import release_title_key
        
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
        from cache.redis_client import get_redis_client
        from cache.redis_keys import release_title_key
        
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
    """DN/release com fonte (WEB-DL etc.) mas sem resolução nem codec — típico de magnet incompleto"""
    if not title or len(title.strip()) < 3:
        return True
    lower = title.lower()
    has_source = any(m in lower for m in _RELEASE_SOURCE_MARKERS)
    has_quality = any(m in lower for m in _RESOLUTION_CODEC_MARKERS)
    if has_source and not has_quality:
        return True
    return False

def _is_metadata_more_complete(metadata_name: str, cross_magnet_processed: str) -> bool:
    """Compara se metadata['name'] tem mais informações técnicas que cross_data['magnet_processed']"""
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
    """Detecta título normalizado do Bludv (-S02E05-1080P-.MKV....) — não é o name do .torrent."""
    if not name:
        return False
    stripped = name.strip()
    if not re.match(r'^-S\d{1,2}E\d{1,2}-', stripped, re.IGNORECASE):
        return False
    return stripped.count('.') >= 3

def magnet_original_needs_raw_name(name: str, magnet_processed: str = '') -> bool:
    """True quando magnet_original não é o nome bruto do .torrent."""
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
    """Preenche magnet_original com o name bruto do .torrent (iTorrents/cache)."""
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
    """Evita HTTP ao iTorrents só quando já há size + nome bruto válido no cache."""
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
    """Nome exato do torrent (campo name do .torrent / iTorrents), sem normalização."""
    if skip_metadata or not info_hash or len(info_hash) != 40:
        return None

    try:
        from utils.text.cross_data import get_cross_data_from_redis
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
        from cache.metadata_cache import MetadataCache
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
                    from utils.text.cross_data import save_cross_data_to_redis
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
        from utils.text.cross_data import get_cross_data_from_redis
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
        from cache.metadata_cache import MetadataCache
        metadata_cache = MetadataCache()
        cached_metadata = metadata_cache.get(info_hash.lower())
        if cached_metadata and cached_metadata.get('name'):
            metadata_name = cached_metadata.get('name', '').strip()
            if metadata_name and len(metadata_name) >= 3:
                if cross_data_magnet_processed:
                    if _is_metadata_more_complete(metadata_name, cross_data_magnet_processed):
                        try:
                            from utils.text.cross_data import save_cross_data_to_redis
                            from utils.text.title_builder import _normalize_metadata_name
                            
                            normalized_metadata = _normalize_metadata_name(metadata_name)
                            
                            save_cross_data_to_redis(info_hash, {'metadata_name': metadata_name, 'magnet_processed': normalized_metadata})
                        except Exception:
                            pass
                        return metadata_name
                    else:
                        return cross_data_magnet_processed
                else:
                    try:
                        from utils.text.cross_data import save_cross_data_to_redis
                        from utils.text.title_builder import _normalize_metadata_name
                        
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
    """Reconstrói title_processed quando metadata['name'] é mais completo que o título atual"""
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

    from utils.text.title_builder import (
        prepare_release_title,
        create_standardized_title,
    )
    from utils.parsing.audio_extraction import add_audio_tag_if_needed

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
    """Indica se vale buscar metadata para completar o título antes do filtro/resposta."""
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

