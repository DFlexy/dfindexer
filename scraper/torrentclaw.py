# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import json
import os
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable, Any
from urllib.parse import quote, urlencode, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from scraper.base import SiteConfig
from utils.text import format_bytes
from utils.log import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("TorrentClaw", logger)

SITE = SiteConfig(
    # Endereço do site: ajuste aqui se o domínio mudar.
    url="https://torrentclaw.com/",
    caminho_busca="pt/search?q=",
    paginacao="pt/genero/anime?lang=pt-BR&page={}&sort=recent&quality=1080p&type=show",
    seletores={
        "card": 'a[href*="/series/"], a[href*="/filmes/"], a[href*="/shows/"], a[href*="/movies/"]',
        "api_busca": "api/v1/search",
        "catalogo_anime": "pt/genero/anime",
        "genero": "Anime",
        "generos_anime": "anime,donghua,animation,animação,animacao",
        "idioma_audio": "pt-BR",
        "idioma_legenda": "pt",
        "tipo": "show",
        "ordenacao_recente": "recent",
        "catalogo_1080p": "pt/genero/anime?lang=pt-BR&page={}&sort=recent&quality=1080p&verified=&type=show",
        "catalogo_720p": "pt/genero/anime?lang=pt-BR&page={}&sort=recent&quality=720p&verified=&type=show",
        "titulo": "h1",
        "json_ld": 'script[type="application/ld+json"]',
        "imdb": 'a[href*="imdb.com/title/"]',
        "links_magnet": 'a[href^="magnet:"]',
    },
)

_RE_CONTENT_PATH = re.compile(
    r'/(?:pt/)?(?:series|filmes|shows|movies)/([a-z0-9][a-z0-9-]{2,}-\d{4}-\d+)',
    re.I,
)
_RE_EPISODE_SUFFIX = re.compile(r'/s\d{1,2}e\d{1,2}/?$', re.I)
_RE_QUERY_EPISODE = re.compile(r'(?i)\bs(\d{1,2})e(\d{1,2})\b')
_RE_H1_YEAR = re.compile(r'\(\s*((?:19|20)\d{2})\s*\)\s*$')
_RE_INFO_HASH = re.compile(r'"infoHash"\s*:\s*"([a-fA-F0-9]{40})"')
_RE_MAGNET = re.compile(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\s"\'<>]*', re.I)
_RE_LANG_TOKEN = re.compile(r'[a-z]{2}(?:-[A-Z0-9]+)?', re.I)

_MAX_SEARCH_PAGES = 3
_MAX_TORRENTS_PER_PAGE = 100

_LANG_AUDIO_LABELS = {
    'pt': 'Português',
    'pt-br': 'Português',
    'pt-pt': 'Português',
    'en': 'Inglês',
    'ja': 'Japonês',
    'dual': 'Dual',
}
_PT_BR_AUDIO_CODES = frozenset({'pt-br', 'ptbr'})
_RE_DUBLADO_TITLE = re.compile(r'(?i)\bdublado\b')
_RE_PT_SUB_TITLE = re.compile(
    r'(?i)(?:\bpt[\s._-]?br\b|\bptbr\b|\blegend(?:a|ado)\b|multi[\s._-]?sub)',
)


class TorrentclawScraper(BaseScraper):
    SITE = SITE
    SCRAPER_TYPE = "torrentclaw"
    DISPLAY_NAME = "TorrentClaw"

    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self._api_result_titles: Dict[str, str] = {}

    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(
            max_items, is_test=is_test
        )
        try:
            try:
                page_num = int(page or '1')
            except (TypeError, ValueError):
                page_num = 1

            from scraper.pipeline import (
                get_effective_max_items, limit_list, process_links_parallel
            )
            effective_max = get_effective_max_items(max_items)
            if effective_max > 0:
                limit_1080 = effective_max // 2
                limit_720 = effective_max - limit_1080
            else:
                limit_1080 = 0
                limit_720 = 0

            links_1080 = limit_list(
                self._collect_recent_catalog_links('1080p', page_num, limit_1080),
                limit_1080,
            )
            links_720 = limit_list(
                self._collect_recent_catalog_links('720p', page_num, limit_720),
                limit_720,
            )
            _log_ctx.info(
                f"Limite configurado: {effective_max} - "
                f"Coletando {len(links_1080)} animes 1080p e {len(links_720)} animes 720p"
            )

            torrents_1080 = process_links_parallel(
                links_1080,
                lambda link: self._get_torrents_from_page(link, quality_filter='1080p'),
                None,
                scraper_name=self.SCRAPER_TYPE,
                use_flaresolverr=self.use_flaresolverr,
            )
            torrents_720 = process_links_parallel(
                links_720,
                lambda link: self._get_torrents_from_page(link, quality_filter='720p'),
                None,
                scraper_name=self.SCRAPER_TYPE,
                use_flaresolverr=self.use_flaresolverr,
            )
            return self.enrich_torrents(
                torrents_1080 + torrents_720,
                skip_metadata=skip_metadata,
                skip_trackers=skip_trackers,
            )
        finally:
            self._skip_metadata = False

    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        return self._extract_search_results(doc)

    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links: List[str] = []
        seen: set = set()
        for item in doc.select(SITE.seletores["card"]):
            href = (item.get('href') or '').strip()
            absolute = self._normalize_content_url(href)
            if not absolute:
                continue
            key = self._content_key(absolute)
            if key in seen:
                continue
            seen.add(key)
            links.append(absolute)
        return links

    def _recent_catalog_url(self, quality: str, page: int) -> str:
        key = f"catalogo_{quality}"
        template = SITE.seletores.get(key) or (
            f"pt/genero/anime?lang=pt-BR&page={{}}&sort=recent&quality={quality}&verified=&type=show"
        )
        return urljoin(self.base_url, template.format(page))

    def _recent_catalog_api_filters(self, quality: str, page: int) -> Dict[str, Any]:
        return self._anime_api_filters({
            'lang': SITE.seletores.get("idioma_audio") or 'pt-BR',
            'sort': SITE.seletores.get("ordenacao_recente") or 'recent',
            'quality': quality,
            'type': SITE.seletores.get("tipo") or 'show',
            'page': page,
        })

    def _collect_recent_catalog_links(self, quality: str, page: int, limit: int) -> List[str]:
        from scraper.pipeline import limit_list
        if limit <= 0:
            return []
        doc = self.get_document(self._recent_catalog_url(quality, page), self.base_url)
        links = self._extract_links_from_page(doc) if doc else []
        if not links:
            links = self._api_content_links('', extra=self._recent_catalog_api_filters(quality, page))
        return limit_list(links, limit)

    def _collect_search_result_titles(self, doc: BeautifulSoup) -> Dict[str, str]:
        title_by_url: Dict[str, str] = {}
        if self._api_result_titles:
            title_by_url.update(self._api_result_titles)

        for item in doc.select(SITE.seletores["card"]):
            href = (item.get('href') or '').strip()
            absolute = self._normalize_content_url(href)
            if not absolute:
                continue
            title_text = (item.get_text(' ', strip=True) or item.get('title') or '').strip()
            normalized = self._normalize_search_result_url(absolute)
            if normalized and title_text:
                title_by_url[normalized] = title_text
        return title_by_url

    def _search_variations(self, query: str) -> List[str]:
        links: List[str] = []
        seen: set = set()
        self._api_result_titles = {}

        variations = [query]
        query_words = query.split()
        if (
            len(query_words) >= 2
            and query_words[-1].isdigit()
            and len(query_words[-1]) == 4
            and query_words[-1][:2] in ('19', '20')
        ):
            without_year = ' '.join(query_words[:-1])
            if without_year not in variations:
                variations.append(without_year)

        extra = self._query_api_filters(query)
        for variation in variations:
            page_links = self._api_content_links(variation, extra=extra)
            if not page_links:
                page_links = self._html_search_links(variation)
            for href in page_links:
                key = self._content_key(href)
                if key in seen:
                    continue
                seen.add(key)
                links.append(href)
        return links

    def _html_search_links(self, variation: str) -> List[str]:
        from urllib.parse import quote as url_quote
        search_url = f"{self.base_url}{self.search_url}{url_quote(variation)}"
        doc = self.get_document(search_url, self.base_url)
        if not doc:
            catalog_url = urljoin(self.base_url, SITE.seletores.get("catalogo_anime") or "pt/genero/anime")
            doc = self.get_document(catalog_url, self.base_url)
        if not doc:
            return []
        page_links = self._extract_search_results(doc)
        return self._filter_links_by_result_titles(doc, page_links, variation)

    def _anime_api_filters(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        merged = dict(extra or {})
        merged['genre'] = SITE.seletores.get("genero") or "Anime"
        return merged

    def _query_api_filters(self, query: str) -> Dict[str, Any]:
        from utils.text import extract_query_season
        extra: Dict[str, Any] = {'sort': 'seeders'}
        season = extract_query_season(query)
        episode = self._extract_query_episode(query)
        if season:
            extra['season'] = season
        if episode:
            extra['episode'] = episode
        return extra

    def _api_content_links(self, query: str, extra: Optional[Dict[str, Any]] = None) -> List[str]:
        links: List[str] = []
        seen: set = set()
        extra = extra or {}
        start_page = int(extra.get('page') or 1)
        max_pages = 1 if not query else _MAX_SEARCH_PAGES

        for offset in range(max_pages):
            page = start_page + offset
            payload = self._fetch_search_api(query, extra, page)
            if not payload:
                break
            results = payload.get('results') or []
            if not results:
                break
            for result in results:
                if not isinstance(result, dict):
                    continue
                if not self._is_anime_result(result):
                    continue
                if query and not self._api_result_matches_query(query, result):
                    continue
                absolute = self._content_url_from_result(result)
                if not absolute:
                    continue
                key = self._content_key(absolute)
                if key in seen:
                    continue
                seen.add(key)
                links.append(absolute)
                title_text = (
                    result.get('title')
                    or result.get('titleOriginal')
                    or ''
                ).strip()
                if title_text:
                    self._api_result_titles[self._normalize_search_result_url(absolute)] = title_text
            if not query:
                break
            total = payload.get('total') or 0
            page_size = payload.get('pageSize') or len(results)
            if page * page_size >= total:
                break
        return links

    def _fetch_search_api(self, query: str, extra: Dict[str, Any], page: int) -> Optional[Dict]:
        params: Dict[str, Any] = {
            'locale': 'pt',
            'limit': 20,
            'page': page,
        }
        if query and query.strip():
            params['q'] = query.strip()
        for key, value in extra.items():
            if key == 'page' or value in (None, ''):
                continue
            params[key] = value

        api_url = f"{self.base_url}{SITE.seletores['api_busca']}?{urlencode(params, doseq=True)}"
        headers = {
            'Accept': 'application/json',
            'Referer': self.base_url,
            'x-search-source': 'dfindexer',
        }
        api_key = (os.getenv('TORRENTCLAW_API_KEY') or os.getenv('SCRAPER_API_KEY_TORRENTCLAW') or '').strip()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        if not self._ensure_site_online():
            return None
        try:
            response = self.session.get(api_url, headers=headers, timeout=self._request_timeout())
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.debug(f"[TorrentClaw] API search error: {type(e).__name__} - {str(e).split(chr(10))[0][:100]}")
        return None

    def _request_timeout(self) -> int:
        from app.config import Config
        return Config.HTTP_REQUEST_TIMEOUT

    def _is_anime_result(self, result: Dict) -> bool:
        genres = result.get('genres') or []
        return self._has_anime_genre(genres)

    @staticmethod
    def _has_anime_genre(genres) -> bool:
        if not genres:
            return False
        if isinstance(genres, str):
            genres = [genres]
        allowed = {
            token.strip().lower()
            for token in (SITE.seletores.get("generos_anime") or "anime").split(',')
            if token.strip()
        }
        return any(str(genre).strip().lower() in allowed for genre in genres)

    def _api_result_matches_query(self, query: str, result: Dict) -> bool:
        title_query = self._title_only_query(query)
        if not title_query:
            return True
        from utils.text import check_query_match
        return check_query_match(
            title_query,
            result.get('title') or '',
            result.get('titleOriginal') or '',
            result.get('title') or '',
        )

    def _content_url_from_result(self, result: Dict) -> str:
        path = (result.get('contentUrl') or '').strip()
        if not path:
            content_type = (result.get('contentType') or 'movie').lower()
            folder = 'shows' if content_type == 'show' else 'movies'
            slug_source = result.get('titleOriginal') or result.get('title') or ''
            slug = re.sub(r'[^a-z0-9]+', '-', slug_source.lower()).strip('-')
            year = result.get('year') or ''
            result_id = result.get('id') or ''
            if slug and year and result_id:
                path = f"/{folder}/{slug}-{year}-{result_id}"
        return self._normalize_content_url(path)

    def _normalize_content_url(self, href: str) -> str:
        if not href:
            return ''
        absolute = urljoin(self.base_url, href)
        absolute = absolute.split('#', 1)[0].split('?', 1)[0]
        absolute = _RE_EPISODE_SUFFIX.sub('', absolute)
        if not _RE_CONTENT_PATH.search(absolute):
            return ''
        return absolute.rstrip('/')

    @staticmethod
    def _content_key(url: str) -> str:
        match = _RE_CONTENT_PATH.search(url or '')
        if match:
            return match.group(1).lower()
        return (url or '').rstrip('/').lower()

    @staticmethod
    def _extract_query_episode(query: str) -> Optional[int]:
        if not query:
            return None
        match = _RE_QUERY_EPISODE.search(query)
        if not match:
            return None
        try:
            episode = int(match.group(2))
        except (TypeError, ValueError):
            return None
        return episode if 1 <= episode <= 99 else None

    @staticmethod
    def _title_only_query(query: str) -> str:
        text = query or ''
        text = re.sub(r'(?i)\b(?:temporada|season)\s*\d{1,2}\b', ' ', text)
        text = re.sub(r'(?i)\bs\d{1,2}e\d{1,2}\b', ' ', text)
        text = re.sub(r'(?i)\bs\d{1,2}\b', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    def _get_torrents_from_page(self, link: str, quality_filter: Optional[str] = None) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not str(link).startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []

        page_title, original_title, title_translated, year, imdb, genres = self._extract_page_identity(doc)
        if not page_title:
            self._log_structure_miss(absolute_link, SITE.seletores["titulo"])
            return []

        if genres and not self._has_anime_genre(genres):
            return []

        if not original_title:
            original_title = page_title

        title_query = self._title_only_query(self._active_search_query)
        if title_query:
            from utils.text import check_query_match
            if not check_query_match(title_query, page_title, original_title, title_translated):
                from scraper.pipeline import mark_page_skipped_by_query
                mark_page_skipped_by_query()
                return []

        from utils.parsing import extract_date_from_page
        page_date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)

        raw_items = self._extract_torrent_items(doc)
        if not raw_items:
            self._log_structure_miss(absolute_link, 'infoHash/magnet na página')
            return []

        raw_items = self._filter_items_by_query(raw_items, quality_filter=quality_filter)
        if not raw_items:
            return []

        from core.torrent_builder import build_torrent_from_magnet
        torrents: List[Dict] = []
        for item in raw_items:
            magnet_link = item.get('magnet') or ''
            if not magnet_link.startswith('magnet:'):
                continue
            item_date = item.get('date') or page_date
            try:
                torrent = build_torrent_from_magnet(
                    magnet_link=magnet_link,
                    idx=0,
                    sizes=[item.get('size') or ''],
                    page_title=page_title,
                    original_title=original_title,
                    title_translated_processed=title_translated,
                    year=year,
                    imdb=imdb,
                    audio_info=item.get('audio_info') or '',
                    audio_html_content=item.get('audio_html') or '',
                    absolute_link=absolute_link,
                    date=item_date,
                    legend_info=item.get('legend_info'),
                    skip_metadata=self._skip_metadata,
                    doc=doc,
                    scraper_type=self.SCRAPER_TYPE,
                    fallback_title_priority='original_then_page',
                    original_title_fallbacks=[title_translated],
                )
            except Exception as e:
                _log_ctx.error_magnet(magnet_link, e)
                continue
            if not torrent:
                continue
            processed = torrent.get('title_processed') or ''
            if not item.get('has_pt_br_audio') and '[Brazilian]' in processed:
                processed = re.sub(r'\s*\[Brazilian\]', '', processed).strip()
            if item.get('has_pt_subs'):
                torrent['has_legenda'] = True
                if not item.get('has_pt_br_audio') and '[Eng]' not in processed:
                    processed = f"{processed} [Eng]".strip()
            torrent['title_processed'] = processed
            torrent['seed_count'] = item.get('seeders') or 0
            torrent['leech_count'] = item.get('leechers') or 0
            torrents.append(torrent)
        return torrents

    def _extract_page_identity(self, doc: BeautifulSoup):
        page_title = ''
        original_title = ''
        title_translated = ''
        year = ''
        imdb = ''
        genres: List[str] = []

        ld = self._parse_json_ld(doc)
        if ld:
            page_title = (ld.get('name') or '').strip()
            original_title = (ld.get('alternateName') or '').strip()
            if not original_title:
                original_title = page_title
            if original_title and page_title and original_title.lower() != page_title.lower():
                title_translated = page_title
            published = str(ld.get('datePublished') or '')
            year_match = re.search(r'((?:19|20)\d{2})', published)
            if year_match:
                year = year_match.group(1)
            ld_genres = ld.get('genre') or []
            if isinstance(ld_genres, str):
                ld_genres = [ld_genres]
            genres = [str(g).strip() for g in ld_genres if g]
            same_as = ld.get('sameAs')
            same_as_values = same_as if isinstance(same_as, list) else [same_as]
            for value in same_as_values:
                imdb_match = re.search(r'(tt\d+)', str(value or ''))
                if imdb_match:
                    imdb = imdb_match.group(1)
                    break

        if not page_title:
            h1 = doc.select_one(SITE.seletores["titulo"])
            if h1:
                page_title = h1.get_text(' ', strip=True)

        if page_title:
            year_in_title = _RE_H1_YEAR.search(page_title)
            if year_in_title:
                if not year:
                    year = year_in_title.group(1)
                page_title = page_title[:year_in_title.start()].strip()

        if not original_title:
            for text_node in doc.find_all(string=re.compile(r'T[íi]tulo original\s*:', re.I)):
                blob = text_node if isinstance(text_node, str) else text_node.get_text(' ', strip=True)
                match = re.search(r'T[íi]tulo original\s*:\s*(.+)$', blob, re.I)
                if match:
                    original_title = match.group(1).strip()
                    break

        if not imdb:
            from utils.parsing import extract_imdb_from_soup
            imdb = extract_imdb_from_soup(doc)

        if original_title and not title_translated and page_title and original_title.lower() != page_title.lower():
            title_translated = page_title

        return page_title, original_title, title_translated, year, imdb, genres

    def _parse_json_ld(self, doc: BeautifulSoup) -> Dict:
        for script in doc.select(SITE.seletores["json_ld"]):
            raw = (script.string or script.get_text() or '').strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            candidates = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and '@graph' in data:
                graph = data.get('@graph')
                if isinstance(graph, list):
                    candidates = graph
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                type_name = str(item.get('@type') or '')
                if type_name in ('TVSeries', 'Movie', 'TVEpisode'):
                    return item
        return {}

    def _extract_torrent_items(self, doc: BeautifulSoup) -> List[Dict]:
        page_html = self._get_fetched_html() or str(doc)
        items = self._parse_rsc_torrents(page_html)

        if not items:
            for link in doc.select(SITE.seletores["links_magnet"]):
                href = html.unescape((link.get('href') or '').strip())
                magnet = self._resolve_link(href)
                if magnet and magnet.startswith('magnet:'):
                    items.append(self._item_from_magnet(magnet))

        if not items:
            for match in _RE_MAGNET.findall(page_html):
                magnet = html.unescape(match)
                if magnet.startswith('magnet:'):
                    items.append(self._item_from_magnet(magnet))

        deduped: List[Dict] = []
        seen: set = set()
        for item in items:
            info_hash = (item.get('info_hash') or '').lower()
            if not info_hash or info_hash in seen:
                continue
            seen.add(info_hash)
            deduped.append(item)
        return deduped

    def _parse_rsc_torrents(self, page_html: str) -> List[Dict]:
        from utils.parsing import determine_legend_info

        text = self._unescape_rsc_text(page_html)
        items: List[Dict] = []
        seen: set = set()
        for match in _RE_INFO_HASH.finditer(text):
            info_hash = match.group(1).lower()
            if info_hash in seen:
                continue
            seen.add(info_hash)
            next_match = _RE_INFO_HASH.search(text, match.end())
            end = next_match.start() if next_match else min(len(text), match.start() + 20000)
            blob = text[match.start():end]
            raw_title = self._json_string_field(blob, 'rawTitle')
            magnet_url = self._json_string_field(blob, 'magnetUrl')
            quality = self._json_string_field(blob, 'quality')
            audio_codec = self._json_string_field(blob, 'audioCodec')
            uploaded_at = self._json_string_field(blob, 'uploadedAt')
            size_bytes = self._json_int_field(blob, 'sizeBytes')
            seeders = self._json_int_field(blob, 'seeders')
            leechers = self._json_int_field(blob, 'leechers')
            season = self._json_int_field(blob, 'season')
            episode = self._json_int_field(blob, 'episode')
            languages = self._json_str_list_field(blob, 'languages')
            subtitle_languages = self._json_str_list_field(blob, 'subtitleLanguages')
            audio_track_langs = self._json_nested_lang_field(blob, 'audioTracks')
            subtitle_track_langs = self._json_nested_lang_field(blob, 'subtitleTracks')
            if audio_track_langs:
                languages = list(dict.fromkeys(list(languages) + audio_track_langs))
            if subtitle_track_langs:
                subtitle_languages = list(dict.fromkeys(list(subtitle_languages) + subtitle_track_langs))

            magnet = ''
            if magnet_url and magnet_url.startswith('magnet:'):
                magnet = html.unescape(magnet_url)
            else:
                magnet = self._magnet_from_hash(info_hash, raw_title)

            date = None
            if uploaded_at:
                try:
                    date = datetime.fromisoformat(uploaded_at.replace('Z', '+00:00')).replace(tzinfo=None)
                except ValueError:
                    date = None

            audio_labels = self._audio_labels(languages, audio_codec)
            legend_labels = self._legend_labels(subtitle_languages)
            has_pt_br_audio = self._has_pt_br_audio(languages, raw_title)
            has_pt_subs = self._has_pt_subs(subtitle_languages, raw_title)
            audio_html = ''
            if audio_labels:
                audio_html += f"Áudio: {audio_labels} "
            if legend_labels:
                audio_html += f"Legenda: {legend_labels}"
            if quality:
                audio_html += f" Qualidade: {quality}"

            audio_info = self._audio_info_from_languages(languages)
            if has_pt_br_audio and 'português' not in audio_info:
                audio_info = ('português ' + audio_info).strip()
            if has_pt_subs and not has_pt_br_audio:
                if 'legendado' not in audio_info:
                    audio_info = (audio_info + ' legendado').strip()
                if not legend_labels:
                    audio_html = (audio_html + ' Legenda: Português').strip()
            legend_info = determine_legend_info(
                legend_labels or ('legendado' if has_pt_subs else '')
            )

            items.append({
                'info_hash': info_hash,
                'magnet': magnet,
                'raw_title': raw_title,
                'size': format_bytes(size_bytes) if size_bytes else '',
                'seeders': seeders or 0,
                'leechers': leechers or 0,
                'season': season,
                'episode': episode,
                'date': date,
                'audio_info': audio_info,
                'audio_html': audio_html.strip(),
                'legend_info': legend_info,
                'languages': languages,
                'subtitle_languages': subtitle_languages,
                'has_pt_br_audio': has_pt_br_audio,
                'has_pt_subs': has_pt_subs,
                'quality': quality,
            })
        return items

    @staticmethod
    def _unescape_rsc_text(page_html: str) -> str:
        text = html.unescape(page_html or '')
        for _ in range(2):
            if '\\"' not in text:
                break
            text = text.replace('\\"', '"')
        return text

    @staticmethod
    def _json_string_field(blob: str, key: str) -> str:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"(.*?)"', blob)
        if match:
            return html.unescape(match.group(1)).replace('\\/', '/')
        match_null = re.search(rf'"{re.escape(key)}"\s*:\s*null', blob)
        if match_null:
            return ''
        return ''

    @staticmethod
    def _json_int_field(blob: str, key: str) -> Optional[int]:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"?(\d+)"?', blob)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json_str_list_field(blob: str, key: str) -> List[str]:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', blob)
        if not match:
            return []
        return [token.lower() for token in _RE_LANG_TOKEN.findall(match.group(1))]

    @staticmethod
    def _json_nested_lang_field(blob: str, key: str) -> List[str]:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*(\[.*?\]|null)', blob, re.DOTALL)
        if not match or match.group(1) == 'null':
            return []
        return [token.lower() for token in re.findall(r'"lang"\s*:\s*"([^"]+)"', match.group(1))]

    def _item_from_magnet(self, magnet: str) -> Dict:
        info_hash = ''
        try:
            from magnet.parser import MagnetParser
            parsed = MagnetParser.parse(magnet)
            info_hash = parsed.get('info_hash') or ''
        except Exception:
            hash_match = re.search(r'btih:([a-fA-F0-9]{40})', magnet, re.I)
            if hash_match:
                info_hash = hash_match.group(1)
        return {
            'info_hash': info_hash.lower(),
            'magnet': magnet,
            'raw_title': '',
            'size': '',
            'seeders': 0,
            'leechers': 0,
            'season': None,
            'episode': None,
            'date': None,
            'audio_info': '',
            'audio_html': '',
            'legend_info': None,
            'languages': [],
            'subtitle_languages': [],
            'has_pt_br_audio': False,
            'has_pt_subs': False,
            'quality': '',
        }

    @staticmethod
    def _magnet_from_hash(info_hash: str, name: str = '') -> str:
        magnet = f"magnet:?xt=urn:btih:{info_hash.lower()}"
        if name:
            magnet += f"&dn={quote(name, safe='')}"
        return magnet

    @staticmethod
    def _audio_labels(languages: List[str], audio_codec: str) -> str:
        labels: List[str] = []
        codec = (audio_codec or '').lower()
        langs = [str(lang).lower() for lang in languages or []]
        if codec in ('dual-audio', 'dual') or 'dual' in langs:
            labels.append('Dual')
        for lang in langs:
            label = _LANG_AUDIO_LABELS.get(lang) or _LANG_AUDIO_LABELS.get(lang.split('-', 1)[0])
            if label and label not in labels:
                labels.append(label)
        return ' '.join(labels)

    @staticmethod
    def _legend_labels(subtitle_languages: List[str]) -> str:
        labels: List[str] = []
        for lang in subtitle_languages or []:
            low = str(lang).lower()
            if low.startswith('pt'):
                if 'Português' not in labels:
                    labels.append('Português')
            elif low.startswith('en'):
                if 'Inglês' not in labels:
                    labels.append('Inglês')
        return ', '.join(labels)

    @staticmethod
    def _normalize_lang(code: str) -> str:
        return str(code or '').strip().lower().replace('_', '-')

    @classmethod
    def _has_pt_br_audio(cls, languages: List[str], raw_title: str) -> bool:
        for lang in languages or []:
            normalized = cls._normalize_lang(lang)
            compact = normalized.replace('-', '')
            if normalized in _PT_BR_AUDIO_CODES or compact in _PT_BR_AUDIO_CODES:
                return True
        return bool(_RE_DUBLADO_TITLE.search(raw_title or ''))

    @classmethod
    def _audio_info_from_languages(cls, languages: List[str]) -> str:
        parts: List[str] = []
        langs = [cls._normalize_lang(lang) for lang in languages or []]
        if any(
            lang in _PT_BR_AUDIO_CODES or lang.replace('-', '') in _PT_BR_AUDIO_CODES
            for lang in langs
        ):
            parts.append('português')
        if any(lang == 'en' or lang.startswith('en-') for lang in langs):
            parts.append('inglês')
        if any(lang in ('ja', 'jp') or lang.startswith('ja-') for lang in langs):
            parts.append('japonês')
        return ' '.join(parts)

    @classmethod
    def _has_pt_subs(cls, subtitle_languages: List[str], raw_title: str) -> bool:
        for lang in subtitle_languages or []:
            normalized = cls._normalize_lang(lang)
            if normalized == 'pt' or normalized.startswith('pt-'):
                return True
        return bool(_RE_PT_SUB_TITLE.search(raw_title or ''))

    @staticmethod
    def _item_matches_quality(item: Dict, wanted: str) -> bool:
        quality = str(item.get('quality') or '').strip().lower()
        if quality == wanted or quality.replace('p', '') == wanted.replace('p', ''):
            return True
        raw_title = str(item.get('raw_title') or '').lower()
        return wanted.lower() in raw_title

    def _filter_items_by_query(
        self,
        items: List[Dict],
        quality_filter: Optional[str] = None,
    ) -> List[Dict]:
        query = self._active_search_query or ''
        from utils.text import extract_query_season
        season = extract_query_season(query)
        episode = self._extract_query_episode(query)

        filtered = items
        if episode is not None:
            filtered = [
                item for item in filtered
                if item.get('episode') == episode and (
                    season is None or item.get('season') == season
                )
            ]
        elif season is not None:
            filtered = [
                item for item in filtered
                if item.get('season') == season
            ]

        filtered = [
            item for item in filtered
            if item.get('has_pt_br_audio') or item.get('has_pt_subs')
        ]

        if quality_filter:
            wanted = quality_filter.strip().lower()
            filtered = [
                item for item in filtered
                if self._item_matches_quality(item, wanted)
            ]

        filtered.sort(key=lambda item: int(item.get('seeders') or 0), reverse=True)
        if len(filtered) > _MAX_TORRENTS_PER_PAGE:
            filtered = filtered[:_MAX_TORRENTS_PER_PAGE]
        return filtered
