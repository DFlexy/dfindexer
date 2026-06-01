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
from utils.text.cleaning import clean_title, remove_accents
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.text.title_builder import create_standardized_title, prepare_release_title
from utils.parsing.audio_extraction import add_audio_tag_if_needed, detect_audio_from_html
from utils.logging import format_error, format_link_preview
from utils.parsing.link_resolver import decode_data_u

logger = logging.getLogger(__name__)

_RE_STARCK_DATA_U_DQ = re.compile(r'data-u\s*=\s*"([^"]*)"', re.I)
_RE_STARCK_DATA_U_SQ = re.compile(r"data-u\s*=\s*'([^']*)'", re.I)

def _starck_raw_data_u_values(page_html: str) -> List[str]:
    if not page_html:
        return []
    low = page_html.lower()
    i = low.find('post-buttons')
    if i < 0:
        chunk = page_html
    else:
        j = low.find('post-content', i + 1)
        chunk = page_html[i:j] if j > i else page_html[i : i + 900000]
    out: List[str] = []
    seen = set()
    for rx in (_RE_STARCK_DATA_U_DQ, _RE_STARCK_DATA_U_SQ):
        for m in rx.finditer(chunk):
            v = m.group(1).strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    return out

class StarckScraper(BaseScraper):
    SCRAPER_TYPE = "starck"
    DEFAULT_BASE_URL = "https://starckfilmes-v17.com/"
    DISPLAY_NAME = "Starck"
    
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
        seen_hrefs = set()
        
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog')
        if not catalog_div:
            catalog_div = doc
        
        items = catalog_div.select('.item')
        
        for item in items:

            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            
            all_links = sub_item.find_all('a', href=lambda h: h and 'catalog' in h)
            link_elem = None
            
            for link in all_links:
                parent_h3 = link.find_parent('h3')
                title_attr = link.get('title')
                
                if not parent_h3 and title_attr and title_attr.strip():
                    link_elem = link
                    break
            
            if link_elem:
                href = link_elem.get('href')
                title_attr = link_elem.get('title')
                
                if href and title_attr and title_attr.strip():
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    if href not in seen_hrefs:
                        links.append(href)
                        seen_hrefs.add(href)
        
        logger.debug(f"[Starck] Encontrados {len(items)} itens na página e extraídos {len(links)} links únicos")
        return links
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        seen_hrefs = set()
        
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog')
        if not catalog_div:
            catalog_div = doc
        
        for item in catalog_div.select('.item'):

            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            
            link_elem = sub_item.find('a', href=lambda h: h and 'catalog' in h, title=lambda t: t and t.strip())
            
            if link_elem:
                href = link_elem.get('href')
                title_attr = link_elem.get('title')
                
                if href and title_attr and title_attr.strip():
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    if href not in seen_hrefs:
                        links.append(href)
                        seen_hrefs.add(href)
        
        return links
    
    def _search_variations(self, query: str) -> List[str]:
        from urllib.parse import urljoin, quote
        from utils.text.constants import STOP_WORDS
        
        links = []
        seen_urls = set()
        variations = [query]
        
        words = [w for w in query.split() if w.lower() not in STOP_WORDS]
        if words and ' '.join(words) != query:
            variations.append(' '.join(words))
        
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
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            page_links = self._extract_search_results(doc)
            
            for href in page_links:
                absolute_url = urljoin(self.base_url, href)
                
                if absolute_url not in seen_urls:
                    links.append(absolute_url)
                    seen_urls.add(absolute_url)
        
        return links
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        post = doc.find('div', class_='post')
        if not post:
            return []
        
        capa = post.find('div', class_='capa')
        if not capa:
            return []
        
        page_title = ''
        title_elem = capa.select_one('.post-description > h2')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        original_title = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                if 'Nome Original:' in spans[0].get_text():
                    original_title = spans[1].get_text(strip=True)
                    break
        
        title_translated_processed = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                span_text = spans[0].get_text()
                if 'Título Traduzido:' in span_text or 'Titulo Traduzido:' in span_text:
                    span2 = spans[1]
                    for tag in span2.find_all(['strong', 'em', 'b', 'i']):
                        tag.unwrap()
                    title_translated_processed = span2.get_text(strip=True)
                    title_translated_processed = html.unescape(title_translated_processed)
                    from utils.text.cleaning import clean_title_translated_processed
                    title_translated_processed = clean_title_translated_processed(title_translated_processed)
                    break
        
        if not title_translated_processed:
            post_title_elem = capa.select_one('h2.post-title')
            if post_title_elem:
                title_translated_processed = post_title_elem.get_text(strip=True)
                title_translated_processed = html.unescape(title_translated_processed)
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        if title_translated_processed:
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            title_translated_processed = html.unescape(title_translated_processed)
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        year = ''
        sizes = []
        imdb = ''
        audio_info = ''
        audio_html_content = ''
        all_paragraphs_html = []
        for p in capa.select('.post-description p'):
            text = ' '.join(span.get_text() for span in p.find_all('span'))
            html_content = str(p)
            all_paragraphs_html.append(html_content)
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
            
            if not audio_info:
                audio_info = detect_audio_from_html(html_content)
        
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        all_links = post.select('a[href]')
        
        magnet_links: List[str] = []
        seen_hashes: set = set()
        seen_data_u: set = set()

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

        for link in all_links:
            href = link.get('href', '')
            if not href:
                continue
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet:
                _add_magnet(resolved_magnet)

        if not magnet_links:
            for link in post.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                resolved_magnet = self._resolve_link(href)
                if resolved_magnet:
                    _add_magnet(resolved_magnet)

        def _append_decoded_magnets_from_data_u_values(values: List[str]) -> None:
            for data_u_value in values:
                v = html.unescape(data_u_value.strip())
                if not v or v in seen_data_u:
                    continue
                seen_data_u.add(v)
                decoded_magnet = decode_data_u(v)
                if decoded_magnet:
                    _add_magnet(decoded_magnet)

        page_html = self._get_fetched_html()
        _append_decoded_magnets_from_data_u_values(_starck_raw_data_u_values(page_html))

        buttons_root = post.select_one('.post-buttons') or post
        for elem in buttons_root.select('[data-u]'):
            data_u_value = (elem.get('data-u') or '').strip()
            if not data_u_value or data_u_value in seen_data_u:
                continue
            seen_data_u.add(data_u_value)
            decoded_magnet = decode_data_u(data_u_value)
            if decoded_magnet:
                _add_magnet(decoded_magnet)

        if not magnet_links:

            return []
        
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
                
                fallback_title = page_title or original_title or ''
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
                
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title, info_hash=info_hash, skip_metadata=self._skip_metadata, audio_info_from_html=audio_info, audio_html_content=audio_html_content if audio_html_content else None)
                
                origem_audio_tag = 'N/A'
                if audio_info:
                    origem_audio_tag = f'HTML da página (detect_audio_from_html)'
                elif magnet_original and ('dual' in magnet_original.lower() or 'dublado' in magnet_original.lower() or 'legendado' in magnet_original.lower()):
                    origem_audio_tag = 'magnet_processed'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
                legenda = extract_legenda_from_page(doc, scraper_type='starck')
                
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
                    'original_title': original_title if original_title else page_title,
                    'title_translated_processed': title_translated_processed if title_translated_processed else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb,
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

