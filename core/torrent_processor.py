# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from datetime import datetime
from typing import Any, Callable, Dict, List

from bs4 import NavigableString, Tag

from utils.text import check_query_match

logger = logging.getLogger(__name__)

class QueryFilter:
    @staticmethod
    def create_filter(query: str) -> Callable[[Dict], bool]:
        if not query:
            return lambda t: True

        def filter_func(torrent: Dict) -> bool:
            title_processed = torrent.get('title_processed') or ''
            original_title = torrent.get('original_title') or ''
            title_translated = torrent.get('title_translated_processed') or ''

            title_processed = str(title_processed) if title_processed is not None else ''
            original_title = str(original_title) if original_title is not None else ''
            title_translated = str(title_translated) if title_translated is not None else ''

            result = check_query_match(
                query,
                title_processed,
                original_title,
                title_translated,
            )

            if result:
                logger.debug(f"Resultado Aprovado: Query='{query[:50]}' | Title='{title_processed[:60]}' | Original='{original_title[:40]}' | Translated='{title_translated[:40]}'")
            else:

                query_words = set(query.lower().split())
                title_words = set((title_processed + ' ' + original_title + ' ' + title_translated).lower().split())

                common_words = query_words.intersection(title_words)
                common_words = {w for w in common_words if len(w) > 2 and w not in ['the', 'and', 'of', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'de', 'da', 'do', 'e', 'o', 'a', 'os', 'as']}

                if common_words:
                    logger.debug(f"Resultado Rejeitado: Query='{query[:50]}' | Title='{title_processed[:60]}' | Original='{original_title[:40]}' | Translated='{title_translated[:40]}'")

            return result

        return filter_func

class TorrentProcessor:
    @staticmethod
    def _sanitize_value(value: Any) -> Any:

        if value is None:
            return None

        if isinstance(value, Tag):
            return value.get_text(strip=True) if hasattr(value, 'get_text') else str(value)

        if isinstance(value, NavigableString):
            return str(value)

        if isinstance(value, list):
            return [TorrentProcessor._sanitize_value(item) for item in value]

        if isinstance(value, dict):
            return {k: TorrentProcessor._sanitize_value(v) for k, v in value.items()}

        return value

    @staticmethod
    def sanitize_torrents(torrents: List[Dict]) -> None:

        for torrent in torrents:
            for key, value in list(torrent.items()):
                sanitized = TorrentProcessor._sanitize_value(value)
                if sanitized != value:
                    torrent[key] = sanitized

    @staticmethod
    def remove_internal_fields(torrents: List[Dict]) -> None:
        from datetime import datetime

        for torrent in torrents:
            torrent.pop('_metadata', None)
            torrent.pop('_metadata_fetched', None)
            torrent.pop('_original_order', None)


            if 'title_processed' in torrent and 'title' not in torrent:
                torrent['title'] = torrent.get('title_processed', '')

            date_value = torrent.get('date')
            if not date_value or (isinstance(date_value, str) and date_value.strip() == ''):
                torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')


            if torrent.get('seed_count') is None:
                torrent['seed_count'] = 0
            else:
                try:
                    torrent['seed_count'] = int(torrent['seed_count'])
                except (ValueError, TypeError):
                    torrent['seed_count'] = 0

            if torrent.get('leech_count') is None:
                torrent['leech_count'] = 0
            else:
                try:
                    torrent['leech_count'] = int(torrent['leech_count'])
                except (ValueError, TypeError):
                    torrent['leech_count'] = 0

            if not torrent.get('magnet_link') and torrent.get('magnet'):
                torrent['magnet_link'] = torrent['magnet']

            if not torrent.get('details'):
                torrent['details'] = torrent.get('magnet_link', '')

            if not torrent.get('info_hash'):
                magnet_link = torrent.get('magnet_link', '')
                if magnet_link and 'xt=urn:btih:' in magnet_link.lower():
                    try:
                        import re
                        match = re.search(r'xt=urn:btih:([a-f0-9]{40})', magnet_link, re.IGNORECASE)
                        if match:
                            torrent['info_hash'] = match.group(1).lower()
                    except Exception:
                        pass

    @staticmethod
    def sort_by_date(torrents: List[Dict], reverse: bool = True) -> None:
        def sort_key(torrent: Dict) -> datetime:
            date_str = torrent.get('date', '')
            if not date_str:
                return datetime.min.replace(tzinfo=None)

            try:
                dt = None
                if 'T' in date_str:
                    if '+' in date_str or 'Z' in date_str:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(date_str)
                else:
                    dt = datetime.strptime(date_str.split('T')[0], '%Y-%m-%d')

                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)

                return dt
            except (ValueError, AttributeError, TypeError):
                return datetime.min.replace(tzinfo=None)

        torrents.sort(key=sort_key, reverse=reverse)
