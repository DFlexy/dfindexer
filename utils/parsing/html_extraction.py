"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import html
import logging
from datetime import datetime
from typing import List, Optional
from bs4 import BeautifulSoup, Tag
from urllib.parse import unquote
import requests

from utils.parsing.date_parser import parse_date_from_string

logger = logging.getLogger(__name__)


# Extrai data de publicação de uma página HTML - tenta múltiplas fontes: URL, meta tag article:published_time, ou usa data atual
def extract_date_from_page(doc: BeautifulSoup, url: str) -> datetime:
    # Tenta extrair da URL primeiro
    date = parse_date_from_string(url)
    if date:
        return date
    
    # Tenta extrair da meta tag article:published_time
    date_meta = doc.find('meta', {'property': 'article:published_time'})
    if date_meta:
        date_content = date_meta.get('content', '')
        if date_content:
            try:
                date_content = date_content.replace('Z', '+00:00')
                date = datetime.fromisoformat(date_content)
                if date:
                    return date
            except (ValueError, AttributeError):
                pass
    
    # Fallback: usa data atual
    return datetime.now()


# Extrai ID do IMDB de uma página HTML - retorna ID do IMDB (ex: 'tt1234567') ou string vazia se não encontrar
def extract_imdb_from_page(doc: BeautifulSoup, selectors: Optional[List[str]] = None) -> str:
    if selectors is None:
        selectors = ['a']
    
    for selector in selectors:
        for link_elem in doc.select(selector):
            href = link_elem.get('href', '')
            if 'imdb.com' in href:
                imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
                if imdb_match:
                    return imdb_match.group(1)
    
    return ''


# Extrai links magnet de uma página HTML - tenta primeiro nos containers especificados, depois em fallback
# Também resolve links protegidos (protlink, encurtador, etc.) automaticamente
def extract_magnet_links(
    doc: BeautifulSoup, 
    container_selectors: List[str], 
    fallback_selectors: Optional[List[str]] = None,
    session: Optional[requests.Session] = None,
    base_url: str = '',
    redis=None
) -> List[str]:
    if fallback_selectors is None:
        fallback_selectors = ['a[href^="magnet:"]']
    
    magnet_links = []
    
    # Seletores para buscar links protegidos também
    protected_selectors = ['a[href*="protlink"], a[href*="encurtador"], a[href*="encurta"], a[href*="get.php"], a[href*="systemads"]']
    
    # Tenta primeiro nos containers especificados
    for container_selector in container_selectors:
        container = doc.select_one(container_selector)
        if container:
            # Busca links magnet diretos
            magnets = container.select('a[href^="magnet:"]')
            for magnet in magnets:
                href = magnet.get('href', '')
                if href:
                    href = href.replace('&#038;', '&').replace('&amp;', '&')
                    unescaped_href = html.unescape(href)
                    if unescaped_href not in magnet_links:
                        magnet_links.append(unescaped_href)
            
            # Busca links protegidos e resolve
            if session:
                from utils.parsing.link_resolver import is_protected_link
                for protected_selector in protected_selectors:
                    protected_links = container.select(protected_selector)
                    for protected_link in protected_links:
                        href = protected_link.get('href', '')
                        if href and is_protected_link(href):
                            try:
                                from utils.parsing.link_resolver import resolve_protected_link
                                resolved_magnet = resolve_protected_link(href, session, base_url, redis=redis)
                                if resolved_magnet and resolved_magnet not in magnet_links:
                                    magnet_links.append(resolved_magnet)
                            except Exception as e:
                                logger.debug(f"Erro ao resolver link protegido {href}: {e}")
                                continue
            
            if magnet_links:
                return magnet_links
    
    # Fallback: busca em qualquer lugar
    for fallback_selector in fallback_selectors:
        magnets = doc.select(fallback_selector)
        for magnet in magnets:
            href = magnet.get('href', '')
            if href:
                href = href.replace('&#038;', '&').replace('&amp;', '&')
                unescaped_href = html.unescape(href)
                if unescaped_href not in magnet_links:
                    magnet_links.append(unescaped_href)
    
    # Busca links protegidos no fallback também
    if session:
        from utils.parsing.link_resolver import is_protected_link
        for protected_selector in protected_selectors:
            protected_links = doc.select(protected_selector)
            for protected_link in protected_links:
                href = protected_link.get('href', '')
                if href and is_protected_link(href):
                    try:
                        from utils.parsing.link_resolver import resolve_protected_link
                        resolved_magnet = resolve_protected_link(href, session, base_url, redis=redis)
                        if resolved_magnet and resolved_magnet not in magnet_links:
                            magnet_links.append(resolved_magnet)
                    except Exception as e:
                        logger.debug(f"Erro ao resolver link protegido {href}: {e}")
                        continue
    
    return magnet_links


# Extrai texto de um elemento BeautifulSoup, removendo tags HTML
def extract_text_from_element(elem: Tag, strip: bool = True) -> str:
    if not elem:
        return ''
    
    text = elem.get_text(separator=' ', strip=strip)
    return text


# Extrai título original de um texto usando padrões comuns
def extract_original_title_from_text(text: str, patterns: List[str]) -> str:
    for pattern in patterns:
        if pattern in text:
            # Tenta extrair após o padrão
            parts = text.split(pattern, 1)
            if len(parts) > 1:
                extracted = parts[1].strip()
                # Remove caracteres de parada comuns
                extracted = re.sub(r'[.!?].*$', '', extracted)
                extracted = extracted.rstrip(' .,:;-')
                # Limita tamanho
                if len(extracted) > 200:
                    extracted = extracted[:200]
                if extracted:
                    return extracted
    
    return ''

