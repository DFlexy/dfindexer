"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional, Callable
from urllib.parse import quote, unquote
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from magnet.parser import MagnetParser
from utils.parsing.magnet_utils import process_trackers
from utils.text.text_processing import (
    find_year_from_text, find_sizes_from_text, STOP_WORDS,
    add_audio_tag_if_needed, create_standardized_title, prepare_release_title
)

logger = logging.getLogger(__name__)


# Scraper específico para Comando Torrents
class ComandScraper(BaseScraper):
    SCRAPER_TYPE = "comand"
    DEFAULT_BASE_URL = "https://comando.la/"
    DISPLAY_NAME = "Comando"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
        
        # Mapeamento de meses em português para números (como no código Go)
        self.month_replacer = {
            'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
            'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
            'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
        }
    
    # Faz parsing de data localizada em português (ex: "16 de novembro de 2025")
    def _parse_localized_date(self, date_text: str) -> Optional[datetime]:
        # Padrão: "16 de novembro de 2025" ou "1 de novembro de 2025"
        pattern = r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})'
        match = re.search(pattern, date_text, re.IGNORECASE)
        if match:
            day = match.group(1).zfill(2)  # Adiciona zero à esquerda se necessário
            month_name = match.group(2).lower()
            year = match.group(3)
            
            # Converte nome do mês para número
            month = self.month_replacer.get(month_name)
            if month:
                # Formata como YYYY-MM-DD
                date_str = f"{year}-{month}-{day}"
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                    # Retorna sem timezone (consistente com outros scrapers)
                    return date
                except ValueError:
                    pass
        return None
    
    # Busca torrents com variações da query
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        return self._default_search(query, filter_func)
    
    # Extrai links da página inicial
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        # Busca artigos na página
        for article in doc.select('article.post'):
            link_elem = article.select_one('header.entry-header h1.entry-title a')
            if link_elem:
                href = link_elem.get('href')
                if href:
                    links.append(href)
        
        # Se não encontrou com seletor específico, tenta alternativo
        if not links:
            for article in doc.select('article'):
                link_elem = article.select_one('h1.entry-title a, header.entry-header a')
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
            
            # Busca artigos nos resultados
            for article in doc.select('article.post'):
                link_elem = article.select_one('header.entry-header h1.entry-title a')
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        links.append(href)
            
            # Se não encontrou com seletor específico, tenta alternativo
            if not links:
                for article in doc.select('article'):
                    link_elem = article.select_one('h1.entry-title a, header.entry-header a')
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
        
        # Extrai data de div.entry-date[itemprop="datePublished"]
        date = None
        date_elem = doc.find('div', {'class': 'entry-date', 'itemprop': 'datePublished'})
        if date_elem:
            # Busca o link <a> dentro do div que contém a data em português
            date_link = date_elem.find('a')
            if date_link:
                date_text = date_link.get_text(strip=True)
                # Tenta fazer parsing de data localizada em português (ex: "16 de novembro de 2025")
                try:
                    date = self._parse_localized_date(date_text)
                except (ValueError, AttributeError):
                    pass
        
        # Fallback: Se não encontrou, usa data atual
        if not date:
            date = datetime.now()
        
        torrents = []
        article = doc.find('article')
        if not article:
            return []
        
        # Extrai título da página (h1.entry-title)
        page_title = ''
        title_elem = article.select_one('h1.entry-title, header.entry-header h1.entry-title')
        if title_elem:
            title_link = title_elem.find('a')
            if title_link:
                page_title = title_link.get_text(strip=True)
            else:
                page_title = title_elem.get_text(strip=True)
        
        # Extrai título original e outras informações do entry-content
        original_title = ''
        year = ''
        sizes = []
        imdb = ''
        
        entry_content = article.select_one('div.entry-content')
        if entry_content:
            # Busca título original - tenta múltiplos padrões
            html_content = str(entry_content)
            
            # Padrão 1: HTML com tags <strong>Título Original</strong>: texto<br />
            # Aceita "Título" (com acento) ou "Titulo" (sem acento)
            # Exemplo: <strong>Título Original</strong>: Rogue One<br />
            title_original_match = re.search(
                r'<strong>T[íi]tulo Original</strong>\s*[:\s]\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</strong|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if title_original_match:
                original_title = title_original_match.group(1).strip()
                # Remove tags HTML restantes que possam ter sido capturadas
                original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                original_title = html.unescape(original_title)
                # Remove quebras de linha e espaços extras
                original_title = re.sub(r'\s+', ' ', original_title).strip()
                # Remove caracteres especiais do final (mas mantém dois pontos no meio)
                original_title = original_title.rstrip(' .,:;-')
            
            # Padrão 2: HTML com tags <b>Título Original:</b> texto<br />
            # Aceita "Título" (com acento) ou "Titulo" (sem acento)
            # Exemplo: <b>Título Original:</b> The Witcher: Blood Origin<br />
            if not original_title:
                title_original_match = re.search(
                    r'<b>T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</b|<strong|$)',
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    # Remove tags HTML restantes que possam ter sido capturadas
                    original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                    original_title = html.unescape(original_title)
                    # Remove quebras de linha e espaços extras
                    original_title = re.sub(r'\s+', ' ', original_title).strip()
                    # Remove caracteres especiais do final (mas mantém dois pontos no meio)
                    original_title = original_title.rstrip(' .,:;-')
            
            # Padrão 3: HTML sem tag <b> inicial, mas com </b> antes do texto
            # Exemplo: Titulo Original:</b> One Battle After Another<br />
            if not original_title:
                title_original_match = re.search(
                    r'T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+?)(?:<br|</p|</b|<strong|$)',
                    html_content,
                    re.IGNORECASE | re.DOTALL
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                    original_title = html.unescape(original_title)
                    original_title = re.sub(r'\s+', ' ', original_title).strip()
                    original_title = original_title.rstrip(' .,:;-')
            
            # Padrão 4: Busca usando BeautifulSoup para encontrar o texto após "Título Original"
            if not original_title:
                # Procura por elementos que contenham "Título Original" ou "Titulo Original"
                for elem in entry_content.find_all(['b', 'strong', 'p', 'span']):
                    text = elem.get_text()
                    if re.search(r'T[íi]tulo Original', text, re.IGNORECASE):
                        # Pega o próximo elemento ou o texto após
                        next_elem = elem.find_next_sibling()
                        if next_elem:
                            original_title = next_elem.get_text(strip=True)
                        else:
                            # Tenta extrair do próprio elemento
                            html_elem = str(elem)
                            match = re.search(r'T[íi]tulo Original[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<]+)', html_elem, re.IGNORECASE | re.DOTALL)
                            if match:
                                original_title = match.group(1).strip()
                                original_title = re.sub(r'<[^>]+>', '', original_title).strip()
                                original_title = html.unescape(original_title)
                        if original_title:
                            original_title = re.sub(r'\s+', ' ', original_title).strip()
                            original_title = original_title.rstrip(' .,:;-')
                            break
            
            # Padrão 5: Texto puro (fallback final)
            if not original_title:
                content_text = entry_content.get_text()
                title_original_match = re.search(
                    r'T[íi]tulo Original[:\s]+([^\n]+?)(?:\n|$)',
                    content_text,
                    re.IGNORECASE
                )
                if title_original_match:
                    original_title = title_original_match.group(1).strip()
                    # Remove caracteres especiais do final
                    original_title = original_title.rstrip(' .,:;-')
            
            # Busca ano - tenta múltiplos padrões
            # Padrão 1: HTML com link <a>2025</a>
            lancamento_match = re.search(
                r'Lançamento[:\s]*</b>\s*<a[^>]*>(\d{4})</a>',
                html_content,
                re.IGNORECASE
            )
            if lancamento_match:
                year = lancamento_match.group(1).strip()
            
            # Padrão 2: Texto puro ou HTML sem link
            if not year:
                lancamento_match = re.search(
                    r'Lançamento[:\s]*</b>\s*(?:<br\s*/?>)?\s*(\d{4})',
                    html_content,
                    re.IGNORECASE
                )
                if lancamento_match:
                    year = lancamento_match.group(1).strip()
            
            # Padrão 3: Busca no texto geral usando find_year_from_text
            if not year:
                content_text = entry_content.get_text()
                y = find_year_from_text(content_text, page_title)
                if y:
                    year = y
            
            # Busca tamanhos - tenta múltiplos padrões
            # Padrão 1: Campo específico "Tamanho:"
            tamanho_match = re.search(
                r'Tamanho[:\s]*</b>\s*(?:<br\s*/?>)?\s*([^<\n]+?)(?:<br|</p|$)',
                html_content,
                re.IGNORECASE | re.DOTALL
            )
            if tamanho_match:
                tamanho_text = re.sub(r'<[^>]+>', '', tamanho_match.group(1)).strip()
                tamanho_text = html.unescape(tamanho_text)
                sizes.extend(find_sizes_from_text(tamanho_text))
            
            # Padrão 2: Busca no texto geral
            if not sizes:
                content_text = entry_content.get_text()
                sizes.extend(find_sizes_from_text(content_text))
            
            # Remove duplicados de tamanhos
            sizes = list(dict.fromkeys(sizes))
            
            # Busca IMDB - tenta múltiplos padrões
            # Padrão 1: Link direto
            imdb_links = entry_content.select('a[href*="imdb.com"]')
            for imdb_link in imdb_links:
                href = imdb_link.get('href', '')
                # Tenta padrão pt/title/tt
                imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
                if imdb_match:
                    imdb = imdb_match.group(1)
                    break
                # Tenta padrão title/tt (sem /pt/)
                imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                if imdb_match:
                    imdb = imdb_match.group(1)
                    break
        
        # Se não encontrou título original, usa o título da página
        if not original_title:
            original_title = page_title
        
        # Extrai links magnet - busca TODOS os magnets no entry-content
        magnet_links = []
        if entry_content:
            for magnet in entry_content.select('a[href^="magnet:"]'):
                href = magnet.get('href', '')
                if href:
                    # Remove entidades HTML
                    href = href.replace('&amp;', '&').replace('&#038;', '&')
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
                
                fallback_title = original_title if original_title else page_title
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
                
                # Processa trackers usando função utilitária
                trackers = process_trackers(magnet_data)
                
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

