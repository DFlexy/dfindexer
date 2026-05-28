# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def extract_imdb_from_element(element: BeautifulSoup) -> Optional[str]:
    if not element:
        return None
    
    for a in element.select('a[href*="imdb.com"]'):
        href = a.get('href', '')
        
        imdb_match = re.search(r'imdb\.com/pt/title/(tt\d+)', href)
        if imdb_match:
            return imdb_match.group(1)
        
        imdb_match = re.search(r'imdb\.com/title/(tt\d+)', href)
        if imdb_match:
            return imdb_match.group(1)
    
    return None

def extract_imdb_from_page(doc: BeautifulSoup, content_selectors: Optional[list] = None) -> str:
    if not doc:
        return ''
    
    if not content_selectors:
        content_selectors = [
            'div#informacoes',
            'div.entry-content',
            'div.content',
            'article',
            'div.post',
            'main',
        ]
    
    imdb = ''
    
    imdb_strong = doc.find('strong', string=re.compile(r'IMDb', re.I))
    if imdb_strong:
        parent = imdb_strong.parent
        if parent:
            imdb = extract_imdb_from_element(parent)
            if imdb:
                return imdb
    
    imdb_em = doc.find('em', string=re.compile(r'IMDb:', re.I))
    if imdb_em:
        parent = imdb_em.parent
        if parent:
            imdb = extract_imdb_from_element(parent)
            if imdb:
                return imdb
    
    for selector in content_selectors:
        content_div = doc.select_one(selector)
        if content_div:
            imdb = extract_imdb_from_element(content_div)
            if imdb:
                return imdb
    
    imdb = extract_imdb_from_element(doc)
    
    return imdb or ''

