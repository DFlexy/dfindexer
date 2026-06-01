# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
import base64
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import urlparse, parse_qs, urljoin
from bs4 import BeautifulSoup, Tag
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("XFilmes", logger)

_INFO_STOPS = (
    'IMDb', 'Ano de Lançamento', 'Ano de Lancamento', 'Gênero', 'Genero',
    'Formato', 'Qualidade', 'Idioma', 'Legenda', 'Tamanho', 'Duração',
    'Duracao', 'Servidor', 'Qualidade Áudio', 'Filme:', 'Série:', 'Serie:',
)

_FILMES_SECTION = (
    'Últimos Filmes Adicionados',
    'Ultimos Filmes Adicionados',
    'Últimos Filmes',
    'Ultimos Filmes',
)
_SERIES_SECTION = (
    'Últimas Séries Adicionadas',
    'Ultimas Series Adicionadas',
    'Últimas Séries',
    'Ultimas Series',
)
_LEGACY_COMBINED_SECTION = (
    'Últimos Filmes e Séries',
    'Ultimos Filmes e Series',
)

_SKIP_H2_TEXT = (
    'categorias', 'buscas recentes', 'populares', 'pesquisa em alta',
    'resultados para', 'filmes e séries', 'voltar para', 'como baixar',
    'página de pedidos', 'dual áudio', 'trailer', 'relacionados',
)


class XFilmesScraper(BaseScraper):
    SCRAPER_TYPE = "xfilmes"
    DEFAULT_BASE_URL = "https://www.xbrtorrent.net/"
    DISPLAY_NAME = "XFilmes"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"

    def _is_content_url(self, href: str) -> bool:
        if not href or href.startswith('#') or href.startswith('mailto:'):
            return False
        lower = href.lower()
        if any(x in lower for x in ('telegram', 'facebook', 'twitter', 'instagram', 'whatsapp')):
            return False
        absolute = urljoin(self.base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc and parsed.netloc.replace('www.', '') not in urlparse(self.base_url).netloc.replace('www.', ''):
            return False
        path = (parsed.path or '').lower().rstrip('/')
        if not path or path in ('', '/'):
            return False
        skip_paths = (
            '/filmes/', '/series/', '/720p/', '/1080p/', '/4k/',
            '/categoria/', '/tag/', '/page/', '/author/', '/wp-',
            '/como-baixar', '/pedidos', '/buscar',
        )
        if any(path.startswith(p) or p in path for p in skip_paths):
            return False
        if '?s=' in absolute or '/search' in path:
            return False
        return True

    def _append_link(self, links: List[str], href: str) -> None:
        if not href or not self._is_content_url(href):
            return
        absolute_url = urljoin(self.base_url, href)
        if absolute_url not in links:
            links.append(absolute_url)

    def _should_skip_h2(self, text: str) -> bool:
        lower = (text or '').lower().strip()
        if not lower or len(lower) < 3:
            return True
        return any(k in lower for k in _SKIP_H2_TEXT)

    def _link_from_h2(self, h2: Tag) -> Optional[str]:
        link = h2.find('a', href=True)
        if link:
            return link.get('href')
        parent_link = h2.find_parent('a', href=True)
        if parent_link:
            return parent_link.get('href')
        return None

    def _extract_legacy_post_links(self, doc: BeautifulSoup) -> List[str]:
        links: List[str] = []
        for item in doc.select('.post'):
            link_elem = item.select_one('div.title > a') or item.select_one('div.thumb > a')
            if link_elem:
                self._append_link(links, link_elem.get('href', ''))
        return links

    def _normalize_section_text(self, text: str) -> str:
        return ' '.join((text or '').split())

    def _section_title_matches(self, text: str, section_markers: tuple) -> bool:
        normalized = self._normalize_section_text(text)
        return any(marker in normalized for marker in section_markers)

    def _extract_grid_section_links(self, doc: BeautifulSoup, section_markers: tuple) -> List[str]:
        """
        Layout xbr-home-v6: h1.section-title + div.grid > article.card > a[href].
        """
        links: List[str] = []
        for h1 in doc.find_all('h1', class_='section-title'):
            if not self._section_title_matches(h1.get_text(), section_markers):
                continue
            grid = h1.find_next_sibling('div', class_='grid')
            if not grid:
                continue
            for card in grid.select('article.card'):
                anchor = card.find('a', href=True)
                if anchor:
                    self._append_link(links, anchor.get('href', ''))
        return links

    def _extract_h2_section_links(self, doc: BeautifulSoup, section_markers: tuple) -> List[str]:
        """Fallback: percorre h1/h2 e usa link no h2 ou no <a> ancestral."""
        links: List[str] = []
        collecting = False

        for tag in doc.find_all(['h1', 'h2']):
            text = self._normalize_section_text(tag.get_text())
            if self._section_title_matches(text, section_markers):
                collecting = True
                continue
            if not collecting or tag.name != 'h2':
                if collecting and tag.name == 'h1' and not self._section_title_matches(text, section_markers):
                    collecting = False
                continue
            if self._should_skip_h2(text):
                continue
            href = self._link_from_h2(tag)
            if href:
                self._append_link(links, href)

        return links

    def _extract_search_h2_links(self, doc: BeautifulSoup) -> List[str]:
        links: List[str] = []
        in_results = False

        for tag in doc.find_all(['h1', 'h2']):
            text = tag.get_text(strip=True).lower()
            if 'resultado' in text and 'para' in text:
                in_results = True
                continue
            if not in_results or tag.name != 'h2':
                continue
            if self._should_skip_h2(tag.get_text(strip=True)):
                continue
            href = self._link_from_h2(tag)
            if href:
                self._append_link(links, href)

        if not links:
            for h2 in doc.find_all('h2'):
                if self._should_skip_h2(h2.get_text(strip=True)):
                    continue
                href = self._link_from_h2(h2)
                if href:
                    self._append_link(links, href)

        return links

    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = self._extract_search_h2_links(doc)
        if not links:
            links = self._extract_legacy_post_links(doc)
        return [urljoin(self.base_url, u) if not u.startswith('http') else u for u in links]

    def _collect_search_result_titles(self, doc: BeautifulSoup) -> Dict[str, str]:
        title_by_url = super()._collect_search_result_titles(doc)
        for h2 in doc.find_all('h2'):
            link_elem = h2.find('a', href=True) or h2.find_parent('a', href=True)
            if not link_elem:
                continue
            href = (link_elem.get('href') or '').strip()
            title_text = h2.get_text(strip=True) or link_elem.get_text(strip=True)
            normalized = self._normalize_search_result_url(href)
            if normalized and title_text and normalized not in title_by_url:
                title_by_url[normalized] = title_text
        return title_by_url

    def search(
        self,
        query: str,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        skip_trackers: bool = False,
        skip_metadata: bool = False,
    ) -> List[Dict]:
        return self._default_search(
            query, filter_func, skip_trackers=skip_trackers, skip_metadata=skip_metadata
        )
    
    def _extract_legacy_combined_links(self, doc: BeautifulSoup) -> List[str]:
        """Layout antigo: bloco único 'Últimos Filmes e Séries' com div.post."""
        links: List[str] = []
        ultimos_h2 = None
        for h2 in doc.find_all('h2'):
            h2_text = h2.get_text()
            if any(marker in h2_text for marker in _LEGACY_COMBINED_SECTION):
                ultimos_h2 = h2
                break

        if not ultimos_h2:
            return links

        main_title_container = ultimos_h2.find_parent('div', class_='main_title')
        post_list_container = None
        if main_title_container:
            post_list_container = main_title_container.find_parent('div', class_='post_list')

        if post_list_container and main_title_container:
            row_container = main_title_container.find_next_sibling('div', class_='row')
            if row_container:
                for post in row_container.select('div.post'):
                    link_elem = post.select_one('div.title > a') or post.select_one('div.thumb > a')
                    if link_elem:
                        self._append_link(links, link_elem.get('href', ''))

            if not links:
                current = main_title_container.find_next_sibling()
                while current:
                    classes = current.get('class', []) or []
                    if current.name == 'div' and any(
                        c in classes for c in ('post_list', 'main_title', 'pagination')
                    ):
                        break
                    if current.name == 'div' and 'post' in classes:
                        link_elem = current.select_one('div.title > a') or current.select_one('div.thumb > a')
                        if link_elem:
                            self._append_link(links, link_elem.get('href', ''))
                    for post in current.select('div.post'):
                        link_elem = post.select_one('div.title > a') or post.select_one('div.thumb > a')
                        if link_elem:
                            self._append_link(links, link_elem.get('href', ''))
                    current = current.find_next_sibling()

        if not links:
            for post in ultimos_h2.find_all_next('div', class_='post'):
                link_elem = post.select_one('div.title > a') or post.select_one('div.thumb > a')
                if link_elem:
                    self._append_link(links, link_elem.get('href', ''))

        return links

    def _split_links_filmes_series(self, links: List[str]) -> Tuple[List[str], List[str]]:
        """Divide lista mista: séries costumam ter 'temporada' no título/URL."""
        filmes: List[str] = []
        series: List[str] = []
        for url in links:
            lower = url.lower()
            if 'temporada' in lower or re.search(r'/\d{1,2}a-temporada', lower):
                series.append(url)
            else:
                filmes.append(url)
        return filmes, series

    def _extract_links_from_page(self, doc: BeautifulSoup) -> Tuple[List[str], List[str]]:
        filmes_links = self._extract_grid_section_links(doc, _FILMES_SECTION)
        series_links = self._extract_grid_section_links(doc, _SERIES_SECTION)

        if not filmes_links:
            filmes_links = self._extract_h2_section_links(doc, _FILMES_SECTION)
        if not series_links:
            series_links = self._extract_h2_section_links(doc, _SERIES_SECTION)

        if not filmes_links and not series_links:
            combined = self._extract_legacy_combined_links(doc)
            if combined:
                filmes_links, series_links = self._split_links_filmes_series(combined)
            else:
                _log_ctx.info("Seções de filmes/séries não encontradas - fallback .post")
                fallback: List[str] = []
                for href in self._extract_legacy_post_links(doc):
                    self._append_link(fallback, href)
                if fallback:
                    filmes_links, series_links = self._split_links_filmes_series(fallback)

        return filmes_links, series_links

    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items, is_test=is_test)

        try:
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel,
            )
            page_url = build_page_url(self.base_url, self.page_pattern, page)

            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []

            filmes_links, series_links = self._extract_links_from_page(doc)
            effective_max = get_effective_max_items(max_items)

            if effective_max > 0:
                half_limit = max(1, effective_max // 2)
                filmes_links = limit_list(filmes_links, half_limit)
                series_links = limit_list(series_links, half_limit)
                _log_ctx.info(
                    f"Limite configurado: {effective_max} - "
                    f"Coletando {len(filmes_links)} filmes e {len(series_links)} séries"
                )
                links = filmes_links + series_links
            else:
                links = filmes_links + series_links

            all_torrents = process_links_parallel(
                links,
                self._get_torrents_from_page,
                None,
                scraper_name=self.SCRAPER_TYPE,
                use_flaresolverr=self.use_flaresolverr,
            )

            return self.enrich_torrents(
                all_torrents,
                skip_metadata=skip_metadata,
                skip_trackers=skip_trackers,
            )
        finally:
            self._skip_metadata = False

    def _find_content_root(self, doc: BeautifulSoup) -> Optional[Tag]:
        return (
            doc.find('article')
            or doc.find('main')
            or doc.select_one('.single-post, .post-single, .entry-content, .content-area')
        )

    def _extract_labeled_value(self, source: str, label: str) -> str:
        if not source:
            return ''
        stops_pattern = '|'.join(re.escape(s) for s in _INFO_STOPS if s != label)
        patterns = [
            rf'(?is)<strong>\s*{re.escape(label)}\s*:?\s*</strong>\s*([^<]+)',
            rf'(?is)<b>\s*{re.escape(label)}\s*:?\s*</b>\s*([^<]+)',
            rf'(?is){re.escape(label)}\s*:\s*(.+?)(?=\s*(?:{stops_pattern})\s*:|$)',
        ]
        for pattern in patterns:
            match = re.search(pattern, source)
            if match:
                value = match.group(1).strip()
                value = re.sub(r'<[^>]+>', '', value)
                value = html.unescape(value)
                value = re.sub(r'\s+', ' ', value).strip()
                value = value.rstrip(' .,:;')
                if value:
                    return value
        return ''

    def _extract_idioma_from_root(self, root: Tag) -> str:
        root_html = str(root)
        idioma = self._extract_labeled_value(root_html, 'Idioma')
        if idioma:
            return idioma
        root_text = root.get_text(' ', strip=True)
        match = re.search(
            r'(?i)Idioma\s*:\s*([^|]+(?:\|[^|]+)?)(?=\s*(?:Legenda|Tamanho|Qualidade|Servidor|Formato)|$)',
            root_text,
        )
        return match.group(1).strip() if match else ''

    def _audio_info_from_idioma(self, idioma: str) -> Optional[str]:
        if not idioma:
            return None
        idioma_lower = idioma.lower()
        idiomas_detectados = []
        if 'português' in idioma_lower or 'portugues' in idioma_lower:
            idiomas_detectados.append('português')
        if 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower:
            idiomas_detectados.append('inglês')
        if 'japonês' in idioma_lower or 'japones' in idioma_lower or 'japanese' in idioma_lower or 'jap' in idioma_lower:
            idiomas_detectados.append('japonês')
        idiomas_detectados = idiomas_detectados[:3]
        if len(idiomas_detectados) >= 2:
            if 'português' in idiomas_detectados and 'inglês' in idiomas_detectados:
                return 'dual'
            if 'português' in idiomas_detectados:
                return 'dual'
            return idiomas_detectados[0]
        if len(idiomas_detectados) == 1:
            return idiomas_detectados[0]
        return None

    def _collect_magnet_links(self, doc: BeautifulSoup, article: Tag) -> List[str]:
        magnet_links: List[str] = []
        containers = []
        for sel in ('div.content', 'div.entry-content', '.left', 'div.modal-downloads', 'div#modal-downloads'):
            containers.extend(article.select(sel) if article else [])
        if article and article not in containers:
            containers.append(article)

        def try_href(href: str, original_href: Optional[str] = None) -> None:
            if not href:
                return
            resolved_magnet = self._resolve_link(href)
            if not resolved_magnet or not resolved_magnet.startswith('magnet:'):
                if 'token=' in href:
                    try:
                        parsed = urlparse(href)
                        params = parse_qs(parsed.query)
                        token = params.get('token', [None])[0]
                        if token:
                            decoded = base64.b64decode(token).decode('utf-8')
                            if decoded.startswith('magnet:'):
                                resolved_magnet = decoded
                    except Exception:
                        pass
            if not resolved_magnet or not resolved_magnet.startswith('magnet:'):
                return
            orig = original_href or href
            if 'protlink=' in orig:
                try:
                    magnet_data = MagnetParser.parse(resolved_magnet)
                    trackers = magnet_data.get('trackers', [])
                    if not trackers:
                        from tracker.list_provider import TrackerListProvider
                        tracker_provider = TrackerListProvider(redis_client=self.redis)
                        default_trackers = tracker_provider.get_trackers()
                        if default_trackers:
                            from urllib.parse import urlencode
                            magnet_params = {'xt': f"urn:btih:{magnet_data.get('info_hash', '')}"}
                            display_name = magnet_data.get('display_name', '')
                            if display_name and display_name.strip():
                                magnet_params['dn'] = display_name
                            for tracker in default_trackers[:5]:
                                magnet_params.setdefault('tr', []).append(tracker)
                            resolved_magnet = f"magnet:?{urlencode(magnet_params, doseq=True)}"
                except Exception:
                    pass
            if resolved_magnet not in magnet_links:
                magnet_links.append(resolved_magnet)

        seen_hrefs = set()
        for text_content in containers:
            for a in text_content.select('a[href]'):
                href = a.get('href', '')
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                try_href(href, href)

        if not magnet_links:
            for a in doc.select('a[href]'):
                href = a.get('href', '')
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                try_href(href, href)

        return magnet_links
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        article = self._find_content_root(doc)
        if not article:
            return []
        
        root_html = str(article)
        root_text = article.get_text(' ', strip=True)

        original_title = self._extract_labeled_value(root_html, 'Titulo Original')
        if not original_title:
            original_title = self._extract_labeled_value(root_html, 'Título Original')

        title_translated_processed = self._extract_labeled_value(root_html, 'Titulo Traduzido')
        if not title_translated_processed:
            title_translated_processed = self._extract_labeled_value(root_html, 'Título Traduzido')

        entry_content = article.select_one('div.content, div.entry-content, .left')
        if entry_content:
            html_content = str(entry_content)
            if not original_title:
                original_title = self._extract_labeled_value(html_content, 'Titulo Original') or self._extract_labeled_value(
                    html_content, 'Título Original'
                )
            if not title_translated_processed:
                title_translated_processed = self._extract_labeled_value(html_content, 'Titulo Traduzido') or self._extract_labeled_value(
                    html_content, 'Título Traduzido'
                )
        
        if not original_title:
            title_raw = article.find('h1', class_='entry-title') or article.find('h1')
            if title_raw:
                original_title = title_raw.get_text(strip=True)
                original_title = re.sub(r'\s*\(\d{4}(-\d{4})?\)\s*$', '', original_title)
        
        for suffix in (' Torrent Dual Áudio', ' Torrent Dublado', ' Torrent Legendado', ' Torrent'):
            original_title = original_title.replace(suffix, '').strip()
        
        if not title_translated_processed:
            title_raw = article.find('h1', class_='entry-title') or article.find('h1')
            if title_raw:
                title_translated_processed = title_raw.get_text(strip=True)
        
        if title_translated_processed:
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            title_translated_processed = html.unescape(title_translated_processed)
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        title = original_title
        
        year = ''
        imdb = ''
        sizes = []
        audio_info = None
        audio_html_content = ''
        all_paragraphs_html = []
        
        entry_meta_list = doc.find_all('div', class_='entry-meta')
        
        idioma = ''
        legenda = ''
        
        for entry_meta in entry_meta_list:
            all_paragraphs_html.append(str(entry_meta))
        
        for entry_meta in entry_meta_list:
            entry_meta_html = str(entry_meta)
            
            if not idioma:
                idioma_match = re.search(r'(?i)<b>Idioma:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', entry_meta_html, re.DOTALL)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                else:
                    idioma_match = re.search(r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', entry_meta_html, re.DOTALL)
                    if idioma_match:
                        idioma = idioma_match.group(1).strip()
                if idioma:
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                    idioma = re.sub(r'\s+', ' ', idioma).strip()
            
            if idioma:
                break

        if not idioma:
            idioma = self._extract_idioma_from_root(article)
        
        from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
        legenda = extract_legenda_from_page(doc, scraper_type='xfilmes', entry_meta_list=entry_meta_list)
        
        legend_info = determine_legend_info(legenda) if legenda else None
        
        audio_info = self._audio_info_from_idioma(idioma)
        
        for p in article.select('div.content p, div.entry-content p, p'):
            html_content = str(p)
            all_paragraphs_html.append(html_content)
        
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
            if legenda and 'Legenda' not in audio_html_content and 'legenda' not in audio_html_content.lower():
                audio_html_content += f' Legenda: {legenda}'
        
        if not audio_info:
            for p in article.select('div.content p, div.entry-content p, p'):
                text = p.get_text()
                html_content = str(p)
                
                y = find_year_from_text(text, title)
                if y:
                    year = y
                
                sizes.extend(find_sizes_from_text(html_content))
                
                from utils.parsing.audio_extraction import detect_audio_from_html
                audio_info = detect_audio_from_html(html_content)
                if audio_info:
                    break
        else:
            for p in article.select('div.entry-meta, div.content p, div.entry-content p, p'):
                text = p.get_text()
                html_content = str(p)
                
                y = find_year_from_text(text, title)
                if y:
                    year = y
                
                sizes.extend(find_sizes_from_text(html_content))
        
        sizes = list(dict.fromkeys(sizes))
        
        if not year:
            year_match = re.search(
                r'(?i)Ano de Lançamento\s*:\s*((?:19|20)\d{2})',
                root_text,
            )
            if year_match:
                year = year_match.group(1)
        
        if not year:
            try:
                year_match = re.search(r'(?i)Lançamento\s*:?\s*((?:19|20)\d{2})', root_text)
                if year_match:
                    year = year_match.group(1)
                else:
                    article_full_text = article.get_text(' ', strip=True)
                    year_match = re.search(r'(19|20)\d{2}', article_full_text)
                    if year_match:
                        year = year_match.group(0)
            except Exception:
                pass

        imdb = ''
        for a in article.select('a[href*="imdb.com"]'):
            href = a.get('href', '')
            imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
            if imdb_match:
                imdb = imdb_match.group(1)
                break
            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
            if imdb_match:
                imdb = imdb_match.group(1)
                break

        magnet_links = self._collect_magnet_links(doc, article)
        
        if not magnet_links:
            return []
        
        if self._skip_metadata:
            magnet_links = magnet_links[:1]
        
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
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
                
                magnet_original = magnet_data.get('display_name', '') or ''
                missing_dn = not magnet_original or len(magnet_original.strip()) < 3
                
                if not missing_dn and magnet_original:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, magnet_original)
                    except Exception:
                        pass
                
                fallback_title = title
                working_release_title = magnet_original if not missing_dn else ''
                
                original_release_title = prepare_release_title(
                    working_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                if missing_dn:
                    has_season_ep_info = re.search(r'(?i)S\d{1,2}(?:E\d{1,2}(?:-\d{1,2})?)?', original_release_title)
                    if not has_season_ep_info and 'temporada' not in original_release_title.lower():
                        try:
                            article_text_cached = article.get_text(' ', strip=True).lower()
                            season_match = re.search(r'(\d+)\s*(?:ª|a)?\s*temporada', article_text_cached)
                            if season_match:
                                season_number = season_match.group(1)
                                if not re.search(rf'\b{season_number}\s*(?:ª|a)?\s*temporada', original_release_title, re.IGNORECASE):
                                    original_release_title = f"{original_release_title} temporada {season_number}"
                        except Exception:
                            pass
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title, title_translated_html=title_translated_processed if title_translated_processed else None, magnet_original=magnet_original
                )
                
                final_title = add_audio_tag_if_needed(
                    standardized_title, 
                    original_release_title, 
                    info_hash=info_hash, 
                    skip_metadata=self._skip_metadata,
                    audio_info_from_html=audio_info,
                    audio_html_content=audio_html_content
                )
                
                origem_audio_tag = 'N/A'
                if audio_info:
                    origem_audio_tag = 'HTML da página (Idioma/Legenda)'
                elif magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                trackers = process_trackers(magnet_data)
                
                if not trackers:
                    try:
                        from tracker.list_provider import TrackerListProvider
                        tracker_provider = TrackerListProvider(redis_client=self.redis)
                        dynamic_trackers = tracker_provider.get_trackers()
                        if dynamic_trackers:
                            trackers = [t for t in dynamic_trackers if t.lower().startswith('udp://')]
                    except Exception:
                        pass
                
                from utils.parsing.legend_extraction import determine_legend_presence
                has_legenda = determine_legend_presence(
                    legend_info_from_html=legend_info,
                    audio_html_content=audio_html_content,
                    magnet_processed=original_release_title,
                    info_hash=info_hash,
                    skip_metadata=self._skip_metadata
                )
                
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
                    cross_data_to_save = {
                        'title_original_html': original_title if original_title else None,
                        'magnet_processed': original_release_title if original_release_title else None,
                        'magnet_original': magnet_original if magnet_original else None,
                        'title_translated_html': title_translated_processed if title_translated_processed else None,
                        'imdb': imdb if imdb else None,
                        'missing_dn': missing_dn,
                        'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None,
                        'size': size if size and size.strip() else None,
                        'has_legenda': has_legenda,
                        'legend': legend_info if legend_info else None
                    }
                    save_cross_data_to_redis(info_hash, cross_data_to_save)
                except Exception:
                    pass
                
                torrent = {
                    'title_processed': final_title,
                    'original_title': original_title if original_title else title,
                    'title_translated_processed': title_translated_processed if title_translated_processed else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb,
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
                    'info_hash': info_hash,
                    'trackers': trackers,
                    'size': size,
                    'leech_count': 0,
                    'seed_count': 0,
                    'similarity': 1.0,
                    'magnet_original': magnet_original if magnet_original else None,
                    'legend': legend_info if legend_info else None,
                    'has_legenda': has_legenda
                }
                torrents.append(torrent)
            
            except Exception as e:
                _log_ctx.error_magnet(magnet_link, e)
                continue
        
        return torrents
