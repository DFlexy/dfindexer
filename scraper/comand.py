# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from urllib.parse import unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.logging import format_error, format_link_preview, ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("Comand", logger)

class ComandScraper(BaseScraper):
    SCRAPER_TYPE = "comand"
    DEFAULT_BASE_URL = "https://comando1.com/"
    DISPLAY_NAME = "Comando"
    USE_FLARESOLVERR_DEFAULT = True
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
        
        self.month_replacer = {
            'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
            'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
            'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
        }
    
    def _parse_localized_date(self, date_text: str) -> Optional[datetime]:

        pattern = r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})'
        match = re.search(pattern, date_text, re.IGNORECASE)
        if match:
            day = match.group(1).zfill(2)
            month_name = match.group(2).lower()
            year = match.group(3)
            
            month = self.month_replacer.get(month_name)
            if month:
                date_str = f"{year}-{month}-{day}"
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                    return date
                except ValueError:
                    pass
        return None
    
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
        for article in doc.select('article'):
            link_elem = article.select_one('h2.entry-title a')
            if not link_elem:
                link_elem = article.select_one('header.entry-header h1.entry-title a, h1.entry-title a, header.entry-header a')
            
            if link_elem:
                href = link_elem.get('href')
                if href:
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    links.append(href)
        
        return links
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for article in doc.select('article.post'):
            link_elem = article.select_one('header.entry-header h1.entry-title a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        if not links:
            for article in doc.select('article'):
                link_elem = article.select_one('h1.entry-title a, header.entry-header a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        return links

    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        from urllib.parse import urljoin
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        date = None
        
        date_elem = doc.find('div', {'class': 'entry-date', 'itemprop': 'datePublished'})
        if date_elem:
            date_link = date_elem.find('a')
            if date_link:
                date_text = date_link.get_text(strip=True)
                try:
                    date = self._parse_localized_date(date_text)
                except (ValueError, AttributeError):
                    pass
        
        if not date:
            from utils.parsing.date_extraction import extract_date_from_page
            date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        article = doc.find('article')
        if not article:
            self._log_structure_miss(absolute_link, 'article')
            return []
        
        page_title = ''
        title_elem = article.select_one('h1.entry-title, header.entry-header h1.entry-title')
        if title_elem:
            title_link = title_elem.find('a')
            if title_link:
                page_title = title_link.get_text(strip=True)
            else:
                page_title = title_elem.get_text(strip=True)
        
        original_title = ''
        year = ''
        sizes = []
        imdb = ''
        
        entry_content = article.select_one('div.entry-content')
        if entry_content:
            html_content = str(entry_content)
            
            title_original_match = re.search(
                r'<strong>T[íi]tulo Original</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?=<span|<br|</p|</strong|<strong>Sinopse|<strong>Gênero|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|Temporada|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if title_original_match:
                original_title = title_original_match.group(1).strip()
                original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                original_title = html.unescape(original_title)
                original_title = re.sub(r'\s+', ' ', original_title).strip()
                stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                for stop_word in stop_words:
                    title_lower = original_title.lower()
                    stop_lower = stop_word.lower()
                    if stop_lower in title_lower:
                        idx = title_lower.index(stop_lower)
                        original_title = original_title[:idx].strip()
                        break
                if 'sinopse' in original_title.lower():
                    _log_ctx.warning(f"Título descartado por conter 'Sinopse' após processamento: {original_title[:100]}...")
                    original_title = ''
                elif len(original_title) > 200:
                    original_title = original_title[:200].strip()
                if original_title:
                    original_title = original_title.rstrip(' .,:;')
            
            if not original_title:
                title_original_match = re.search(
                    r'<b>T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<span|<br|</p|</b|<strong|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|$)',
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                    original_title = html.unescape(original_title)
                    original_title = re.sub(r'\s+', ' ', original_title).strip()
                    stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                    for stop_word in stop_words:
                        title_lower = original_title.lower()
                        stop_lower = stop_word.lower()
                        if stop_lower in title_lower:
                            idx = title_lower.index(stop_lower)
                            original_title = original_title[:idx].strip()
                            break
                    if 'sinopse' in original_title.lower():
                        _log_ctx.warning(f"Título descartado (Padrão 2) por conter 'Sinopse': {original_title[:100]}...")
                        original_title = ''
                    elif len(original_title) > 200:
                        original_title = original_title[:200].strip()
                    if original_title:
                        original_title = original_title.rstrip(' .,:;')
            
            if not original_title:
                title_original_match = re.search(
                    r'T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</b|<strong|Gênero|Sinopse|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|$)',
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                    original_title = html.unescape(original_title)
                    original_title = re.sub(r'\s+', ' ', original_title).strip()
                    stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido']
                    for stop_word in stop_words:
                        title_lower = original_title.lower()
                        stop_lower = stop_word.lower()
                        if stop_lower in title_lower:
                            idx = title_lower.index(stop_lower)
                            original_title = original_title[:idx].strip()
                            break
                    if 'sinopse' in original_title.lower():
                        _log_ctx.warning(f"Título descartado (Padrão 3) por conter 'Sinopse': {original_title[:100]}...")
                        original_title = ''
                    if original_title:
                        original_title = original_title.rstrip(' .,:;-')
            
            if not original_title:
                for elem in entry_content.find_all(['b', 'strong', 'p', 'span']):
                    text = elem.get_text()
                    if re.search(r'T[íi]tulo Original', text, re.IGNORECASE):
                        next_elem = elem.find_next_sibling()
                        if next_elem:
                            original_title = next_elem.get_text(strip=True)
                        else:
                            html_elem = str(elem)
                            match = re.search(r'T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+)', html_elem, re.IGNORECASE | re.DOTALL)
                            if match:
                                original_title = match.group(1).strip()
                                original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                                original_title = html.unescape(original_title)
                        if original_title:
                            original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                            original_title = html.unescape(original_title)
                            original_title = re.sub(r'\s+', ' ', original_title).strip()
                            stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                            for stop_word in stop_words:
                                title_lower = original_title.lower()
                                stop_lower = stop_word.lower()
                                if stop_lower in title_lower:
                                    idx = title_lower.index(stop_lower)
                                    original_title = original_title[:idx].strip()
                                    break
                            if 'sinopse' in original_title.lower():
                                _log_ctx.warning(f"Título descartado (Padrão 4) por conter 'Sinopse': {original_title[:100]}...")
                                original_title = ''
                            elif len(original_title) > 200:
                                original_title = original_title[:200].strip()
                            if original_title:
                                original_title = original_title.rstrip(' .,:;')
                            break
            
            if not original_title:
                content_text = entry_content.get_text()
                title_original_match = re.search(
                    r'T[íi]tulo Original[:\s]+([^\n]+?)(?:\n|Sinopse|Gênero|Lançamento|Duração|Formato|Qualidade|Áudio|Audio|Legenda|Tamanho|IMDb|TEMPORADA|Temporada|$)',
                    content_text,
                    re.IGNORECASE
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    original_title = html.unescape(original_title)
                    stop_words = ['Sinopse', 'Gênero', 'Lançamento', 'Duração', 'Formato', 'Qualidade', 'Áudio', 'Audio', 'Legenda', 'Tamanho', 'IMDb', 'Título Traduzido', 'TEMPORADA', 'Temporada']
                    for stop_word in stop_words:
                        title_lower = original_title.lower()
                        stop_lower = stop_word.lower()
                        if stop_lower in title_lower:
                            idx = title_lower.index(stop_lower)
                            original_title = original_title[:idx].strip()
                            break
                    if 'sinopse' in original_title.lower():
                        _log_ctx.warning(f"Título descartado (Padrão 5) por conter 'Sinopse': {original_title[:100]}...")
                        original_title = ''
                    elif len(original_title) > 200:
                        original_title = original_title[:200].strip()
                    if original_title:
                        original_title = original_title.rstrip(' .,:;')
            
            lancamento_match = re.search(
                r'Lançamento[:\s]*</b>\s*<a[^>]*>(\d{4})</a>',
                html_content,
                re.IGNORECASE
            )
            if lancamento_match:
                year = lancamento_match.group(1).strip()
            
            if not year:
                lancamento_match = re.search(
                    r'Lançamento[:\s]*</b>\s*(?:<br\s*/?>)?\s*(\d{4})',
                    html_content,
                    re.IGNORECASE
                )
                if lancamento_match:
                    year = lancamento_match.group(1).strip()
            
            if not year:
                content_text = entry_content.get_text()
                y = find_year_from_text(content_text, page_title)
                if y:
                    year = y
            
            tamanho_match = re.search(
                r'Tamanho[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<\n]+?)(?:<br|</p|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if tamanho_match:
                tamanho_text = re.sub(r'<[^>]+>', '', tamanho_match.group(1)).strip()
                tamanho_text = html.unescape(tamanho_text)
                sizes.extend(find_sizes_from_text(tamanho_text))
            
            if not sizes:
                content_text = entry_content.get_text()
                sizes.extend(find_sizes_from_text(content_text))
            
            sizes = list(dict.fromkeys(sizes))
            
            from utils.parsing.imdb_extraction import extract_imdb_from_soup
            imdb = extract_imdb_from_soup(entry_content, content_div=entry_content) if entry_content else ''
        
        title_translated_processed = ''
        if entry_content:
            html_content = str(entry_content)
            
            title_traduzido_match = re.search(
                r'<strong>T[íi]tulo Traduzido</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</strong|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if title_traduzido_match:
                title_translated_processed = title_traduzido_match.group(1).strip()
                title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed).strip()
                title_translated_processed = html.unescape(title_translated_processed)
                title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
                title_translated_processed = title_translated_processed.rstrip(' .,:;-')
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
            
            if not title_translated_processed:
                title_traduzido_match = re.search(
                    r'<b>T[íi]tulo Traduzido[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|$)', 
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_traduzido_match:
                    title_translated_processed = title_traduzido_match.group(1).strip()
                    title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed).strip()
                    title_translated_processed = html.unescape(title_translated_processed)
                    title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
                    title_translated_processed = title_translated_processed.rstrip(' .,:;-')
                    from utils.text.cleaning import clean_title_translated_processed
                    title_translated_processed = clean_title_translated_processed(title_translated_processed)
            
            if not title_translated_processed:
                content_text = entry_content.get_text()
                title_traduzido_match = re.search(
                    r'T[íi]tulo Traduzido[:\s]+([^\n]+?)(?:\n|$)',
                    content_text,
                    re.IGNORECASE
                )
                if title_traduzido_match:
                    title_translated_processed = title_traduzido_match.group(1).strip()
                    title_translated_processed = title_translated_processed.rstrip(' .,:;-')
        
        if title_translated_processed:
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            title_translated_processed = html.unescape(title_translated_processed)
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        if original_title:
            original_title_lower = original_title.lower().strip()
            if original_title_lower.startswith('sinopse'):
                _log_ctx.warning(f"Título descartado por começar com 'Sinopse': {original_title[:100]}...")
                original_title = ''
            elif len(original_title) > 100:
                sinopse_indicators = ['mauro', 'michel', 'joelsas', 'garoto', 'mineiro', 'adora', 'futebol', 'jogo', 'botao', 'vida', 'muda', 'completamente', 'pais', 'saem', 'ferias', 'inesperada', 'um dia', 'sua vida', 'que adora', 'anos que']
                title_lower = original_title_lower
                indicator_count = sum(1 for indicator in sinopse_indicators if indicator in title_lower)
                if indicator_count >= 3:
                    _log_ctx.warning(f"Título descartado por conter {indicator_count} indicadores de sinopse: {original_title[:100]}...")
                    original_title = ''
        
        if not original_title:
            original_title = page_title
        
        if self._should_skip_page_by_query(
            page_title, original_title, title_translated_processed, absolute_link,
        ):
            return []

        audio_info = ''
        audio_html_content = ''
        all_paragraphs_html = []
        
        if entry_content:
            content_html = str(entry_content)
            all_paragraphs_html.append(content_html)
            
            from utils.parsing.audio_extraction import detect_audio_from_html
            audio_info = detect_audio_from_html(content_html)
            
            if not audio_info:
                for p in entry_content.find_all(['p', 'span', 'div', 'strong', 'em', 'li', 'b']):
                    html_content = str(p)
                    all_paragraphs_html.append(html_content)
                    audio_info = detect_audio_from_html(html_content)
                    if audio_info:
                        break
            
            if all_paragraphs_html:
                audio_html_content = ' '.join(all_paragraphs_html)
            
            from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
            legenda = extract_legenda_from_page(doc, scraper_type='comand', content_div=entry_content)
            
            legend_info = determine_legend_info(legenda) if legenda else None
        
        magnet_links = []
        if entry_content:
            for link in entry_content.select('a[href]'):
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
            fallback_title_priority='original_then_page',
        )

