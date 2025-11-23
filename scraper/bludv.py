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
    create_standardized_title,
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, prepare_release_title
)

logger = logging.getLogger(__name__)


# Scraper específico para Bludv Filmes
class BludvScraper(BaseScraper):
    SCRAPER_TYPE = "bludv"
    DEFAULT_BASE_URL = "https://bludv.net/"
    DISPLAY_NAME = "Bludv"
    
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
        seen_links = set()  # Para deduplicar links
        
        for item in doc.select('.post'):
            # Busca o link dentro de div.title > a
            link_elem = item.select_one('div.title > a')
            if link_elem:
                href = link_elem.get('href')
                if href and href not in seen_links:
                    links.append(href)
                    seen_links.add(href)
        
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
        
        seen_links = set()  # Para deduplicar links durante a busca
        
        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            for item in doc.select('.post'):
                link_elem = item.select_one('div.title > a')
                if link_elem:
                    href = link_elem.get('href')
                    if href and href not in seen_links:
                        links.append(href)
                        seen_links.add(href)
        
        return links  # Já está deduplicado via seen_links
    
    # Extrai torrents de uma página
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        doc = self.get_document(link, self.base_url)
        if not doc:
            return []
        
        # Extrai data da URL do link
        date = parse_date_from_string(link)
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        
        # Extrai título da página
        page_title = ''
        title_elem = doc.find('h1')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        # Extrai título original e traduzido
        original_title = ''
        translated_title = ''
        
        # Busca por "Título Original:" e "Título Traduzido:" no conteúdo
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')
        
        if content_div:
            # Busca por padrões de título original e traduzido usando BeautifulSoup
            # Procura em todos os elementos que possam conter essas informações
            
            # Extrai título original
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                # Verifica se contém "Título Original:" no texto ou HTML
                if re.search(r'(?i)T[íi]tulo\s+Original\s*:?', elem_html):
                    # Usa BeautifulSoup para extrair texto após o label
                    # Procura pelo texto "Título Original:" e pega o que vem depois
                    text_parts = elem_text.split('Título Original:')
                    if len(text_parts) > 1:
                        # Pega o texto após o label
                        original_title = text_parts[1].strip()
                        
                        # Tenta extrair do HTML de forma mais precisa
                        # Procura pelo padrão no HTML: Título Original: ... até <br ou </span
                        html_match = re.search(r'(?i)T[íi]tulo\s+Original\s*:?\s*(.*?)(?:<br|</span|</p|</div|$)', elem_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            # Remove todas as tags HTML
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                original_title = html_text
                        
                        # Remove entidades HTML
                        original_title = html.unescape(original_title)
                        # Remove espaços múltiplos
                        original_title = re.sub(r'\s+', ' ', original_title).strip()
                        # Para no primeiro separador comum
                        for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:', 'Título Traduzido:']:
                            if stop in original_title:
                                original_title = original_title.split(stop)[0].strip()
                                break
                        if original_title:
                            break
            
            # Extrai título traduzido
            for elem in content_div.find_all(['p', 'span', 'div', 'strong', 'em', 'li']):
                elem_html = str(elem)
                elem_text = elem.get_text(' ', strip=True)
                
                # Verifica se contém "Título Traduzido:" no texto ou HTML
                if re.search(r'(?i)T[íi]tulo\s+Traduzido\s*:?', elem_html):
                    # Usa BeautifulSoup para extrair texto após o label
                    text_parts = elem_text.split('Título Traduzido:')
                    if len(text_parts) > 1:
                        # Pega o texto após o label
                        translated_title = text_parts[1].strip()
                        
                        # Tenta extrair do HTML de forma mais precisa
                        html_match = re.search(r'(?i)T[íi]tulo\s+Traduzido\s*:?\s*(.*?)(?:<br|</span|</p|</div|$)', elem_html, re.DOTALL)
                        if html_match:
                            html_text = html_match.group(1)
                            # Remove todas as tags HTML
                            html_text = re.sub(r'<[^>]+>', '', html_text)
                            html_text = html_text.strip()
                            if html_text:
                                translated_title = html_text
                        
                        # Remove entidades HTML
                        translated_title = html.unescape(translated_title)
                        # Remove espaços múltiplos
                        translated_title = re.sub(r'\s+', ' ', translated_title).strip()
                        # Para no primeiro separador comum
                        for stop in ['\n', 'Gênero:', 'Duração:', 'Ano:', 'IMDb:']:
                            if stop in translated_title:
                                translated_title = translated_title.split(stop)[0].strip()
                                break
                        if translated_title:
                            break
        
        # Fallback: usa título da página se não encontrou título original
        if not original_title:
            original_title = page_title
        
        # Extrai ano e tamanhos
        year = ''
        sizes = []
        imdb = ''
        
        if content_div:
            for p in content_div.select('p, span, div'):
                text = p.get_text()
                html_content = str(p)
                
                # Extrai ano
                y = find_year_from_text(text, original_title or page_title)
                if y:
                    year = y
                
                # Extrai tamanhos
                sizes.extend(find_sizes_from_text(html_content))
                
                # Extrai IMDB - padrão específico do bludv
                # Formato: <strong><em>IMDb:</em></strong> <a href='https://www.imdb.com/pt/title/tt16358384/' target='_blank' rel='noopener'>7,9
                if not imdb:
                    # Busca padrão específico: <strong><em>IMDb:</em></strong> seguido de link
                    imdb_em = p.find('em', string=re.compile(r'IMDb:', re.I))
                    if imdb_em:
                        # Procura link IMDB próximo ao <em>IMDb:</em>
                        parent = imdb_em.parent
                        if parent:
                            for a in parent.select('a[href*="imdb.com"]'):
                                href = a.get('href', '')
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
                    
                    # Fallback: busca por texto "IMDB" ou "IMDb" próximo
                    if not imdb:
                        text_lower = text.lower()
                        has_imdb_label = 'imdb' in text_lower or 'imdb:' in text_lower
                        for a in p.select('a[href*="imdb.com"]'):
                            href = a.get('href', '')
                            # Tenta padrão /pt/title/tt
                            imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                # Se tem label IMDB, usa este. Caso contrário, continua procurando
                                if has_imdb_label:
                                    break
                                continue
                            # Tenta padrão /title/tt
                            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                            if imdb_match:
                                imdb = imdb_match.group(1)
                                # Se tem label IMDB, usa este. Caso contrário, continua procurando
                                if has_imdb_label:
                                    break
                                continue
        
        # Extrai links magnet - busca TODOS os magnets em todo o conteúdo
        # Também busca links protegidos (protlink, encurtador, systemads/get.php, etc.)
        # Busca em todo o documento, não apenas em containers específicos
        all_magnets = doc.select('a[href^="magnet:"], a[href*="protlink"], a[href*="encurtador"], a[href*="encurta"], a[href*="get.php"], a[href*="systemads"]')
        
        # Se não encontrou nada, tenta buscar em qualquer link que contenha esses padrões
        if not all_magnets:
            all_links = doc.select('a[href]')
            for link in all_links:
                href = link.get('href', '')
                if href and ('get.php' in href or 'systemads' in href or 'protlink' in href or 'encurtador' in href or 'encurta' in href):
                    all_magnets.append(link)
        
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
        
        # Remove duplicados de tamanhos
        sizes = list(dict.fromkeys(sizes))
        
        # Set para rastrear info_hashes já processados (deduplicação)
        seen_info_hashes = set()
        
        # Processa cada magnet
        for idx, magnet_link in enumerate(magnet_links):
            try:
                magnet_data = MagnetParser.parse(magnet_link)
                info_hash = magnet_data['info_hash']
                
                # Deduplica por info_hash - se já vimos este hash, pula
                if info_hash in seen_info_hashes:
                    continue
                seen_info_hashes.add(info_hash)
                
                raw_release_title = magnet_data.get('display_name', '')
                missing_dn = not raw_release_title or len(raw_release_title.strip()) < 3
                
                fallback_title = original_title or translated_title or page_title or ''
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
                
                # Adiciona [Brazilian] se detectar DUAL/DUBLADO/NACIONAL, [Eng] se LEGENDADO, ou ambos se houver os dois
                final_title = add_audio_tag_if_needed(standardized_title, original_release_title, info_hash=info_hash, skip_metadata=self._skip_metadata)
                
                # Extrai tamanho do magnet se disponível
                # Tenta associar tamanho ao magnet pelo índice, mas se não houver tamanho suficiente,
                # deixa vazio (será preenchido via metadata se disponível)
                size = ''
                if sizes and idx < len(sizes):
                    size = sizes[idx]
                
                torrent = {
                    'title': final_title,
                    'original_title': original_title if original_title else (translated_title if translated_title else page_title),
                    'details': link,
                    'year': year,
                    'imdb': imdb if imdb else '',
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

