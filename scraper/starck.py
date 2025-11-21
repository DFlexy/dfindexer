"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    clean_title, remove_accents, create_standardized_title,
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, prepare_release_title
)

logger = logging.getLogger(__name__)


# Scraper específico para Starck Filmes
class StarckScraper(BaseScraper):
    SCRAPER_TYPE = "starck"
    DEFAULT_BASE_URL = "https://starckfilmes-v3.com/"
    DISPLAY_NAME = "Starck"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.item'):
            # Tenta primeiro o link com class="title" (mais específico)
            link_elem = item.select_one('div.sub-item > h3 > a.title')
            if not link_elem:
                # Fallback: primeiro link dentro de sub-item
                link_elem = item.select_one('div.sub-item > a')
            if not link_elem:
                # Fallback alternativo: qualquer link com "catalog" dentro de sub-item
                all_links = item.select('div.sub-item a[href*="catalog"]')
                if all_links:
                    link_elem = all_links[0]
            
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        return links
    
    # Obtém torrents de uma página específica
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        return self._default_get_page(page, max_items)
    
    # Busca com variações da query
    def _search_variations(self, query: str) -> List[str]:
        links = []
        variations = [query]
        
        # Remove stop words
        words = [w for w in query.split() if w.lower() not in STOP_WORDS]
        if words and ' '.join(words) != query:
            variations.append(' '.join(words))
        
        # Primeira palavra (apenas se não for stop word)
        query_words = query.split()
        if len(query_words) > 1:
            first_word = query_words[0].lower()
            # Só adiciona primeira palavra se não for stop word
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            for item in doc.select('.item'):
                # Tenta primeiro o link com class="title" (mais específico)
                link_elem = item.select_one('div.sub-item > h3 > a.title')
                if not link_elem:
                    # Fallback: primeiro link dentro de sub-item
                    link_elem = item.select_one('div.sub-item > a')
                if not link_elem:
                    # Fallback alternativo: qualquer link com "catalog" dentro de sub-item
                    all_links = item.select('div.sub-item a[href*="catalog"]')
                    if all_links:
                        link_elem = all_links[0]
                
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return list(set(links))  # Remove duplicados
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        doc = self.get_document(link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL (como no Go - getPublishedDateFromRawString)
        # Extrai data da URL do link
        date = parse_date_from_string(link)
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        post = doc.find('div', class_='post')
        if not post:
            return []
        
        capa = post.find('div', class_='capa')
        if not capa:
            return []
        
        # Extrai título da página
        page_title = ''
        title_elem = capa.select_one('.post-description > h2')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        # Extrai título original
        original_title = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                if 'Nome Original:' in spans[0].get_text():
                    original_title = spans[1].get_text(strip=True)
                    break
        
        # Extrai ano e tamanhos
        year = ''
        sizes = []
        for p in capa.select('.post-description p'):
            text = ' '.join(span.get_text() for span in p.find_all('span'))
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
        
        # Extrai links magnet - busca TODOS os magnets em todo o post
        # Isso garante que capture magnets de todas as seções (DUAL ÁUDIO, LEGENDADO, etc.)
        # Também busca links protegidos (protlink, encurtador, systemads/get.php, etc.)
        all_magnets = post.select('a[href^="magnet:"], a[href*="protlink"], a[href*="encurtador"], a[href*="encurta"], a[href*="get.php"], a[href*="systemads"]')
        
        magnet_links = []
        for magnet in all_magnets:
            href = magnet.get('href', '')
            if not href:
                continue
            
            # Link direto magnet
            if href.startswith('magnet:'):
                unescaped_href = html.unescape(href)
                if unescaped_href not in magnet_links:
                    magnet_links.append(unescaped_href)
            # Link protegido - resolve antes de adicionar
            else:
                from utils.parsing.link_resolver import is_protected_link, resolve_protected_link
                if is_protected_link(href):
                    try:
                        resolved_magnet = resolve_protected_link(href, self.session, self.base_url, redis=self.redis)
                        if resolved_magnet and resolved_magnet not in magnet_links:
                            magnet_links.append(resolved_magnet)
                    except Exception as e:
                        logger.debug(f"Erro ao resolver link protegido {href}: {e}")
                # Se não for link protegido, ignora (pode ser outro tipo de link)
                continue
        
        if not magnet_links:
            return []
        
        # Processa cada magnet
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                raw_release_title = magnet_data.get('display_name', '')
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                fallback_title = page_title or original_title or ''
                original_release_title = prepare_release_title(
                    raw_release_title,
                    fallback_title,
                    year,
                    missing_dn=missing_dn,
                    info_hash=info_hash if missing_dn else None,
                    skip_metadata=self._skip_metadata
                )
                
                standardized_title = create_standardized_title(
                    original_title, year, original_release_title
                )
                
                # Adiciona (pt-br) se o título do magnet contém DUAL, DUBLADO ou NACIONAL
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title)
                
                # Extrai tamanho do magnet se disponível
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else page_title,  # Usa nome original se disponível
                    'details': link,
                    'year': year,
                    'imdb': '',
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.isoformat(),
                    'info_hash': info_hash,
                    'trackers': process_trackers(magnet_data),
                    'size': size,
                    'leech_count': 0,
                    'seed_count': 0,
                    'similarity': 1.0
                }
                torrents.append(torrent)
            
            except Exception as e:
                logger.error(f"Erro ao processar magnet {link}: {e}")
                continue
        
        return torrents

