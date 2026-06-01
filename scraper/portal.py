# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import detect_audio_from_html, add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title
from app.config import Config
from utils.logging import ScraperLogContext

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("Portal", logger)

class PortalScraper(BaseScraper):
    SCRAPER_TYPE = "portal"
    DEFAULT_BASE_URL = "https://www.nerdfilmes1.net"
    DISPLAY_NAME = "Portal"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
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

        for h2 in doc.find_all('h2', class_='block-title'):
            if 'Últimos Adicionados' in (h2.get_text() or ''):
                block_header = h2.find_parent('div', class_='block-header')
                if block_header:
                    movies_list = block_header.find_next_sibling('div', class_='movies-list')
                    if not movies_list:
                        movies_list = block_header.find_next('div', class_='movies-list')
                    if movies_list:
                        for item in movies_list.select('article.col .item .image a, article.col .item .title a, div.col .item .image a, div.col .item .title a'):
                            href = item.get('href')
                            if href:
                                absolute_url = urljoin(self.base_url, href)
                                if absolute_url not in filmes_links:
                                    filmes_links.append(absolute_url)
                break

        if not filmes_links:
            _log_ctx.info("Seção 'Últimos Adicionados' não encontrada - usando fallback genérico")
            for movies_list in doc.select('div.movies-list'):
                for item in movies_list.select('article.col .item .image a, article.col .item .title a, div.col .item .image a, div.col .item .title a'):
                    href = item.get('href')
                    if href:
                        absolute_url = urljoin(self.base_url, href)
                        if absolute_url not in filmes_links:
                            filmes_links.append(absolute_url)

        return (filmes_links, series_links)
    
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
            
            effective_max = get_effective_max_items(max_items)

            if effective_max > 0:
                filmes_links = limit_list(filmes_links, effective_max)
                _log_ctx.info(f"Limite configurado: {effective_max} - Coletando {len(filmes_links)} itens")
            links = filmes_links
            
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
        links = []
        for item in doc.select('.movies-list article.col .item .image a, .movies-list article.col .item .title a'):
            href = item.get('href')
            if href:
                links.append(href)
        
        if not links:
            for item in doc.select('div.movies-list div.item a'):
                href = item.get('href')
                if href:
                    links.append(href)
        
        if not links:
            for article in doc.select('article.post'):
                link_elem = article.select_one('h2.entry-title a, h1.entry-title a, header.entry-header a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        return links
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        
        content_div = None
        content_selectors = [
            'article',
            '.entry-content',
            '.post-content',
            '.content',
            'main',
            '.main-content'
        ]
        
        for selector in content_selectors:
            content_div = doc.select_one(selector)
            if content_div:
                break
        
        if not content_div:
            return []
        
        page_title = ''
        title_selectors = [
            'h1.entry-title',
            'h1.post-title',
            'h1',
            '.entry-title',
            '.post-title',
            'article h1'
        ]
        
        for selector in title_selectors:
            title_elem = doc.select_one(selector)
            if title_elem:
                page_title = title_elem.get_text(strip=True)
                break
        
        original_title = ''
        
        page_heading = doc.select_one('#page-heading')
        if page_heading:
            tempo_span = page_heading.select_one('span.tempo')
            if tempo_span:
                tempo_text = tempo_span.get_text(strip=True)
                tempo_html = str(tempo_span)
                if re.search(r'(?i)T[íi]tulo\s+original\s*:?', tempo_text):
                    text_match = re.search(r'(?i)T[íi]tulo\s+original\s*:?\s*(.+?)(?:\s*$)', tempo_text, re.DOTALL)
                    if text_match:
                        original_title = text_match.group(1).strip()
                    else:
                        html_match = re.search(r'(?i)T[íi]tulo\s+original\s*:?\s*(.*?)(?:</span|$)', tempo_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                original_title = html_text
        
        if not original_title:
            content_html = str(content_div)
            if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', content_html):
                html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(?:</b>|</strong>)?\s*:?\s*(.*?)(?:<br\s*/?>|</span|</p|</div|</strong|</b>|$)', content_html, re.DOTALL)
                
                if html_match:
                    html_text = html_match.group(1)
                    html_text = re.sub(r'<[^>]+>', '', html_text)
                    html_text = html_text.strip()
                    if html_text:
                        original_title = html_text
        
        if not original_title:
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', elem_html):
                    text_parts = elem_text.split('Título Original:')
                    if len(text_parts) > 1:
                        original_title = text_parts[1].strip()
                    
                    html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(?:</b>|</strong>)?\s*:?\s*(.*?)(?:<br\s*/?>|</span|</p|</div|</strong|</b>|$)', elem_html, re.DOTALL)
                    
                    if html_match:
                        html_text = html_match.group(1)
                        html_text = re.sub(r'<[^>]+>', '', html_text)
                        html_text = html_text.strip()
                        if html_text:
                            original_title = html_text
                    
                    if original_title:
                        break
        
        if original_title:
            original_title = html.unescape(original_title)
            original_title = re.sub(r'\s+', ' ', original_title).strip()
            for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:', 'Título Traduzido:']:
                if stop in original_title:
                    original_title = original_title.split(stop)[0].strip()
                    break
        
        title_translated_processed = ''
        poster_info = doc.select_one('.poster-info')
        if poster_info:
            poster_html = str(poster_info)
            poster_text = poster_info.get_text(' ', strip=True)
            
            if re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?', poster_html):
                html_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.*?)(?:<br|</span|</p|</div|</b|T[íi]tulo\s+Original:|IMDb:|Lançamento:|Gênero:|Duração:|$)', poster_html, re.DOTALL)
                if html_match:
                    html_text = html_match.group(1)
                    html_text = re.sub(r'<[^>]+>', '', html_text)
                    html_text = re.sub(r'(?i).*?T[íi]tulo\s+Original:.*$', '', html_text)
                    html_text = re.sub(r'(?i).*?IMDb:.*$', '', html_text)
                    html_text = html_text.strip()
                    if html_text:
                        title_translated_processed = html_text
                else:
                    text_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.+?)(?:\s+T[íi]tulo\s+Original:|IMDb:|Lançamento:|Gênero:|Duração:|$)', poster_text)
                    if text_match:
                        title_translated_processed = text_match.group(1).strip()
        
        if not title_translated_processed:
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                if re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?', elem_html):
                    html_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.*?)(?:<br|</span|</p|</div|</b|T[íi]tulo\s+Original:|IMDb:|Lançamento:|Gênero:|Duração:|$)', elem_html, re.DOTALL)
                    if html_match:
                        html_text = html_match.group(1)
                        html_text = re.sub(r'<[^>]+>', '', html_text)
                        html_text = re.sub(r'(?i).*?T[íi]tulo\s+Original:.*$', '', html_text)
                        html_text = re.sub(r'(?i).*?IMDb:.*$', '', html_text)
                        html_text = html_text.strip()
                        if html_text:
                            title_translated_processed = html_text
                    else:
                        text_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.+?)(?:\s+T[íi]tulo\s+Original:|IMDb:|Lançamento:|Gênero:|Duração:|$)', elem_text)
                        if text_match:
                            title_translated_processed = text_match.group(1).strip()
                    
                    if title_translated_processed:
                        break
        
        if not title_translated_processed:
            og_description = doc.find('meta', property='og:description')
            if og_description:
                og_content = og_description.get('content', '')
                if og_content:
                    meta_match = re.search(r'(?i)Baixar\s+(?:T[íi]tulo|Filme)\s*:?\s*(.+?)(?:\s+Título Original|$)', og_content)
                    if meta_match:
                        title_translated_processed = meta_match.group(1).strip()
        
        if not title_translated_processed:
            og_title = doc.find('meta', property='og:title')
            if og_title:
                og_title_content = og_title.get('content', '')
                if og_title_content:
                    og_title_clean = og_title_content.strip()
                    og_title_clean = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*', ' ', og_title_clean)
                    og_title_clean = re.sub(r'\s+Torrent\s+.*$', '', og_title_clean, flags=re.IGNORECASE)
                    og_title_clean = re.sub(r'\s+Dual\s+Áudio\s+Download\s*$', '', og_title_clean, flags=re.IGNORECASE)
                    og_title_clean = re.sub(r'\s+Download\s*$', '', og_title_clean, flags=re.IGNORECASE)
                    og_title_clean = html.unescape(og_title_clean)
                    og_title_clean = re.sub(r'\s+', ' ', og_title_clean).strip()
                    if og_title_clean:
                        title_translated_processed = og_title_clean
        
        if title_translated_processed:
            title_translated_processed = re.sub(r'\s+Torrent\s*$', '', title_translated_processed, flags=re.IGNORECASE)
            title_translated_processed = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*$', '', title_translated_processed)
            title_translated_processed = re.sub(r'\s*Torrent\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*$', '', title_translated_processed, flags=re.IGNORECASE)
            
            title_translated_processed = html.unescape(title_translated_processed)
            title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
            
            stop_patterns = [
                r'\n',
                r'Gênero:',
                r'Duração:',
                r'Ano:',
                r'IMDb:',
                r'T[íi]tulo\s+Original:',
                r'Lançamento',
            ]
            for pattern in stop_patterns:
                match = re.search(pattern, title_translated_processed, re.IGNORECASE)
                if match:
                    title_translated_processed = title_translated_processed[:match.start()].strip()
                    break
            
            if title_translated_processed:
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        if not original_title:
            original_title = page_title
        
        year = ''
        sizes = []
        imdb = ''
        audio_info = None
        audio_html_content = ''
        all_paragraphs_html = []
        
        content_html = str(content_div)
        idioma = ''
        
        idioma_match = re.search(r'(?i)<b>Idioma:</b>\s*([^<]+?)(?:<br|</div|</p|$)', content_html)
        if idioma_match:
            idioma = idioma_match.group(1).strip()
            idioma = html.unescape(idioma)
            idioma = re.sub(r'<[^>]+>', '', idioma).strip()
        
        if not idioma:
            idioma_match = re.search(r'(?i)Idioma\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|$)', content_html)
            if idioma_match:
                idioma = idioma_match.group(1).strip()
                idioma = html.unescape(idioma)
                idioma = re.sub(r'<[^>]+>', '', idioma).strip()
        
        if idioma:
            idioma_lower = idioma.lower()
            
            has_portugues_audio = 'português' in idioma_lower or 'portugues' in idioma_lower
            has_ingles = 'inglês' in idioma_lower or 'ingles' in idioma_lower or 'english' in idioma_lower
            
            if has_portugues_audio:
                audio_info = 'português'
            elif has_ingles:
                audio_info = 'inglês'
        
        for p in content_div.select('p, span, div'):
            text = p.get_text()
            html_content = str(p)
            all_paragraphs_html.append(html_content)
            
            y = find_year_from_text(text, original_title or page_title)
            if y:
                year = y
            
            sizes.extend(find_sizes_from_text(html_content))
            
            if not audio_info:
                audio_info = detect_audio_from_html(html_content)
            
            if not imdb:
                imdb_em = p.find('em', string=re.compile(r'IMDb:', re.I))
                if imdb_em:
                    parent = imdb_em.parent
                    if parent:
                        for a in parent.select('a[href*="imdb.com"]'):
                            href = a.get('href', '')
                            imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                break
                            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                break
                
                if not imdb:
                    text_lower = text.lower()
                    has_imdb_label = 'imdb' in text_lower or 'imdb:' in text_lower
                    for a in p.select('a[href*="imdb.com"]'):
                        href = a.get('href', '')
                        imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            if has_imdb_label:
                                break
                            continue
                        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                        if imdb_match:
                            imdb = imdb_match.group(1)
                            if has_imdb_label:
                                break
                            continue
        
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        elif content_html:
            audio_html_content = content_html
        
        all_links = doc.select('a[href]')
        
        magnet_links_with_text = []
        for link in all_links:
            href = link.get('href', '')
            if not href:
                continue
            
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:'):
                link_text = link.get_text(strip=True)
                link_text = link_text.replace('🧲', '').strip()
                link_text = re.sub(r'^\s+', '', link_text)
                
                if not any(m[0] == resolved_magnet for m in magnet_links_with_text):
                    magnet_links_with_text.append((resolved_magnet, link_text))
        
        if not magnet_links_with_text:
            return []
        
        sizes = list(dict.fromkeys(sizes))
        
        for idx, (magnet_link, link_text) in enumerate(magnet_links_with_text):
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
                
                magnet_original = magnet_data.get('display_name', '')
                

                if not magnet_original or len(magnet_original.strip()) < 3:
                    if link_text and len(link_text.strip()) >= 3:
                        cleaned_link_text = link_text.strip()
                        cleaned_link_text = cleaned_link_text.replace('🧲', '').strip()
                        cleaned_link_text = re.sub(r'^[\s\-|]+', '', cleaned_link_text)
                        cleaned_link_text = cleaned_link_text.strip()
                        

                        is_generic = bool(re.search(r'^(?:\d+p\s*\|?\s*)?(?:EPIS[ÓO]DIO|EP\.?)\s*\d+', cleaned_link_text, re.IGNORECASE))
                        is_generic = is_generic or bool(re.search(r'^\d+p\s*\|?\s*Dual\s+Áudio', cleaned_link_text, re.IGNORECASE))
                        
                        if not is_generic and len(cleaned_link_text) >= 5:
                            magnet_original = cleaned_link_text
                
                missing_dn = not magnet_original or len(magnet_original.strip()) < 3
                
                if not missing_dn and magnet_original:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, magnet_original)
                    except Exception:
                        pass
                
                fallback_title = original_title if original_title else (title_translated_processed if title_translated_processed else page_title or '')
                original_release_title = prepare_release_title(
                    magnet_original,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
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
                    origem_audio_tag = f'HTML da página (detect_audio_from_html)'
                elif magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
                legenda = extract_legenda_from_page(doc, scraper_type='portal')
                
                legend_info = determine_legend_info(legenda) if legenda else None
                
                from utils.parsing.legend_extraction import determine_legend_presence
                has_legenda = determine_legend_presence(
                    legend_info_from_html=legend_info,
                    audio_html_content=audio_html_content,
                    magnet_processed=original_release_title,
                    info_hash=info_hash,
                    skip_metadata=self._skip_metadata
                )
                
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
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
                    'original_title': original_title if original_title else (title_translated_processed if title_translated_processed else page_title),
                    'title_translated_processed': title_translated_processed if title_translated_processed else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb if imdb else '',
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.strftime('%Y-%m-%dT%H:%M:%SZ') if date else '',
                    'info_hash': info_hash,
                    'trackers': process_trackers(magnet_data),
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

