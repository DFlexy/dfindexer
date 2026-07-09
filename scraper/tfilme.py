# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.text.utils import find_year_from_text, find_sizes_from_text
from app.config import Config
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("TFilme", logger)

_TORRENT_LINK_HINTS = (
    'magnet:', 'go.php', 'get.php', '?go=', '&go=', 'protlink', 'systemads',
)
from utils.parsing.field_extraction import extract_labeled_value as _extract_labeled_value
from utils.parsing.field_extraction import extract_labeled_value_from_text as _extract_labeled_value_from_text

_RE_MAGNET_IN_HTML = re.compile(r'magnet:\?[^"\'\s<>]+', re.IGNORECASE)


class TfilmeScraper(BaseScraper):
    SCRAPER_TYPE = "tfilme"
    DEFAULT_BASE_URL = "https://torrentdosfilmes-v2.xyz/"
    DISPLAY_NAME = "TFilme"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "category/dublado/page/{}/"
    
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
    
    def _extract_links_from_page(self, doc: BeautifulSoup) -> Tuple[List[str], List[str]]:
        filmes_links = []
        series_links = []
        
        filmes_h3 = None
        for h3 in doc.find_all('h3'):
            if h3.get_text(strip=True) == 'Últimos Filmes Adicionados':
                filmes_h3 = h3
                break
        
        if filmes_h3:
            title_geral_filmes = filmes_h3.find_parent('div', class_='titleGeral')
            if title_geral_filmes:
                current = title_geral_filmes.find_next_sibling()
                while current:
                    if current.name == 'div' and 'titleGeral' in current.get('class', []):
                        break
                    if current.name == 'div' and 'post' in current.get('class', []) and 'green' in current.get('class', []):
                        link_elem = current.select_one('div.title > a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                filmes_links.append(href)
                    current = current.find_next_sibling()
        
        series_h3 = None
        for h3 in doc.find_all('h3'):
            if h3.get_text(strip=True) == 'Últimas Séries Adicionadas':
                series_h3 = h3
                break
        
        if series_h3:
            title_geral_series = series_h3.find_parent('div', class_='titleGeral')
            if title_geral_series:
                current = title_geral_series.find_next_sibling()
                while current:
                    if current.name == 'div' and 'titleGeral' in current.get('class', []):
                        break
                    if current.name == 'div' and 'post' in current.get('class', []) and 'blue' in current.get('class', []):
                        link_elem = current.select_one('div.title > a')
                        if link_elem:
                            href = link_elem.get('href')
                            if href:
                                series_links.append(href)
                    current = current.find_next_sibling()
        
        return (filmes_links, series_links)

    def _collect_post_links(self, doc: BeautifulSoup) -> Tuple[List[str], List[str]]:
        """Fallback: extrai links de div.post (listagens de categoria e busca)."""
        filmes_links: List[str] = []
        series_links: List[str] = []
        seen: set = set()

        for item in doc.select('div.post'):
            link_elem = item.select_one('div.title > a') or item.select_one('a[href]')
            if not link_elem:
                continue
            href = (link_elem.get('href') or '').strip()
            if not href or href.startswith('#') or href in seen:
                continue
            seen.add(href)
            classes = item.get('class', [])
            if 'blue' in classes:
                series_links.append(href)
            else:
                filmes_links.append(href)

        return (filmes_links, series_links)

    def _is_probable_torrent_link(self, href: str) -> bool:
        href_lower = href.lower()
        return any(hint in href_lower for hint in _TORRENT_LINK_HINTS)

    def _collect_magnet_links(self, doc: BeautifulSoup, article: BeautifulSoup) -> List[str]:
        """Coleta magnets: prioriza links de download, depois varre a página e o HTML bruto."""
        magnet_links: List[str] = []
        seen_hashes: set = set()

        def _add_magnet(magnet: str) -> None:
            if not magnet or not magnet.startswith('magnet:'):
                return
            try:
                key = MagnetParser.parse(magnet)['info_hash'].lower()
            except Exception:
                key = magnet
            if key in seen_hashes:
                return
            seen_hashes.add(key)
            magnet_links.append(magnet)

        def _scan_links(root) -> None:
            candidates = []
            other = []
            for link in root.select('a[href]'):
                href = html.unescape((link.get('href') or '').strip())
                if not href:
                    continue
                if self._is_probable_torrent_link(href):
                    candidates.append(href)
                else:
                    other.append(href)
            for href in candidates + other:
                resolved = self._resolve_link(href)
                if resolved:
                    _add_magnet(resolved)

        text_content = article.find('div', class_='content')
        if text_content:
            _scan_links(text_content)
        if not magnet_links:
            _scan_links(article)
        if not magnet_links:
            _scan_links(doc)

        if not magnet_links:
            page_html = self._get_fetched_html()
            for match in _RE_MAGNET_IN_HTML.findall(page_html or ''):
                _add_magnet(html.unescape(match))

        return magnet_links
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items, is_test=is_test)
        
        try:
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel
            )
            page_url = build_page_url(self.base_url, self.page_pattern, page)
            
            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []
            
            filmes_links, series_links = self._extract_links_from_page(doc)

            if not filmes_links and not series_links:
                filmes_links, series_links = self._collect_post_links(doc)
                if filmes_links or series_links:
                    _log_ctx.info(
                        f"Fallback div.post: {len(filmes_links)} filmes, {len(series_links)} séries"
                    )
            
            effective_max = get_effective_max_items(max_items)
            
            if effective_max > 0:
                half_limit = max(1, effective_max // 2)
                
                filmes_links = limit_list(filmes_links, half_limit)
                series_links = limit_list(series_links, half_limit)
                
                _log_ctx.info(f"Limite configurado: {effective_max} - Coletando {len(filmes_links)} filmes e {len(series_links)} séries")
                links = filmes_links + series_links
            else:
                links = filmes_links + series_links
            
            all_torrents = process_links_parallel(
                links,
                self._get_torrents_from_page,
                None,
                scraper_name=self.SCRAPER_TYPE if hasattr(self, 'SCRAPER_TYPE') else None,
                use_flaresolverr=self.use_flaresolverr
            )
            
            enriched = self.enrich_torrents(
                all_torrents,
                skip_metadata=skip_metadata,
                skip_trackers=skip_trackers
            )
            return enriched
        finally:
            self._skip_metadata = False
            self._is_test = False
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        filmes_links, series_links = self._collect_post_links(doc)
        return filmes_links + series_links
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        article = doc.find('article')
        if not article:
            self._log_structure_miss(absolute_link, 'article')
            return []
        
        page_title = ''
        title_div = article.find('div', class_='title')
        if title_div:
            h1 = title_div.find('h1')
            if h1:
                page_title = h1.get_text(strip=True).replace(' - Download', '')
        
        if not page_title:
            # Layout do título mudou: tenta qualquer h1 da página antes de descartar.
            h1 = article.find('h1') or doc.find('h1')
            if h1:
                page_title = h1.get_text(strip=True).replace(' - Download', '')
        
        if not page_title:
            self._log_structure_miss(absolute_link, 'div.title > h1')
            return []
        
        original_title = ''
        title_labels = ['Título Original', 'Titulo Original']
        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse']
        for content_div in article.select('div.content'):
            html_content = str(content_div)
            original_title = _extract_labeled_value(html_content, title_labels)
            if not original_title:
                original_title = _extract_labeled_value_from_text(
                    content_div.get_text(), title_labels, stop_words
                )
            if original_title:
                break
        
        title_translated_processed = ''
        translated_labels = ['Título Traduzido', 'Titulo Traduzido']
        translated_stop = stop_words + ['Título Original', 'Titulo Original']
        for content_div in article.select('div.content'):
            html_content = str(content_div)
            title_translated_processed = _extract_labeled_value(html_content, translated_labels)
            if not title_translated_processed:
                title_translated_processed = _extract_labeled_value_from_text(
                    content_div.get_text(), translated_labels, translated_stop
                )
            if title_translated_processed:
                title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
                title_translated_processed = html.unescape(title_translated_processed)
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
                break
        
        if self._should_skip_page_by_query(
            page_title, original_title, title_translated_processed, absolute_link,
        ):
            return []

        year = ''
        sizes = []
        audio_info = None
        audio_html_content = ''
        all_paragraphs_html = []
        
        content_div = article.find('div', class_='content')
        idioma = ''
        
        if content_div:
            content_html = str(content_div)
            all_paragraphs_html.append(content_html)
            
            for field_label in ('Idioma', 'Áudio', 'Audio'):
                idioma_match = re.search(
                    rf'(?i)<b>{field_label}\s*:</b>\s*([^<]+?)(?:<br|</div|</p|$)',
                    content_html,
                )
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                    break
            
            if not idioma:
                for field_label in ('Idioma', 'Áudio', 'Audio'):
                    idioma_match = re.search(
                        rf'(?i){field_label}\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)',
                        content_html,
                    )
                    if idioma_match:
                        idioma = idioma_match.group(1).strip()
                        idioma = html.unescape(idioma)
                        idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                        break
        
        if idioma:
            idioma_lower = idioma.lower()
            
            has_portugues_audio = 'português' in idioma_lower or 'portugues' in idioma_lower
            has_ingles = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower
            
            if has_portugues_audio:
                audio_info = 'português'
            elif has_ingles:
                audio_info = 'inglês'
        
        if not audio_info:
            for p in article.select('div.content p'):
                text = p.get_text()
                html_content = str(p)
                all_paragraphs_html.append(html_content)
                y = find_year_from_text(text, page_title)
                if y:
                    year = y
                sizes.extend(find_sizes_from_text(text))
                
                if not audio_info:
                    from utils.parsing.audio_extraction import detect_audio_from_html
                    audio_info = detect_audio_from_html(html_content)
        else:
            for p in article.select('div.content p'):
                text = p.get_text()
                html_content = str(p)
                all_paragraphs_html.append(html_content)
                y = find_year_from_text(text, page_title)
                if y:
                    year = y
                sizes.extend(find_sizes_from_text(text))
        
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        magnet_links = self._collect_magnet_links(doc, article)
        
        if not magnet_links:
            return []
        
        from utils.parsing.imdb_extraction import extract_imdb_from_soup
        content_div = article.find('div', class_='content')
        imdb = extract_imdb_from_soup(article, content_div=content_div)

        sizes = list(dict.fromkeys(sizes))

        from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
        legenda = extract_legenda_from_page(doc, scraper_type='tfilme')
        legend_info = determine_legend_info(legenda) if legenda else None

        from core.builders import build_torrents_from_magnets
        return build_torrents_from_magnets(
            magnet_links=magnet_links,
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
            skip_metadata=self._skip_metadata,
            doc=doc,
            scraper_type=self.SCRAPER_TYPE,
            log_ctx=_log_ctx,
        )

