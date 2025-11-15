"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from urllib.parse import quote
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.text_processing import (
    clean_title, remove_accents, create_standardized_title,
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, prepare_release_title
)
from utils.date_parser import parse_date_from_string

logger = logging.getLogger(__name__)


class StarckScraper(BaseScraper):
    """Scraper específico para Starck Filmes"""
    
    SCRAPER_TYPE = "starck"
    DEFAULT_BASE_URL = "https://starckfilmes-v3.com/"
    DISPLAY_NAME = "Starck"
    
    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
    
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        """Busca torrents com variações da query"""
        links = self._search_variations(query)
        
        all_torrents = []
        for link in links:
            torrents = self._get_torrents_from_page(link)
            all_torrents.extend(torrents)
        
        return self.enrich_torrents(all_torrents, filter_func=filter_func)
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        """Obtém torrents de uma página específica"""
        # Detecta se está usando limite padrão (teste do Prowlarr)
        is_using_default_limit = max_items is None
        
        # Armazena skip_metadata temporariamente para uso em _get_torrents_from_page
        self._skip_metadata = is_using_default_limit
        try:
            if page == '1':
                page_url = self.base_url
            else:
                page_url = f"{self.base_url}{self.page_pattern.format(page)}"
            
            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []
            
            links = []
            for item in doc.select('.item'):
                link_elem = item.select_one('div.sub-item > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
            
            # Obtém limite efetivo (usa padrão de 3 se não especificado)
            effective_max = self._get_effective_max_items(max_items)
            
            # Limita links
            if effective_max > 0:
                links = links[:effective_max]
            
            all_torrents = []
            for link in links:
                torrents = self._get_torrents_from_page(link)
                all_torrents.extend(torrents)
                # Para quando tiver resultados suficientes
                if len(all_torrents) >= effective_max:
                    break
            
            # Pula metadata e trackers se estiver usando limite padrão (teste do Prowlarr)
            enriched = self.enrich_torrents(
                all_torrents, 
                skip_metadata=is_using_default_limit,
                skip_trackers=is_using_default_limit
            )
            return enriched[:effective_max]
        finally:
            self._skip_metadata = False
    
    def _search_variations(self, query: str) -> List[str]:
        """Busca com variações da query"""
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
                link_elem = item.select_one('div.sub-item > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return list(set(links))  # Remove duplicados
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        """Extrai torrents de uma página"""
        doc = self.get_document(link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL (como no Go - getPublishedDateFromRawString)
        date = parse_date_from_string(link)
        if not date:
            # Tenta extrair da página HTML (meta tag article:published_time)
            date_meta = doc.find('meta', {'property': 'article:published_time'})
            if date_meta:
                date_content = date_meta.get('content', '')
                if date_content:
                    try:
                        # Remove 'Z' e adiciona timezone se necessário
                        date_content = date_content.replace('Z', '+00:00')
                        date = datetime.fromisoformat(date_content)
                    except (ValueError, AttributeError):
                        pass
            
            # Se ainda não encontrou, usa data atual
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
        all_magnets = post.select('a[href^="magnet:"]')
        
        magnet_links = []
        for magnet in all_magnets:
            href = magnet.get('href', '')
            if href:
                # Remove duplicados usando unescape para normalizar
                unescaped_href = html.unescape(href)
                if unescaped_href not in magnet_links:
                    magnet_links.append(unescaped_href)
        
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
                    'trackers': magnet_data.get('trackers', []),
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

