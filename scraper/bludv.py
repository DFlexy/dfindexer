# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from utils.text.constants import STOP_WORDS
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("Bludv", logger)

class BludvScraper(BaseScraper):
    SCRAPER_TYPE = "bludv"
    DEFAULT_BASE_URL = "https://bludv2.xyz/"
    DISPLAY_NAME = "Bludv"
    USE_FLARESOLVERR_DEFAULT = True
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"

    def _collect_post_links(self, doc: BeautifulSoup) -> List[str]:
        """Extrai links de posts (listagem e busca) — tema WordPress bludv2."""
        links: List[str] = []
        seen: set = set()
        article_selectors = ('article.post', 'article', '.post')
        link_selectors = (
            'header.entry-header h1.entry-title a',
            'h1.entry-title a',
            'header.entry-header a',
            'div.title > a',
            'h2 a',
        )

        for article_sel in article_selectors:
            for item in doc.select(article_sel):
                link_elem = None
                for link_sel in link_selectors:
                    link_elem = item.select_one(link_sel)
                    if link_elem and link_elem.get('href'):
                        break
                if not link_elem:
                    continue
                href = (link_elem.get('href') or '').strip()
                if not href or href.startswith('#'):
                    continue
                if not href.startswith('http'):
                    href = urljoin(self.base_url, href)
                if href not in seen:
                    seen.add(href)
                    links.append(href)
            if links:
                break
        return links

    @staticmethod
    def _query_without_year(query: str) -> str:
        words = query.split()
        if (
            len(words) >= 2
            and words[-1].isdigit()
            and len(words[-1]) == 4
            and words[-1][:2] in ('19', '20')
        ):
            return ' '.join(words[:-1])
        return query

    def _build_search_query_variations(self, query: str) -> List[str]:
        """Variações de busca; WordPress do Bludv falha com frases longas em inglês."""
        variations: List[str] = []
        seen: set = set()

        def add(value: str) -> None:
            text = (value or '').strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                variations.append(text)

        from utils.text.query import strip_stop_words_keep_season

        add(query)

        stripped = strip_stop_words_keep_season(query)
        if stripped:
            add(stripped)

        without_year = self._query_without_year(query)
        if without_year.lower() != query.strip().lower():
            add(without_year)

        shrink_base = strip_stop_words_keep_season(without_year).split()
        if not shrink_base:
            shrink_base = without_year.split()

        while len(shrink_base) >= 2:
            add(' '.join(shrink_base))
            shrink_base = shrink_base[:-1]

        query_words = query.split()
        if len(query_words) > 1 and len(query_words) < 3:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                add(query_words[0])

        return variations

    @staticmethod
    def _is_primary_search_variation(variation: str, query: str) -> bool:
        """Filtro por título do card só na query principal (frases parciais mantêm todos os links)."""
        v = variation.strip().lower()
        q = query.strip().lower()
        if v == q:
            return True
        without_year = BludvScraper._query_without_year(query).strip().lower()
        return v == without_year

    def _search_variations(self, query: str) -> List[str]:
        links: List[str] = []
        seen_urls: set = set()

        for variation in self._build_search_query_variations(query):
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue

            page_links = self._collect_post_links(doc)
            if self._is_primary_search_variation(variation, query):
                page_links = self._filter_links_by_result_titles(doc, page_links, variation)

            for href in page_links:
                absolute_url = urljoin(self.base_url, href)
                if absolute_url not in seen_urls:
                    links.append(absolute_url)
                    seen_urls.add(absolute_url)

        return links
    
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
    
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        return self._collect_post_links(doc)
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        return self._collect_post_links(doc)
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        from urllib.parse import urljoin
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        
        page_title = ''
        title_elem = doc.find('h1')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        original_title = ''
        title_translated_processed = ''
        
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
        if not content_div:
            self._log_structure_miss(absolute_link, 'div.content / div.entry-content / article')
        
        if content_div:
            
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', elem_html):
                    text_parts = elem_text.split('Título Original:')
                    if len(text_parts) > 1:
                        original_title = text_parts[1].strip()
                        
                        html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(.*?)(?:<br|</span|</p|</div|$)', elem_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                original_title = html_text
                        
                        original_title = html.unescape(original_title)
                        original_title = re.sub(r'\s+', ' ', original_title).strip()
                        for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:', 'Título Traduzido:']:
                            if stop in original_title:
                                original_title = original_title.split(stop)[0].strip()
                                break
                        if original_title:
                            break
            
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                if re.search(r'(?i)T[íi]tulo\s+Traduzido\s*:?', elem_html):
                    text_parts = elem_text.split('Título Traduzido:')
                    if len(text_parts) > 1:
                        title_translated_processed = text_parts[1].strip()
                        
                        html_match = re.search(r'(?i)T[íi]tulo\s+Traduzido\s*:?\s*(.*?)(?:<br|</span|</p|</div|$)', elem_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                title_translated_processed = html_text
                        
                        title_translated_processed = html.unescape(title_translated_processed)
                        title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
                        for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:']:
                            if stop in title_translated_processed:
                                title_translated_processed = title_translated_processed.split(stop)[0].strip()
                                break
                        if title_translated_processed:
                            from utils.text.cleaning import clean_title_translated_processed
                            title_translated_processed = clean_title_translated_processed(title_translated_processed)
                            break
        
        if not original_title:
            original_title = page_title
        
        if self._should_skip_page_by_query(
            page_title, original_title, title_translated_processed, absolute_link,
        ):
            return []

        audio_info = None
        audio_html_content = ''
        all_paragraphs_html = []
        
        audio_text = ''
        legenda = ''
        
        year = ''
        sizes = []
        imdb = ''
        
        if content_div:
            content_html = str(content_div)
            all_paragraphs_html.append(content_html)
            
            audio_patterns = [
                r'(?i)Áudio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|$)',
                r'(?i)Audio\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Legenda|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|$)',
                r'(?i)<[^>]*>Áudio\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
                r'(?i)<[^>]*>Audio\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legenda|$)',
            ]
            
            for pattern in audio_patterns:
                audio_match = re.search(pattern, content_html, re.DOTALL)
                if audio_match:
                    audio_text = audio_match.group(1).strip()
                    audio_text = html.unescape(audio_text)
                    audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                    audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                    stop_words = ['Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb']
                    for stop_word in stop_words:
                        if stop_word in audio_text:
                            idx = audio_text.index(stop_word)
                            audio_text = audio_text[:idx].strip()
                            break
                    if audio_text:
                        break
            
            if not audio_text:
                for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                    elem_html = str(elem)
                    all_paragraphs_html.append(elem_html)
                    
                    for pattern in audio_patterns:
                        audio_match = re.search(pattern, elem_html, re.DOTALL)
                        if audio_match:
                            audio_text = audio_match.group(1).strip()
                            audio_text = html.unescape(audio_text)
                            audio_text = re.sub(r'<[^>]+>', '', audio_text).strip()
                            audio_text = re.sub(r'\s+', ' ', audio_text).strip()
                            stop_words = ['Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho', 'IMDb']
                            for stop_word in stop_words:
                                if stop_word in audio_text:
                                    idx = audio_text.index(stop_word)
                                    audio_text = audio_text[:idx].strip()
                                    break
                            if audio_text:
                                break
                    if audio_text:
                        break
            
            from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
            legenda = extract_legenda_from_page(doc, scraper_type='bludv', content_div=content_div)
            
            legend_info = determine_legend_info(legenda) if legenda else None
            
            if all_paragraphs_html:
                audio_html_content = ' '.join(all_paragraphs_html)
                if legenda and 'Legenda' not in audio_html_content and 'legenda' not in audio_html_content.lower():
                    audio_html_content += f' Legenda: {legenda}'
            
            if audio_text:
                from utils.parsing.audio_extraction import detect_audio_from_idioma_text
                audio_info = detect_audio_from_idioma_text(audio_text) or audio_info
        
        if content_div:
            for p in content_div.select('p, span, div'):
                text = p.get_text()
                html_content = str(p)
                
                y = find_year_from_text(text, original_title or page_title)
                if y:
                    year = y
                
                sizes.extend(find_sizes_from_text(html_content))

        from utils.parsing.imdb_extraction import extract_imdb_from_soup
        imdb = extract_imdb_from_soup(
            content_div or article,
            content_div=content_div,
            label_tag='em',
            label_regex=r'IMDb:',
        ) if content_div else extract_imdb_from_soup(article)
        
        all_links = doc.select('a[href]')
        
        magnet_links = []
        for link in all_links:
            href = link.get('href', '')
            if not href:
                continue
            
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:'):
                if resolved_magnet not in magnet_links:
                    magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            return []
        
        sizes = list(dict.fromkeys(sizes))
        
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
            fallback_title_priority='original_first',
            original_title_fallbacks=[title_translated_processed],
            imdb_default='',
        )

