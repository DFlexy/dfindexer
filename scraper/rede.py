# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, quote_plus, unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from utils.text.constants import STOP_WORDS
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("Rede", logger)

class RedeScraper(BaseScraper):
    SCRAPER_TYPE = "rede"
    DEFAULT_BASE_URL = "https://redetorrent.com/"
    DISPLAY_NAME = "Rede"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "index.php?s="
        self.page_pattern = "{}"
    
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
        links = []
        for item in doc.select('.capa_lista'):
            link_elem = item.select_one('a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.capa_lista'):
            link_elem = item.select_one('a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        return links
    
    def _search_variations(self, query: str) -> List[str]:
        links = []
        seen_urls = set()
        variations = [query]
        
        query_words = query.split()

        if len(query_words) >= 2 and query_words[-1].isdigit() and len(query_words[-1]) == 4 and query_words[-1][:2] in ('19', '20'):
            without_year = ' '.join(query_words[:-1])
            if without_year not in variations:
                variations.append(without_year)

        if len(query_words) > 1 and len(query_words) < 3:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            page = 1
            use_query_format = None
            
            while True:
                if page == 1:
                    search_url = f"{self.base_url}{self.search_url}{quote_plus(variation)}"
                else:
                    if use_query_format is None:
                        break
                    elif use_query_format:
                        search_url = f"{self.base_url}{self.search_url}{quote_plus(variation)}&page={page}"
                    else:
                        query_formatted = variation.lower().replace(' ', '-')
                        search_url = f"{self.base_url}{query_formatted}/{page}/"
                
                doc = self.get_document(search_url, self.base_url)
                if not doc:
                    break
                
                page_links = []
                for item in doc.select('.capa_lista'):
                    link_elem = item.select_one('a')
                    if link_elem:
                        href = link_elem.get('href')
                        if href:
                            page_links.append(href)
                
                if not page_links:
                    break
                
                for link in page_links:
                    absolute_url = urljoin(self.base_url, link) if link and not link.startswith('http') else link
                    if absolute_url not in seen_urls:
                        links.append(absolute_url)
                        seen_urls.add(absolute_url)
                
                if page == 1:
                    pagination_links = doc.select('a[href], .pagination a, .wp-pagenavi a')
                    for pag_link in pagination_links:
                        href = pag_link.get('href', '').lower()
                        if '/2/' in href or '/3/' in href:
                            if 'index.php' not in href and 'page=' not in href:
                                use_query_format = False
                                break
                        elif "page=2" in href or "&page=2" in href or "?page=2" in href:
                            use_query_format = True
                            break
                
                has_next_page = False
                if page == 1 and use_query_format is None:
                    break
                
                pagination_links = doc.select('a[href], .pagination a, .wp-pagenavi a')
                for pag_link in pagination_links:
                    href = pag_link.get('href', '')
                    text = pag_link.get_text(strip=True).lower()
                    
                    if use_query_format:
                        if (f"page={page + 1}" in href) or (f"&page={page + 1}" in href):
                            has_next_page = True
                            break
                    else:
                        if f"/{page + 1}/" in href:
                            has_next_page = True
                            break
                    
                    if text in ['próxima', 'next', '>', '»']:
                        has_next_page = True
                        break
                    try:
                        page_num = int(text)
                        if page_num > page:
                            has_next_page = True
                            break
                    except ValueError:
                        pass
                
                if not has_next_page:
                    break
                
                page += 1

                if page > 20:
                    break
        
        return list(set(links))
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        article = doc.find('div', class_='conteudo')
        if not article:
            self._log_structure_miss(absolute_link, 'div.conteudo')
            return []
        
        h1 = article.find('h1')
        if not h1:
            self._log_structure_miss(absolute_link, 'h1 em div.conteudo')
            return []
        
        title_text = h1.get_text(strip=True)

        title_match = re.search(r'^(.*?)(?: - (.*?))? \((\d{4})\)', title_text)
        if title_match:
            title = title_match.group(1).strip()
            year = title_match.group(3).strip()
        else:
            # Formato "Título (Ano)" mudou: usa o h1 inteiro e tenta só o ano,
            # em vez de descartar a página (o ano ainda pode vir de #informacoes).
            title = title_text.strip()
            year = ''
            year_match = re.search(r'\((\d{4})\)', title_text)
            if year_match:
                year = year_match.group(1)
                title = re.sub(r'\s*\(\d{4}\)\s*', ' ', title).strip()
            if not title:
                self._log_structure_miss(absolute_link, "padrão 'Título (Ano)' no h1")
                return []
        
        original_title = ''
        for p in article.select('div#informacoes > p'):
            html_content = str(p)
            html_content = html_content.replace('\n', '').replace('\t', '')
            html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
            lines = html_content.split('<br>')
            
            for line in lines:
                line = re.sub(r'<[^>]*>', '', line).strip()
                if 'Título Original:' in line:
                    title_regex = re.compile(r'Título Original:\s*([^\n\r]{1,200}?)(?:\s*(?:Gênero|Ano|Duração|Direção|Elenco|Sinopse|$))')
                    match = title_regex.search(line)
                    if match:
                        original_title = match.group(1).strip()
                    else:
                        parts = line.split('Título Original:')
                        if len(parts) > 1:
                            extracted = parts[1].strip()
                            if len(extracted) > 200:
                                extracted = extracted[:200]
                            stop_regex = re.compile(r'^[^.!?]*[.!?]')
                            stop_match = stop_regex.search(extracted)
                            if stop_match:
                                extracted = stop_match.group(0)
                            original_title = extracted.strip()
                    
                    original_title = original_title.rstrip(' .,:;-')
                    break
        
        title_translated_processed = ''
        for p in article.select('div#informacoes > p'):
            html_content = str(p)
            html_content = html_content.replace('\n', '').replace('\t', '')
            html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
            lines = html_content.split('<br>')
            
            for line in lines:
                line_clean = re.sub(r'<[^>]*>', '', line).strip()
                if 'Título Traduzido:' in line_clean:
                    title_regex = re.compile(r'Título Traduzido:\s*([^\n\r]{1,200}?)(?:\s*(?:Gênero|Ano|Duração|Direção|Elenco|Sinopse|Título Original|$))')
                    match = title_regex.search(line_clean)
                    if match:
                        title_translated_processed = match.group(1).strip()
                    else:
                        parts = line_clean.split('Título Traduzido:')
                        if len(parts) > 1:
                            extracted = parts[1].strip()
                            if len(extracted) > 200:
                                extracted = extracted[:200]
                            stop_regex = re.compile(r'^[^.!?]*[.!?]')
                            stop_match = stop_regex.search(extracted)
                            if stop_match:
                                extracted = stop_match.group(0)
                            title_translated_processed = extracted.strip()
                    
                    title_translated_processed = title_translated_processed.rstrip(' .,:;-')
                    break
            if title_translated_processed:
                break
        
        if not original_title:
            original_title = title
        
        if self._should_skip_page_by_query(
            title, original_title, title_translated_processed, absolute_link,
        ):
            return []

        audio_info = None
        audio_html_content = ''
        all_paragraphs_html = []
        
        idioma = ''
        
        info_div = article.find('div', id='informacoes')
        if info_div:
            info_html = str(info_div)
            all_paragraphs_html.append(info_html)
            
            idioma_patterns = [
                r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Legendas?|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|$)',
                r'(?i)<[^>]*>Idioma\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Legendas?|$)',
            ]
            
            for pattern in idioma_patterns:
                idioma_match = re.search(pattern, info_html, re.DOTALL)
                if idioma_match:
                    idioma = idioma_match.group(1).strip()
                    idioma = html.unescape(idioma)
                    idioma = re.sub(r'<[^>]+>', '', idioma).strip()
                    idioma = re.sub(r'\s+', ' ', idioma).strip()
                    if idioma:
                        break
            
            if not idioma:
                for p in article.select('div#informacoes > p'):
                    html_content = str(p)
                    html_content = html_content.replace('\n', '').replace('\t', '')
                    html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
                    lines = html_content.split('<br>')
                    
                    for line in lines:
                        line_clean = re.sub(r'<[^>]*>', '', line).strip()
                        if 'Idioma:' in line_clean:
                            parts = line_clean.split('Idioma:')
                            if len(parts) > 1:
                                extracted = parts[1].strip()
                                stop_words = ['Legendas', 'Legenda', 'Qualidade', 'Duração', 'Formato', 'Vídeo', 'Nota', 'Tamanho']
                                for stop_word in stop_words:
                                    if stop_word in extracted:
                                        idx = extracted.index(stop_word)
                                        extracted = extracted[:idx]
                                        break
                                idioma = extracted.strip()
                                if idioma:
                                    break
                    if idioma:
                        break
        
        from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
        legenda = extract_legenda_from_page(doc, scraper_type='rede', article=article)
        
        legend_info = determine_legend_info(legenda) if legenda else None
        
        if idioma:
            from utils.parsing.audio_extraction import detect_audio_from_idioma_text
            audio_info = detect_audio_from_idioma_text(idioma)
        
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
            if legenda and 'Legenda' not in audio_html_content and 'legenda' not in audio_html_content.lower():
                audio_html_content += f' Legenda: {legenda}'
        
        sizes = []
        for p in article.select('div#informacoes > p'):
            html_content = str(p)
            html_content = html_content.replace('\n', '').replace('\t', '')
            html_content = re.sub(r'<br\s*\/?>', '<br>', html_content)
            lines = html_content.split('<br>')
            
            text = '\n'.join(re.sub(r'<[^>]*>', '', line).strip() for line in lines)
            y = find_year_from_text(text, title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
        
        text_content = article.find('div', class_='apenas_itemprop')
        
        magnet_links = []
        if text_content:
            for link in text_content.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet and resolved_magnet.startswith('magnet:'):
                    if resolved_magnet not in magnet_links:
                        magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            all_links = doc.select('a[href]')
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
        
        imdb = ''
        from utils.parsing.imdb_extraction import extract_imdb_from_soup
        info_div = article.find('div', id='informacoes')
        imdb = extract_imdb_from_soup(article, content_div=info_div)

        sizes = list(dict.fromkeys(sizes))
        
        from core.builders import build_torrents_from_magnets
        return build_torrents_from_magnets(
            magnet_links=magnet_links,
            sizes=sizes,
            page_title=title,
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
            fallback_title_priority='original_then_page',
        )

