"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from utils.parsing.date_parser import parse_date_from_string
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote, urljoin
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)
from utils.logging import format_error, format_link_preview

logger = logging.getLogger(__name__)


# Scraper específico para Rede Torrent
class RedeScraper(BaseScraper):
    SCRAPER_TYPE = "rede"
    DEFAULT_BASE_URL = "https://redetorrent.com/"
    DISPLAY_NAME = "Rede"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "index.php?s="
        self.page_pattern = "{}"
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        for item in doc.select('.capa_lista'):
            link_elem = item.select_one('a')
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
            
            for item in doc.select('.capa_lista'):
                link_elem = item.select_one('a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
        
        return list(set(links))
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        # Garante que o link seja absoluto para o campo details
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL do link
        date = parse_date_from_string(link)
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        article = doc.find('div', class_='conteudo')
        if not article:
            return []
        
        # Extrai título e ano do h1
        h1 = article.find('h1')
        if not h1:
            return []
        
        title_text = h1.get_text(strip=True)
        # Padrão: "Title - Subtitle (YYYY)" ou "Title (YYYY)"
        title_match = re.search(r'^(.*?)(?: - (.*?))? \((\d{4})\)', title_text)
        if not title_match:
            return []
        
        title = title_match.group(1).strip()
        year = title_match.group(3).strip()
        
        # Extrai título original
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
        
        # Extrai título traduzido
        translated_title = ''
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
                        translated_title = match.group(1).strip()
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
                            translated_title = extracted.strip()
                    
                    translated_title = translated_title.rstrip(' .,:;-')
                    break
            if translated_title:
                break
        
        if not original_title:
            original_title = title
        
        # Extrai tamanhos
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
        
        # Extrai links magnet - busca TODOS os links <a> no conteúdo
        # A função _resolve_link automaticamente identifica e resolve links protegidos
        text_content = article.find('div', class_='apenas_itemprop')
        if not text_content:
            return []
        
        magnet_links = []
        for link in text_content.select('a[href]'):
            href = link.get('href', '')
            if not href:
                continue
            
            # Resolve automaticamente (magnet direto ou protegido)
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet and resolved_magnet.startswith('magnet:') and resolved_magnet not in magnet_links:
                magnet_links.append(resolved_magnet)
        
        if not magnet_links:
            return []
        
        # Extrai IMDB - prioriza links dentro de div#informacoes (conteúdo principal)
        imdb = ''
        # Primeiro busca dentro de div#informacoes (conteúdo principal)
        info_div = article.find('div', id='informacoes')
        if info_div:
            for a in info_div.select('a'):
                href = a.get('href', '')
                if 'imdb.com' in href:
                    # Tenta padrão /pt/title/tt
                    imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                    if imdb_match:
                        imdb = imdb_match.group(1)
                        break
                    # Tenta padrão /title/tt
                    imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                    if imdb_match:
                        imdb = imdb_match.group(1)
                        break
        
        # Se não encontrou em div#informacoes, busca em toda a página
        if not imdb:
            for a in article.select('a'):
                href = a.get('href', '')
                if 'imdb.com' in href:
                    # Tenta padrão /pt/title/tt
                    imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                    if imdb_match:
                        imdb = imdb_match.group(1)
                        break
                    # Tenta padrão /title/tt
                    imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                    if imdb_match:
                        imdb = imdb_match.group(1)
                        break
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
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
                
                fallback_title = original_title if original_title else title
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
                
                # Extrai tamanho
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                # Processa trackers usando função utilitária
                trackers = process_trackers(magnet_data)
                
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
                    'original_title': original_title if original_title else title,
                    'translated_title': translated_title if translated_title else None,
                    'details': absolute_link,
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
                logger.error(f"Magnet error: {format_error(e)} (link: {format_link_preview(magnet_link)})")
                continue
        
        return torrents


