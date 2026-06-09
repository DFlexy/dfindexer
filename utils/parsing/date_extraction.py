# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Callable
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def parse_date_from_string(date_str: str) -> Optional[datetime]:
    patterns = [
        (r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),
        (r'\d{2}-\d{2}-\d{4}', '%d-%m-%Y'),
        (r'\d{2}/\d{2}/\d{4}', '%d/%m/%Y'),
        (r'\d{1,2},? [A-Za-z]+', '%d, %B'),
        (r'[A-Za-z]+ \d{1,2},? \d{4}', '%B %d, %Y'),
    ]
    
    for pattern, fmt in patterns:
        match = re.search(pattern, date_str)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    
    year_pattern = r'\b(19|20)\d{2}\b'
    year_match = re.search(year_pattern, date_str)
    if year_match:
        year = int(year_match.group(0))
        current_year = datetime.now().year
        if year != current_year:
            return datetime(year, 12, 31)
    
    return None

def _extract_release_year_starck(doc: BeautifulSoup) -> Optional[int]:
    """Starck: <div>Lançamentos 2025</div>"""
    lancamentos_div = doc.find('div', string=re.compile(r'Lançamentos?\s+\d{4}', re.I))
    if lancamentos_div:
        year_match = re.search(r'(19|20)\d{2}', lancamentos_div.get_text())
        if year_match:
            year = int(year_match.group(0))
            current_year = datetime.now().year
            if year != current_year:
                return year
    return None

def _extract_release_year_tfilme(doc: BeautifulSoup) -> Optional[int]:
    """Torrent dos Filmes: <b>Lançamento:</b> <a href="...">2025</a><br />"""
    for b_tag in doc.find_all('b'):
        b_text = b_tag.get_text(strip=True).lower()
        if 'lançamento' in b_text or 'lancamento' in b_text:
            parent = b_tag.parent
            if parent:
                parent_html = str(parent)
                year_match = re.search(r'(?i)Lançamento\s*:?\s*(?:</b>|</strong>)?\s*(?:<a[^>]*>)?\s*(\d{4})', parent_html)
                if year_match:
                    year = int(year_match.group(1))
                    current_year = datetime.now().year
                    if year != current_year:
                        return year
    return None

def _extract_release_year_bludv(doc: BeautifulSoup) -> Optional[int]:
    """Bludv: <span style='...'><strong><em>Lançamento:</em></strong> 2025</span><br />"""
    for span in doc.find_all('span'):
        span_html = str(span)
        if re.search(r'(?i)Lançamento', span_html):
            year_match = re.search(r'(?i)Lançamento\s*:?\s*(?:</em>|</strong>)?\s*(\d{4})', span_html)
            if year_match:
                year = int(year_match.group(1))
                current_year = datetime.now().year
                if year != current_year:
                    return year
    return None

def _extract_release_year_comand(doc: BeautifulSoup) -> Optional[int]:
    """Comando: <b>Lançamento:</b> <a href="...">2025</a><br />"""
    for b_tag in doc.find_all('b'):
        b_text = b_tag.get_text(strip=True).lower()
        if 'lançamento' in b_text or 'lancamento' in b_text:
            parent = b_tag.parent
            if parent:
                parent_html = str(parent)
                year_match = re.search(r'(?i)Lançamento\s*:?\s*(?:</b>|</strong>)?\s*(?:<a[^>]*>)?\s*(\d{4})', parent_html)
                if year_match:
                    year = int(year_match.group(1))
                    current_year = datetime.now().year
                    if year != current_year:
                        return year
    return None

def _extract_release_year_rede(doc: BeautifulSoup) -> Optional[int]:
    """Rede: <strong>Lançamento</strong>: 2025<br>"""
    for strong_tag in doc.find_all('strong'):
        strong_text = strong_tag.get_text(strip=True).lower()
        if 'lançamento' in strong_text or 'lancamento' in strong_text:
            parent = strong_tag.parent
            if parent:
                parent_text = parent.get_text()
                year_match = re.search(r'(?i)Lançamento\s*:?\s*(\d{4})', parent_text)
                if year_match:
                    year = int(year_match.group(1))
                    current_year = datetime.now().year
                    if year != current_year:
                        return year
    return None

SCRAPER_RELEASE_YEAR_EXTRACTORS: Dict[str, Callable[[BeautifulSoup], Optional[int]]] = {
    'starck': _extract_release_year_starck,
    'tfilme': _extract_release_year_tfilme,
    'bludv': _extract_release_year_bludv,
    'comand': _extract_release_year_comand,
    'rede': _extract_release_year_rede,
}

def extract_release_year_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None) -> Optional[int]:
    """Extrai o ano do campo "Lançamento" do HTML"""
    if scraper_type and scraper_type in SCRAPER_RELEASE_YEAR_EXTRACTORS:
        extractor = SCRAPER_RELEASE_YEAR_EXTRACTORS[scraper_type]
        try:
            year = extractor(doc)
            if year:
                return year
        except Exception as e:
            logger.debug(f"Erro ao extrair ano com regra específica do scraper {scraper_type}: {e}")
    
    for extractor in SCRAPER_RELEASE_YEAR_EXTRACTORS.values():
        try:
            year = extractor(doc)
            if year:
                return year
        except Exception:
            continue
    

    doc_text = doc.get_text()
    year_match = re.search(r'(?i)Lançamento\s*:?\s*(\d{4})', doc_text)
    if year_match:
        year = int(year_match.group(1))
        current_year = datetime.now().year
        if year != current_year:
            return year
    
    return None

def extract_release_year_date_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None) -> Optional[datetime]:
    """Extrai o ano do campo "Lançamento" e retorna como datetime(YYYY, 12, 31)"""
    year = extract_release_year_from_page(doc, scraper_type)
    if year:
        return datetime(year, 12, 31)
    return None

def extract_date_from_page(doc: BeautifulSoup, url: str, scraper_type: Optional[str] = None) -> Optional[datetime]:
    """Extrai data de publicação da URL, meta tags ou campo Lançamento."""
    date = parse_date_from_string(url)
    if date:
        return date
    
    release_year_date = extract_release_year_date_from_page(doc, scraper_type)
    if release_year_date:
        return release_year_date
    
    return None

