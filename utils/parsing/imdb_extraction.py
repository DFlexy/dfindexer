# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

"""Extração de ID IMDb (ttNNNNNNNN) a partir do HTML da página de um post."""
import re
from typing import Optional
from bs4 import BeautifulSoup
from bs4.element import Tag

_RE_IMDB_PT = re.compile(r'imdb\.com/pt/title/(tt\d+)')
_RE_IMDB = re.compile(r'imdb\.com/title/(tt\d+)')


def _match_imdb_href(href: str) -> Optional[str]:
    if not href:
        return None
    m = _RE_IMDB_PT.search(href)
    if m:
        return m.group(1)
    m = _RE_IMDB.search(href)
    if m:
        return m.group(1)
    return None


def extract_imdb_from_soup(
    article: Tag,
    *,
    content_div: Optional[Tag] = None,
    label_tag: str = 'strong',
    label_regex: str = r'IMDb',
) -> str:
    """Extrai o ID IMDb (ex.: tt9813792) de um <article>.

    Estratégia (ordem):
    1. Procura por <strong>/<b> com texto 'IMDb' e varre links imdb.com no parent.
    2. Varre links imdb.com dentro de `content_div` (se fornecido) ou do article.
    3. Fallback: varre todos os <a> imdb.com no article.

    Retorna string vazia se não encontrar.
    """
    imdb = ''

    if article is None:
        return imdb

    try:
        label_re = re.compile(label_regex, re.I)
    except re.error:
        label_re = re.compile(r'IMDb', re.I)

    for label_name in (label_tag, 'strong', 'b'):
        label_elem = article.find(label_name, string=label_re)
        if label_elem:
            parent = label_elem.parent
            if parent:
                for a in parent.select('a[href*="imdb.com"]'):
                    imdb = _match_imdb_href(a.get('href', ''))
                    if imdb:
                        return imdb

    scan_root = content_div or article
    for a in scan_root.select('a[href*="imdb.com"]'):
        imdb = _match_imdb_href(a.get('href', ''))
        if imdb:
            return imdb

    for a in article.select('a[href*="imdb.com"]'):
        imdb = _match_imdb_href(a.get('href', ''))
        if imdb:
            return imdb

    return imdb
