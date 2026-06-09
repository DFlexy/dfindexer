# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import add_audio_tag_if_needed
from utils.text.title_builder import create_standardized_title, prepare_release_title
from utils.logging import format_error, format_link_preview

logger = logging.getLogger(__name__)

class BludvScraper(BaseScraper):
    SCRAPER_TYPE = "bludv"
    DEFAULT_BASE_URL = "https://bludv1.com/"
    DISPLAY_NAME = "Bludv"
    USE_FLARESOLVERR_DEFAULT = True
    
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
    
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        
        for item in doc.select('.post'):
            link_elem = item.select_one('div.title > a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        return links
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.post'):
            link_elem = item.select_one('div.title > a')
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
                audio_lower = audio_text.lower()
                
                idiomas_detectados = []
                
                if ('português' in audio_lower or 'portugues' in audio_lower or 
                    'pt-br' in audio_lower or 'ptbr' in audio_lower or 
                    'pt br' in audio_lower):
                    idiomas_detectados.append('português')
                if 'inglês' in audio_lower or 'ingles' in audio_lower or 'english' in audio_lower or 'en' in audio_lower:
                    idiomas_detectados.append('inglês')
                if 'japonês' in audio_lower or 'japones' in audio_lower or 'japanese' in audio_lower or 'jap' in audio_lower:
                    idiomas_detectados.append('japonês')
                
                idiomas_detectados = idiomas_detectados[:3]
                
                if len(idiomas_detectados) >= 2:
                    if 'português' in idiomas_detectados and 'inglês' in idiomas_detectados:
                        audio_info = 'dual'
                    elif 'português' in idiomas_detectados:
                        audio_info = 'dual'
                    else:
                        audio_info = idiomas_detectados[0]
                elif len(idiomas_detectados) == 1:
                    audio_info = idiomas_detectados[0]
        
        if content_div:
            for p in content_div.select('p, span, div'):
                text = p.get_text()
                html_content = str(p)
                
                y = find_year_from_text(text, original_title or page_title)
                if y:
                    year = y
                
                sizes.extend(find_sizes_from_text(html_content))
                

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
                
                magnet_original = magnet_data.get('display_name', '')
                missing_dn = not magnet_original or len(magnet_original.strip()) < 3
                
                if not missing_dn and magnet_original:
                    try:
                        from utils.text.storage import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, magnet_original)
                    except Exception:
                        pass
                
                fallback_title = original_title or title_translated_processed or page_title or ''
                original_release_title = prepare_release_title(
                    magnet_original,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                title_translated_processed_str = str(title_translated_processed) if title_translated_processed else None
                if title_translated_processed_str and not isinstance(title_translated_processed_str, str):
                    title_translated_processed_str = None
                
                standardized_title = create_standardized_title(
                    str(original_title) if original_title else '', year, original_release_title, title_translated_html=title_translated_processed_str, magnet_original=magnet_original
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
                if magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
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
                        'title_original_html': str(original_title) if original_title else None,
                        'magnet_processed': original_release_title if original_release_title else None,
                        'magnet_original': magnet_original if magnet_original else None,
                        'title_translated_html': str(title_translated_processed) if title_translated_processed else None,
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
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents

