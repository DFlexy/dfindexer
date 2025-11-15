"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.text_processing import (
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)
from utils.date_parser import parse_date_from_string

logger = logging.getLogger(__name__)


class TfilmeScraper(BaseScraper):
    """Scraper específico para Torrent dos Filmes"""
    
    SCRAPER_TYPE = "tfilme"
    DEFAULT_BASE_URL = "https://torrentdosfilmes.se/"
    DISPLAY_NAME = "TFilme"
    
    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url)
        self.search_url = "?s="
        self.page_pattern = "category/dublado/page/{}/"
    
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
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
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
        
        # Primeira palavra (se não for stop word)
        query_words = query.split()
        if len(query_words) > 1:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return list(set(links))
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        """Extrai torrents de uma página"""
        doc = self.get_document(link, self.base_url)
        if not doc:
            return []
        
        date = parse_date_from_string(link)
        if not date:
            date_meta = doc.find('meta', {'property': 'article:published_time'})
            if date_meta:
                date_content = date_meta.get('content', '')
                if date_content:
                    try:
                        date_content = date_content.replace('Z', '+00:00')
                        date = datetime.fromisoformat(date_content)
                    except (ValueError, AttributeError):
                        pass
            
            if not date:
                date = datetime.now()
        
        torrents = []
        article = doc.find('article')
        if not article:
            return []
        
        # Extrai título da página
        page_title = ''
        title_div = article.find('div', class_='title')
        if title_div:
            h1 = title_div.find('h1')
            if h1:
                page_title = h1.get_text(strip=True).replace(' - Download', '')
        
        if not page_title:
            return []
        
        # Extrai título original
        original_title = ''
        for content_div in article.select('div.content'):
            html_content = str(content_div)
            
            # Tenta regex no HTML
            title_regex = re.compile(r'(?i)t[íi]tulo\s+original:\s*</b>\s*([^<\n\r]+)')
            match = title_regex.search(html_content)
            if match:
                original_title = match.group(1).strip()
            else:
                # Tenta extrair do texto
                text = content_div.get_text()
                if 'Título Original:' in text:
                    parts = text.split('Título Original:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse']
                        for stop_word in stop_words:
                            if stop_word in title_part:
                                idx = title_part.index(stop_word)
                                title_part = title_part[:idx]
                                break
                        lines = title_part.split('\n')
                        if lines:
                            original_title = lines[0].strip()
                elif 'Titulo Original:' in text:
                    parts = text.split('Titulo Original:')
                    if len(parts) > 1:
                        title_part = parts[1].strip()
                        stop_words = ['Lançamento', 'Gênero', 'IMDB', 'Duração', 'Qualidade', 'Áudio', 'Sinopse']
                        for stop_word in stop_words:
                            if stop_word in title_part:
                                idx = title_part.index(stop_word)
                                title_part = title_part[:idx]
                                break
                        lines = title_part.split('\n')
                        if lines:
                            original_title = lines[0].strip()
        
        # Extrai ano e tamanhos
        year = ''
        sizes = []
        for p in article.select('div.content p'):
            text = p.get_text()
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
        
        # Extrai links magnet
        text_content = article.find('div', class_='content')
        if not text_content:
            return []
        
        magnet_links = []
        for magnet in text_content.select('a[href^="magnet:"]'):
            href = magnet.get('href', '')
            if href:
                href = href.replace('&#038;', '&').replace('&amp;', '&')
                magnet_links.append(html.unescape(href))
        
        if not magnet_links:
            return []
        
        # Extrai IMDB
        imdb = ''
        for a in article.select('div.content a'):
            href = a.get('href', '')
            if 'imdb.com' in href:
                imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                if imdb_match:
                    imdb = imdb_match.group(1)
                    break
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
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
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Processa trackers
                trackers = []
                for tracker in magnet_data.get('trackers', []):
                    tracker = tracker.replace('&#038;', '&').replace('&amp;', '&')
                    try:
                        tracker = unquote(tracker)
                    except:
                        pass
                    trackers.append(tracker.strip())
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else page_title,
                    'details': link,
                    'year': year,
                    'imdb': imdb,
                    'audio': [],
                    'magnet_link': magnet_link,
                    'date': date.isoformat(),
                    'info_hash': info_hash,
                    'trackers': trackers,
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


