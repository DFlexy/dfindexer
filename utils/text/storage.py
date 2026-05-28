# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

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
    cross_data_metadata_name = None
    try:
        from utils.text.cross_data import get_cross_data_from_redis
        cross_data = get_cross_data_from_redis(info_hash)
        if cross_data:
            if cross_data.get('metadata_name'):
                metadata_name = str(cross_data.get('metadata_name')).strip()
                if metadata_name and metadata_name != 'N/A' and len(metadata_name) >= 3:
                    return metadata_name
            
            if cross_data.get('magnet_processed'):
                cross_data_magnet_processed = str(cross_data.get('magnet_processed')).strip()
                if cross_data_magnet_processed and cross_data_magnet_processed != 'N/A' and len(cross_data_magnet_processed) >= 3:
                    pass
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

