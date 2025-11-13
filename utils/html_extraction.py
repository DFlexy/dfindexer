"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import html
from datetime import datetime
from typing import List, Optional
from bs4 import BeautifulSoup, Tag
from urllib.parse import unquote

from utils.date_parser import parse_date_from_string


def extract_date_from_page(doc: BeautifulSoup, url: str) -> datetime:
    """
    Extrai data de publicação de uma página HTML.
    Tenta múltiplas fontes: URL, meta tag article:published_time, ou usa data atual.
    
    Args:
        doc: BeautifulSoup do documento HTML
        url: URL da página
        
    Returns:
        datetime da publicação (ou datetime.now() se não encontrar)
    """
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


def extract_imdb_from_page(doc: BeautifulSoup, selectors: Optional[List[str]] = None) -> str:
    """
    Extrai ID do IMDB de uma página HTML.
    
    Args:
        doc: BeautifulSoup do documento HTML
        selectors: Lista de seletores CSS para buscar links (padrão: ['a'])
        
    Returns:
        ID do IMDB (ex: 'tt1234567') ou string vazia se não encontrar
    """
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


def extract_magnet_links(doc: BeautifulSoup, container_selectors: List[str], fallback_selectors: Optional[List[str]] = None) -> List[str]:
    """
    Extrai links magnet de uma página HTML.
    Tenta primeiro nos containers especificados, depois em fallback.
    
    Args:
        doc: BeautifulSoup do documento HTML
        container_selectors: Lista de seletores CSS para containers principais
        fallback_selectors: Lista de seletores CSS para busca alternativa (padrão: ['a[href^="magnet:"]'])
        
    Returns:
        Lista de links magnet encontrados
    """
    if fallback_selectors is None:
        fallback_selectors = ['a[href^="magnet:"]']
    
    magnet_links = []
    
    # Tenta primeiro nos containers especificados
    for container_selector in container_selectors:
        container = doc.select_one(container_selector)
        if container:
            magnets = container.select('a[href^="magnet:"]')
            for magnet in magnets:
                href = magnet.get('href', '')
                if href:
                    href = href.replace('&#038;', '&').replace('&amp;', '&')
                    magnet_links.append(html.unescape(href))
            if magnet_links:
                return magnet_links
    
    # Fallback: busca em qualquer lugar
    for fallback_selector in fallback_selectors:
        magnets = doc.select(fallback_selector)
        for magnet in magnets:
            href = magnet.get('href', '')
            if href:
                href = href.replace('&#038;', '&').replace('&amp;', '&')
                magnet_links.append(html.unescape(href))
        if magnet_links:
            return magnet_links
    
    return []


def extract_text_from_element(elem: Tag, strip: bool = True) -> str:
    """
    Extrai texto de um elemento BeautifulSoup, removendo tags HTML.
    
    Args:
        elem: Tag BeautifulSoup
        strip: Se True, remove espaços em branco no início e fim
        
    Returns:
        Texto extraído
    """
    if not elem:
        return ''
    
    text = elem.get_text(separator=' ', strip=strip)
    return text


def extract_original_title_from_text(text: str, patterns: List[str]) -> str:
    """
    Extrai título original de um texto usando padrões comuns.
    
    Args:
        text: Texto para buscar
        patterns: Lista de padrões para buscar (ex: ['Nome Original:', 'Título Original:'])
        
    Returns:
        Título original encontrado ou string vazia
    """
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

