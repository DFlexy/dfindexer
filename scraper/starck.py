"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    clean_title, remove_accents, create_standardized_title,
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, prepare_release_title
)
from utils.logging import format_error, format_link_preview

logger = logging.getLogger(__name__)


# Scraper específico para Starck Filmes
class StarckScraper(BaseScraper):
    SCRAPER_TYPE = "starck"
    DEFAULT_BASE_URL = "https://www.starckfilmes-v6.com/"
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
        # Garante que o link seja absoluto para o campo details
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL
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
        
        # Extrai título traduzido
        translated_title = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                span_text = spans[0].get_text()
                if 'Título Traduzido:' in span_text or 'Titulo Traduzido:' in span_text:
                    # Pega o texto do segundo span, removendo qualquer HTML interno
                    span2 = spans[1]
                    # Remove todas as tags HTML internas antes de pegar o texto
                    for tag in span2.find_all(['strong', 'em', 'b', 'i']):
                        tag.unwrap()  # Remove a tag mas mantém o conteúdo
                    translated_title = span2.get_text(strip=True)
                    # Remove entidades HTML
                    translated_title = html.unescape(translated_title)
                    from utils.text.text_processing import clean_translated_title
                    translated_title = clean_translated_title(translated_title)
                    break
        
        # Fallback: se não encontrou "Título Traduzido", usa o título do post (h2.post-title)
        # sempre usa como fallback (não precisa verificar não-latinos)
        if not translated_title:
            post_title_elem = capa.select_one('h2.post-title')
            if post_title_elem:
                # Remove tags HTML e pega apenas o texto
                translated_title = post_title_elem.get_text(strip=True)
                # Remove entidades HTML
                translated_title = html.unescape(translated_title)
                # Limpa o título traduzido
                from utils.text.text_processing import clean_translated_title
                translated_title = clean_translated_title(translated_title)
        
        # Garante que não há HTML restante (remove qualquer tag que possa ter sobrado)
        if translated_title:
            # Remove todas as tags HTML que possam ter sobrado
            translated_title = re.sub(r'<[^>]+>', '', translated_title)
            # Remove entidades HTML novamente (caso tenha sobrado)
            translated_title = html.unescape(translated_title)
            # Aplica limpeza final
            from utils.text.text_processing import clean_translated_title
            translated_title = clean_translated_title(translated_title)
        
        # Extrai ano, tamanhos e IMDB
        year = ''
        sizes = []
        imdb = ''
        for p in capa.select('.post-description p'):
            text = ' '.join(span.get_text() for span in p.find_all('span'))
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
        
        # Extrai links magnet - busca TODOS os links <a> no post
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        all_links = post.select('a[href]')
        
        magnet_links = []
        for link in all_links:
            href = link.get('href', '')
            if not href:
                continue
            
            # Resolve automaticamente (magnet direto ou protegido)
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:') and resolved_magnet not in magnet_links:
                magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            return []
        
        # Processa cada magnet
        # IMPORTANTE: magnet_link já é o magnet resolvido (links protegidos foram resolvidos antes)
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                # Busca dados cruzados no Redis por info_hash (fallback principal)
                cross_data = None
                try:
                    from utils.text.cross_data import get_cross_data_from_redis
                    cross_data = get_cross_data_from_redis(info_hash)
                except Exception:
                    pass
                
                # Preenche campos faltantes com dados cruzados do Redis
                if cross_data:
                    if not original_title and cross_data.get('original_title_html'):
                        original_title = cross_data['original_title_html']
                    
                    if not translated_title and cross_data.get('translated_title_html'):
                        translated_title = cross_data['translated_title_html']
                    
                    if not imdb and cross_data.get('imdb'):
                        imdb = cross_data['imdb']
                
                # Extrai raw_release_title diretamente do display_name do magnet resolvido
                # NÃO modificar antes de passar para create_standardized_title
                raw_release_title = magnet_data.get('display_name', '')
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                # Se ainda está missing_dn, tenta buscar do cross_data
                if missing_dn and cross_data and cross_data.get('release_title_magnet'):
                    raw_release_title = cross_data['release_title_magnet']
                    missing_dn = False
                
                # Salva release_title_magnet no Redis se encontrado (para reutilização por outros scrapers)
                if not missing_dn and raw_release_title:
                    try:
                        from utils.text.text_processing import save_release_title_to_redis
                        save_release_title_to_redis(info_hash, raw_release_title)
                    except Exception:
                        pass
                
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
                    original_title, year, original_release_title, translated_title_html=translated_title if translated_title else None, raw_release_title_magnet=raw_release_title
                )
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, ou ambos se houver os dois
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title, info_hash=info_hash, skip_metadata=self._skip_metadata)
                
                # Determina origem_audio_tag
                origem_audio_tag = 'N/A'
                if raw_release_title and ('dual' in raw_release_title.lower() or 'dublado' in raw_release_title.lower() or 'legendado' in raw_release_title.lower()):
                    origem_audio_tag = 'release_title_magnet'
                elif missing_dn and info_hash:
                    origem_audio_tag = 'metadata (iTorrents.org) - usado durante processamento'
                
                # Extrai tamanho do magnet se disponível
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Salva dados cruzados no Redis para reutilização por outros scrapers
                try:
                    from utils.text.cross_data import save_cross_data_to_redis
                    cross_data_to_save = {
                        'original_title_html': original_title if original_title else None,
                        'release_title_magnet': raw_release_title if not missing_dn else None,
                        'translated_title_html': translated_title if translated_title else None,
                        'imdb': imdb if imdb else None,
                        'missing_dn': missing_dn,
                        'origem_audio_tag': origem_audio_tag if origem_audio_tag != 'N/A' else None,
                        'size': size if size and size.strip() else None
                    }
                    save_cross_data_to_redis(info_hash, cross_data_to_save)
                except Exception:
                    pass
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else page_title,  # Usa nome original se disponível
                    'translated_title': translated_title if translated_title else None,
                    'details': absolute_link,
                    'year': year,
                    'imdb': imdb,
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
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents

