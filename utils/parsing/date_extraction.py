"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Callable
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ============================================================================
# PARSING DE STRINGS DE DATA (Função utilitária de baixo nível)
# ============================================================================

def parse_date_from_string(date_str: str) -> Optional[datetime]:
    """
    Extrai data de uma string usando padrões comuns.
    
    Args:
        date_str: String que pode conter uma data
    
    Returns:
        datetime ou None se não encontrar
    """
    patterns = [
        (r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),
        (r'\d{2}-\d{2}-\d{4}', '%d-%m-%Y'),
        (r'\d{2}/\d{2}/\d{4}', '%d/%m/%Y'),
        (r'\d{1,2},? [A-Za-z]+', '%d, %B'),  # 4, October
        (r'[A-Za-z]+ \d{1,2},? \d{4}', '%B %d, %Y'),  # October 4, 2020
    ]
    
    for pattern, fmt in patterns:
        match = re.search(pattern, date_str)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    
    # Fallback: Se não encontrou data completa, tenta extrair apenas o ano
    # Se o ano não for o ano atual, usa 31/12/YYYY como fallback
    year_pattern = r'\b(19|20)\d{2}\b'  # Anos de 1900-2099
    year_match = re.search(year_pattern, date_str)
    if year_match:
        year = int(year_match.group(0))
        current_year = datetime.now().year
        # Se o ano não for o ano atual, usa último dia do ano como fallback
        if year != current_year:
            return datetime(year, 12, 31)
    
    return None


# ============================================================================
# REGRAS ESPECÍFICAS POR SCRAPER - Campo "Lançamento"
# ============================================================================

def _extract_release_year_starck(doc: BeautifulSoup) -> Optional[int]:
    """
    Starck: <div>Lançamentos 2025</div>
    """
    lancamentos_div = doc.find('div', string=re.compile(r'Lançamentos?\s+\d{4}', re.I))
    if lancamentos_div:
        year_match = re.search(r'(19|20)\d{2}', lancamentos_div.get_text())
        if year_match:
            year = int(year_match.group(0))
            current_year = datetime.now().year
            if year != current_year:
                return year
    return None


def _extract_release_year_nerd(doc: BeautifulSoup) -> Optional[int]:
    """
    Nerd: <b>Lançamento :</b> 2022<br />
    """
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
                parent_text = parent.get_text()
                year_match = re.search(r'(?i)Lançamento\s*:?\s*(\d{4})', parent_text)
                if year_match:
                    year = int(year_match.group(1))
                    current_year = datetime.now().year
                    if year != current_year:
                        return year
    return None


def _extract_release_year_tfilme(doc: BeautifulSoup) -> Optional[int]:
    """
    Torrent dos Filmes: <b>Lançamento:</b> <a href="...">2025</a><br />
    """
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
    """
    Bludv: <span style='...'><strong><em>Lançamento:</em></strong> 2025</span><br />
    """
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
    """
    Comando: <b>Lançamento:</b> <a href="...">2025</a><br />
    """
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
    """
    Rede: <strong>Lançamento</strong>: 2025<br>
    """
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


def _extract_release_year_baixafilmes(doc: BeautifulSoup) -> Optional[int]:
    """
    Baixa Filmes: <meta property="og:updated_time" content="2025-12-12T22:12:38-03:00" />
    """
    meta_updated = doc.find('meta', {'property': 'og:updated_time'})
    if meta_updated:
        content = meta_updated.get('content', '')
        if content:
            date_match = re.search(r'(\d{4})-\d{2}-\d{2}', content)
            if date_match:
                year = int(date_match.group(1))
                current_year = datetime.now().year
                if year != current_year:
                    return year
    return None


# Mapeamento de scrapers para suas funções de extração específicas
SCRAPER_RELEASE_YEAR_EXTRACTORS: Dict[str, Callable[[BeautifulSoup], Optional[int]]] = {
    'starck': _extract_release_year_starck,
    'nerd': _extract_release_year_nerd,
    'tfilme': _extract_release_year_tfilme,
    'bludv': _extract_release_year_bludv,
    'comand': _extract_release_year_comand,
    'rede': _extract_release_year_rede,
    'baixafilmes': _extract_release_year_baixafilmes,
}


# ============================================================================
# FUNÇÕES GENÉRICAS DE EXTRAÇÃO
# ============================================================================

def extract_release_year_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None) -> Optional[int]:
    """
    Extrai o ano do campo "Lançamento" do HTML.
    
    Args:
        doc: Documento BeautifulSoup
        scraper_type: Tipo do scraper (starck, nerd, tfilme, etc.) para usar regra específica
    
    Returns:
        Ano extraído (int) ou None se não encontrar ou se o ano for o ano atual
    """
    # Tenta primeiro com regra específica do scraper
    if scraper_type and scraper_type in SCRAPER_RELEASE_YEAR_EXTRACTORS:
        extractor = SCRAPER_RELEASE_YEAR_EXTRACTORS[scraper_type]
        try:
            year = extractor(doc)
            if year:
                return year
        except Exception as e:
            logger.debug(f"Erro ao extrair ano com regra específica do scraper {scraper_type}: {e}")
    
    # Fallback: tenta todas as regras específicas
    for extractor in SCRAPER_RELEASE_YEAR_EXTRACTORS.values():
        try:
            year = extractor(doc)
            if year:
                return year
        except Exception:
            continue
    
    # Último fallback: busca genérica por "Lançamento" seguido de ano
    doc_text = doc.get_text()
    year_match = re.search(r'(?i)Lançamento\s*:?\s*(\d{4})', doc_text)
    if year_match:
        year = int(year_match.group(1))
        current_year = datetime.now().year
        if year != current_year:
            return year
    
    return None


def extract_release_year_date_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None) -> Optional[datetime]:
    """
    Extrai o ano do campo "Lançamento" e retorna como datetime(YYYY, 12, 31).
    
    Args:
        doc: Documento BeautifulSoup
        scraper_type: Tipo do scraper para usar regra específica
    
    Returns:
        datetime(YYYY, 12, 31) ou None se não encontrar ou se o ano for o ano atual
    """
    year = extract_release_year_from_page(doc, scraper_type)
    if year:
        return datetime(year, 12, 31)
    return None


def extract_date_from_page(doc: BeautifulSoup, url: str, scraper_type: Optional[str] = None) -> Optional[datetime]:
    """
    Extrai data de publicação do link da página (URL), meta tags e do campo "Lançamento".
    
    Ordem de tentativas:
    1. URL (padrões completos ou apenas ano)
    2. Meta tag og:updated_time (para baixafilmes)
    3. Campo "Lançamento" (usando regra específica do scraper se disponível)
    
    Args:
        doc: Documento BeautifulSoup
        url: URL da página
        scraper_type: Tipo do scraper para usar regra específica no campo "Lançamento"
    
    Returns:
        datetime ou None se não encontrar (fallback será metadata)
    """
    # Tentativa 1: Extrai da URL
    date = parse_date_from_string(url)
    if date:
        return date
    
    # Tentativa 2: Para baixafilmes, tenta extrair data completa de meta tags
    if scraper_type == 'baixafilmes':
        # Busca manualmente em todas as meta tags (mais confiável)
        all_meta = doc.find_all('meta')
        meta_updated = None
        
        # Primeiro: busca exata por og:updated_time
        for meta in all_meta:
            prop = meta.get('property', '')
            if prop == 'og:updated_time':
                meta_updated = meta
                break
        
        # Segundo: se não encontrou, tenta via name
        if not meta_updated:
            for meta in all_meta:
                prop = meta.get('name', '')
                if prop == 'og:updated_time':
                    meta_updated = meta
                    break
        
        # Terceiro: busca por outras meta tags de data
        if not meta_updated:
            for meta in all_meta:
                prop = meta.get('property', '') or meta.get('name', '')
                prop_lower = prop.lower()
                if any(mp in prop_lower for mp in ['article:published_time', 'article:modified_time', 'datepublished', 'datemodified', 'published_time', 'modified_time']):
                    meta_updated = meta
                    break
        
        if meta_updated:
            content = meta_updated.get('content', '')
            if content:
                try:
                    # Tenta parsear o formato ISO 8601 completo: 2025-11-30T16:34:11-03:00
                    # Remove timezone para simplificar
                    date_str = content.split('T')[0]  # Pega apenas a parte da data: 2025-11-30
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                    return date
                except (ValueError, AttributeError):
                    # Se falhar, tenta extrair apenas o ano (fallback)
                    year_match = re.search(r'(\d{4})-\d{2}-\d{2}', content)
                    if year_match:
                        year = int(year_match.group(1))
                        current_year = datetime.now().year
                        if year != current_year:
                            return datetime(year, 12, 31)
        else:
            # Meta tag não encontrada - continua para próximo fallback
            pass
    
    # Tentativa 3: Extrai ano do campo "Lançamento" (se não encontrou na URL nem na meta tag)
    release_year_date = extract_release_year_date_from_page(doc, scraper_type)
    if release_year_date:
        return release_year_date
    
    # Não encontrou na URL, meta tag nem no campo "Lançamento" - retorna None (fallback será metadata)
    return None

