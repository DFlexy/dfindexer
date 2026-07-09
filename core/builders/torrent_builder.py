# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

"""Construção de torrents a partir de magnets — lógica compartilhada por todos os scrapers.

Consolida o loop que era duplicado em scraper/{bludv,comand,rede,starck,tfilme}.py.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from bs4 import BeautifulSoup

from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.parsing.audio_extraction import add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title

logger = logging.getLogger(__name__)


def _audio_tag_origin(audio_info: str, magnet_original: str, missing_dn: bool, info_hash: str) -> str:
    if audio_info:
        return 'HTML da página (detect_audio_from_html)'
    if magnet_original:
        lower = magnet_original.lower()
        if 'dual' in lower or 'dublado' in lower or 'legendado' in lower:
            return 'magnet_processed'
    if missing_dn and info_hash:
        return 'metadata (iTorrents.org) - usado durante processamento'
    return 'N/A'


def build_torrent_from_magnet(
    *,
    magnet_link: str,
    idx: int,
    sizes: List[str],
    page_title: str,
    original_title: str,
    title_translated_processed: str,
    year: str,
    imdb: str,
    audio_info: str,
    audio_html_content: str,
    absolute_link: str,
    date: Optional[datetime],
    legend_info: Optional[Dict],
    skip_metadata: bool,
    doc: Optional[BeautifulSoup] = None,
    scraper_type: str = '',
    fallback_title_priority: str = 'page',
    original_title_fallbacks: Optional[List[str]] = None,
    imdb_default: str = '',
) -> Optional[Dict]:
    """Processa um magnet e devolve o dict de torrent no formato esperado pelos scrapers.

    `fallback_title_priority`:
      - 'page': page_title or original_title (padrão tfilme/comand/rede/starck)
      - 'original_first': original_title or title_translated or page_title (bludv)
    `original_title_fallbacks`: lista adicional de fallbacks para o campo original_title
      (ex.: title_translated) — usado pelo bludv.
    `imdb_default`: valor default de imdb quando vazio (bludv usa '').
    """
    try:
        magnet_data = MagnetParser.parse(magnet_link)
    except Exception as e:
        logger.error(
            "Magnet parse error: %s: %s (link: %s)",
            type(e).__name__,
            str(e).split('\n')[0][:100],
            magnet_link[:80],
        )
        return None

    info_hash = magnet_data['info_hash']

    cross_data = None
    try:
        from utils.text.cross_data import get_cross_data_from_redis
        cross_data = get_cross_data_from_redis(info_hash)
    except Exception:
        pass

    if cross_data:
        if not original_title and cross_data.get('title_original_html'):
            original_title = cross_data['title_original_html']
        if not title_translated_processed and cross_data.get('title_translated_html'):
            title_translated_processed = cross_data['title_translated_html']
        if not imdb and cross_data.get('imdb'):
            imdb = cross_data['imdb']

    magnet_original = magnet_data.get('display_name', '')
    missing_dn = not magnet_original or len(magnet_original.strip()) < 3

    from utils.text.storage import _looks_like_bludv_processed_release_name

    if not missing_dn and magnet_original and not _looks_like_bludv_processed_release_name(magnet_original):
        try:
            from utils.text.storage import save_release_title_to_redis
            save_release_title_to_redis(info_hash, magnet_original)
        except Exception:
            pass

    if fallback_title_priority == 'original_first':
        fallback_title = original_title or title_translated_processed or page_title or ''
    elif fallback_title_priority == 'original_then_page':
        fallback_title = original_title if original_title else page_title
    else:
        fallback_title = page_title or original_title or ''
    original_release_title = prepare_release_title(
        magnet_original,
        fallback_title,
        year,
        missing_dn=missing_dn,
        info_hash=info_hash if missing_dn else None,
        skip_metadata=skip_metadata,
    )

    standardized_title = create_standardized_title(
        original_title,
        year,
        original_release_title,
        title_translated_html=title_translated_processed if title_translated_processed else None,
        magnet_original=magnet_original,
    )

    final_title = add_audio_tag_if_needed(
        standardized_title,
        original_release_title,
        info_hash=info_hash,
        skip_metadata=skip_metadata,
        audio_info_from_html=audio_info,
        audio_html_content=audio_html_content,
    )

    origem_audio_tag = _audio_tag_origin(audio_info, magnet_original, missing_dn, info_hash)

    from utils.parsing.legend_extraction import determine_legend_presence
    has_legenda = determine_legend_presence(
        legend_info_from_html=legend_info,
        audio_html_content=audio_html_content,
        magnet_processed=original_release_title,
        info_hash=info_hash,
        skip_metadata=skip_metadata,
    )

    size = ''
    if sizes and idx < len(sizes):
        size = sizes[idx]

    trackers = process_trackers(magnet_data)

    magnet_display_name = (magnet_original or '').strip()
    from utils.text.storage import (
        get_raw_torrent_name,
        magnet_original_needs_raw_name,
    )
    if magnet_original_needs_raw_name(magnet_display_name, original_release_title):
        magnet_display_name = ''
    if not magnet_display_name and info_hash and not skip_metadata:
        try:
            raw_name = get_raw_torrent_name(info_hash, skip_metadata=skip_metadata)
            if raw_name:
                magnet_display_name = raw_name.strip()
        except Exception:
            pass

    try:
        from utils.text.cross_data import save_cross_data_to_redis
        cross_data_to_save = {
            'title_original_html': original_title if original_title else None,
            'magnet_processed': original_release_title if original_release_title else None,
            'magnet_original': magnet_display_name if magnet_display_name else None,
            'title_translated_html': title_translated_processed if title_translated_processed else None,
            'imdb': imdb if imdb else None,
            'missing_dn': missing_dn,
            'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None,
            'size': size if size and size.strip() else None,
            'has_legenda': has_legenda,
            'legend': legend_info if legend_info else None,
        }
        if missing_dn and magnet_display_name:
            cross_data_to_save['metadata_name'] = magnet_display_name
        save_cross_data_to_redis(info_hash, cross_data_to_save)
    except Exception:
        pass

    displayed_original_title = original_title if original_title else page_title
    if not original_title and original_title_fallbacks:
        for fb in original_title_fallbacks:
            if fb:
                displayed_original_title = fb
                break

    torrent = {
        'title_processed': final_title,
        'original_title': displayed_original_title,
        'title_translated_processed': title_translated_processed if title_translated_processed else None,
        'details': absolute_link,
        'year': year,
        'imdb': imdb if imdb else imdb_default,
        'audio': [],
        'magnet_link': magnet_link,
        'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
        'info_hash': info_hash,
        'trackers': trackers,
        'size': size,
        'leech_count': 0,
        'seed_count': 0,
        'magnet_original': magnet_display_name if magnet_display_name else None,
        'magnet_processed': original_release_title if original_release_title else None,
        'similarity': 1.0,
        'legend': legend_info if legend_info else None,
        'has_legenda': has_legenda,
    }
    return torrent


def build_torrents_from_magnets(
    *,
    magnet_links: List[str],
    sizes: List[str],
    page_title: str,
    original_title: str,
    title_translated_processed: str,
    year: str,
    imdb: str,
    audio_info: str,
    audio_html_content: str,
    absolute_link: str,
    date: Optional[datetime],
    legend_info: Optional[Dict],
    skip_metadata: bool,
    doc: Optional[BeautifulSoup] = None,
    scraper_type: str = '',
    log_ctx: Any = None,
    fallback_title_priority: str = 'page',
    original_title_fallbacks: Optional[List[str]] = None,
    imdb_default: str = '',
) -> List[Dict]:
    """Itera sobre os magnets construindo a lista de torrents, isolando erros por magnet."""
    torrents: List[Dict] = []
    for idx, magnet_link in enumerate(magnet_links):
        try:
            torrent = build_torrent_from_magnet(
                magnet_link=magnet_link,
                idx=idx,
                sizes=sizes,
                page_title=page_title,
                original_title=original_title,
                title_translated_processed=title_translated_processed,
                year=year,
                imdb=imdb,
                audio_info=audio_info,
                audio_html_content=audio_html_content,
                absolute_link=absolute_link,
                date=date,
                legend_info=legend_info,
                skip_metadata=skip_metadata,
                doc=doc,
                scraper_type=scraper_type,
                fallback_title_priority=fallback_title_priority,
                original_title_fallbacks=original_title_fallbacks,
                imdb_default=imdb_default,
            )
            if torrent:
                torrents.append(torrent)
        except Exception as e:
            if log_ctx is not None:
                log_ctx.error_magnet(magnet_link, e)
            else:
                logger.error(
                    "Magnet error: %s: %s (link: %s)",
                    type(e).__name__,
                    str(e).split('\n')[0][:100],
                    magnet_link[:80],
                )
            continue
    return torrents
