# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import base64
import codecs
import hashlib
import html
import json
import logging
import re
import string
import threading
import time
import zlib
from datetime import datetime
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from cache.store import get_redis_client, protlink_key
from magnet.parser import MagnetParser

def process_trackers(magnet_data: Dict) -> List[str]:
    trackers = []
    raw_trackers = magnet_data.get('trackers', [])

    for tracker in raw_trackers:
        tracker = tracker.replace('&#038;', '&').replace('&amp;', '&')

        try:
            tracker = unquote(tracker)
        except Exception:
            pass

        tracker_clean = tracker.strip()
        if tracker_clean:
            trackers.append(tracker_clean)

    return trackers

def extract_trackers_from_magnet(magnet_link: str) -> List[str]:
    try:
        magnet_data = MagnetParser.parse(magnet_link)
        return process_trackers(magnet_data)
    except Exception:
        return []

_RE_LABELED_FIELD_VARIANTS = (
    r'(?i)(?:<b>|<strong>)\s*{label}\s*(?:</b>|</strong>)\s*:\s*([^<\n\r]+)',
    r'(?i)(?:<b>|<strong>)\s*{label}\s*:\s*(?:</b>|</strong>)\s*([^<\n\r]+)',
    r'(?i){label}\s*:\s*([^<\n\r]+)',
)


def extract_labeled_value(html_content: str, labels: List[str]) -> str:
    for label in labels:
        for variant in _RE_LABELED_FIELD_VARIANTS:
            pattern = variant.replace('{label}', re.escape(label))
            match = re.search(pattern, html_content)
            if match:
                value = match.group(1).strip()
                value = re.sub(r'<[^>]+>', '', value)
                return html.unescape(value).strip()
    return ''


def extract_labeled_value_from_text(
    text: str, labels: List[str], stop_words: List[str]
) -> str:
    for label in labels:
        for variant in (f'{label}:', f'{label} :'):
            if variant not in text:
                continue
            title_part = text.split(variant, 1)[1].strip()
            for stop_word in stop_words:
                if stop_word in title_part:
                    title_part = title_part[:title_part.index(stop_word)]
                    break
            lines = title_part.split('\n')
            if lines:
                return lines[0].strip()
    return ''

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
    time_el = doc.select_one('time[itemprop="datePublished"]')
    if time_el:
        year_match = re.search(r'(\d{4})', time_el.get_text(strip=True) or '')
        if not year_match:
            year_match = re.search(r'(\d{4})', time_el.get('datetime') or '')
        if year_match:
            year = int(year_match.group(1))
            current_year = datetime.now().year
            if year != current_year:
                return year

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

def _extract_release_year_torrentclaw(doc: BeautifulSoup) -> Optional[int]:
    for script in doc.select('script[type="application/ld+json"]'):
        raw = (script.string or script.get_text() or '').strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            year_match = re.search(r'"datePublished"\s*:\s*"[^"]*((?:19|20)\d{2})', raw)
            if year_match:
                year = int(year_match.group(1))
                if year != datetime.now().year:
                    return year
            continue
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and isinstance(data.get('@graph'), list):
            candidates = data['@graph']
        for item in candidates:
            if not isinstance(item, dict):
                continue
            type_name = str(item.get('@type') or '')
            if type_name not in ('TVSeries', 'Movie', 'TVEpisode'):
                continue
            year_match = re.search(r'((?:19|20)\d{2})', str(item.get('datePublished') or ''))
            if year_match:
                year = int(year_match.group(1))
                if year != datetime.now().year:
                    return year
    return None

SCRAPER_RELEASE_YEAR_EXTRACTORS: Dict[str, Callable[[BeautifulSoup], Optional[int]]] = {
    'starck': _extract_release_year_starck,
    'tfilme': _extract_release_year_tfilme,
    'bludv': _extract_release_year_bludv,
    'comand': _extract_release_year_comand,
    'rede': _extract_release_year_rede,
    'torrentclaw': _extract_release_year_torrentclaw,
}

def extract_release_year_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None) -> Optional[int]:
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
    year = extract_release_year_from_page(doc, scraper_type)
    if year:
        return datetime(year, 12, 31)
    return None

def extract_date_from_page(doc: BeautifulSoup, url: str, scraper_type: Optional[str] = None) -> Optional[datetime]:
    date = parse_date_from_string(url)
    if date:
        return date

    release_year_date = extract_release_year_date_from_page(doc, scraper_type)
    if release_year_date:
        return release_year_date

    return None

def detect_audio_from_idioma_text(idioma_text: str) -> Optional[str]:
    if not idioma_text:
        return None
    lower = idioma_text.lower()

    detectados = []
    if 'português' in lower or 'portugues' in lower or 'pt-br' in lower or 'ptbr' in lower or 'pt br' in lower:
        detectados.append('português')
    if 'inglês' in lower or 'ingles' in lower or 'english' in lower:
        detectados.append('inglês')
    if 'japonês' in lower or 'japones' in lower or 'japanese' in lower or 'jap' in lower:
        detectados.append('japonês')

    detectados = detectados[:3]
    if len(detectados) >= 2:
        if 'português' in detectados and 'inglês' in detectados:
            return 'dual'
        if 'português' in detectados:
            return 'dual'
        return detectados[0]
    if len(detectados) == 1:
        return detectados[0]
    return None


def detect_audio_from_html(html_content: str) -> Optional[str]:
    if not html_content:
        return None

    text_content = re.sub(r'<[^>]+>', ' ', html_content)
    text_content = re.sub(r'\s+', ' ', text_content)

    has_idioma_label = re.search(r'(?i)(?:Áudio|Idioma)\s*:?', html_content)
    has_legenda_label = re.search(r'(?i)Legenda\s*:?', html_content)

    has_portugues = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*(?:<[^>]+>)*\s*.*?Português', html_content, re.DOTALL)
    if not has_portugues:
        has_portugues = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*.*?Português', text_content)

    has_multi = re.search(r'(?i)Multi-?Áudio|Multi-?Audio', html_content)

    has_ingles_audio = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*(?:<[^>]+>)*\s*.*?(?:Inglês|Ingles|English)', html_content, re.DOTALL)
    if not has_ingles_audio:
        has_ingles_audio = re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*.*?(?:Inglês|Ingles|English)', text_content)

    has_ingles = re.search(r'(?i)Inglês|Ingles|English', html_content)

    has_legenda_legendado = re.search(r'(?i)Legenda\s*:?\s*(?:<[^>]+>)*\s*.*?Legendado', html_content, re.DOTALL)
    if not has_legenda_legendado:
        has_legenda_legendado = re.search(r'(?i)Legenda\s*:?\s*.*?Legendado', text_content)

    has_legenda_ingles = re.search(r'(?i)Legenda\s*:?\s*(?:<[^>]+>)*\s*.*?(?:Inglês|Ingles|English)', html_content, re.DOTALL)
    if not has_legenda_ingles:
        has_legenda_ingles = re.search(r'(?i)Legenda\s*:?\s*.*?(?:Inglês|Ingles|English)', text_content)

    has_legenda_portugues = re.search(r'(?i)Legenda\s*:?\s*(?:<[^>]+>)*\s*.*?(?:PT-BR|PTBR|Português|Portugues|PT)', html_content, re.DOTALL)
    if not has_legenda_portugues:
        has_legenda_portugues = re.search(r'(?i)Legenda\s*:?\s*.*?(?:PT-BR|PTBR|Português|Portugues|PT)', text_content)

    if has_portugues:
        if has_multi or has_ingles_audio or has_ingles:
            return 'dual'
        else:
            return 'português'

    if has_ingles_audio:
        if has_legenda_portugues:
            return 'legendado'
        return None


    if has_idioma_label and has_ingles:
        if has_legenda_portugues:
            return 'legendado'
        return None

    if has_legenda_legendado or has_legenda_portugues or (has_legenda_ingles and not has_portugues):
        return 'legendado'

    return None

def add_audio_tag_if_needed(title: str, magnet_processed: str, info_hash: Optional[str] = None, skip_metadata: bool = False, audio_info_from_html: Optional[str] = None, audio_html_content: Optional[str] = None) -> str:
    title = title.replace('[Brazilian]', '').replace('[Eng]', '').replace('[Jap]', '')
    title = re.sub(r'\s+', ' ', title).strip()

    has_brazilian = '[Brazilian]' in title
    has_eng = '[Eng]' in title
    has_jap = '[Jap]' in title

    has_brazilian_audio = False
    has_eng_audio = False
    has_japones_audio = False

    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'português' in audio_info_str or 'portugues' in audio_info_str:
            has_brazilian_audio = True

    if magnet_processed and not has_brazilian_audio:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'dublado' in release_lower or 'nacional' in release_lower or 'portugues' in release_lower or 'português' in release_lower:
            has_brazilian_audio = True

    if info_hash and not skip_metadata and not has_brazilian_audio:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'dual' in metadata_name or 'dublado' in metadata_name or 'nacional' in metadata_name or 'portugues' in metadata_name or 'português' in metadata_name:
                    has_brazilian_audio = True
        except Exception:
            pass

    if info_hash and not skip_metadata and not has_brazilian_audio:
        try:
            from utils.text import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'dual' in cross_release_lower or 'dublado' in cross_release_lower or 'nacional' in cross_release_lower or 'portugues' in cross_release_lower or 'português' in cross_release_lower:
                        has_brazilian_audio = True
        except Exception:
            pass

    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'inglês' in audio_info_str or 'ingles' in audio_info_str or 'english' in audio_info_str or 'legendado' in audio_info_str:
            has_eng_audio = True

    if magnet_processed and not has_eng_audio:
        release_lower = magnet_processed.lower()
        if 'dual' in release_lower or 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            has_eng_audio = True

    if info_hash and not skip_metadata and not has_eng_audio:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'dual' in metadata_name or 'legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name):
                    has_eng_audio = True
        except Exception:
            pass

    if info_hash and not skip_metadata and not has_eng_audio:
        try:
            from utils.text import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'dual' in cross_release_lower or 'legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower):
                        has_eng_audio = True
        except Exception:
            pass

    if audio_html_content and not has_eng_audio:
        if re.search(r'(?i)(?:Áudio|Idioma)\s*:?\s*(?:<[^>]+>)*\s*.*?(?:Inglês|Ingles|English)', audio_html_content, re.DOTALL):
            has_eng_audio = True

    if audio_info_from_html:
        audio_info_str = str(audio_info_from_html).lower()
        if 'japonês' in audio_info_str or 'japones' in audio_info_str or 'japanese' in audio_info_str or 'jap' in audio_info_str:
            has_japones_audio = True

    if magnet_processed and not has_japones_audio:
        release_lower = magnet_processed.lower()
        if 'japonês' in release_lower or 'japones' in release_lower or 'japanese' in release_lower or re.search(r'\bjap\b', release_lower):
            has_japones_audio = True

    if info_hash and not skip_metadata and not has_japones_audio:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'japonês' in metadata_name or 'japones' in metadata_name or 'japanese' in metadata_name or re.search(r'\bjap\b', metadata_name):
                    has_japones_audio = True
        except Exception:
            pass

    if info_hash and not skip_metadata and not has_japones_audio:
        try:
            from utils.text import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'japonês' in cross_release_lower or 'japones' in cross_release_lower or 'japanese' in cross_release_lower or re.search(r'\bjap\b', cross_release_lower):
                        has_japones_audio = True
        except Exception:
            pass

    tags_to_add = []
    if has_brazilian_audio and not has_brazilian:
        tags_to_add.append('[Brazilian]')
    if has_eng_audio and not has_eng:
        tags_to_add.append('[Eng]')
    if has_japones_audio and not has_jap:
        tags_to_add.append('[Jap]')

    if tags_to_add:
        if '[Brazilian]' in tags_to_add or '[Eng]' in tags_to_add:
            title = re.sub(r'\.?\.?DUAL(?![\.\s]?(?:5\.1|2\.0|7\.1))\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        if '[Brazilian]' in tags_to_add:
            title = re.sub(r'\.?\.?DUBLADO\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?NACIONAL\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?PORTUGUES\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?PORTUGUÊS\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        if '[Jap]' in tags_to_add:
            title = re.sub(r'\.?\.?JAPONÊS\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAPONES\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAPANESE\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.?\.?JAP\.?\.?', '.', title, flags=re.IGNORECASE)
            title = re.sub(r'\.{2,}', '.', title)
            title = title.strip('.')
        title = re.sub(r'\.?\.?LEGENDADO\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.?\.?LEGENDA\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.?\.?LEG\.?\.?', '.', title, flags=re.IGNORECASE)
        title = re.sub(r'\.{2,}', '.', title)
        title = title.strip('.')

        title = title.rstrip()
        title = f"{title} {' '.join(tags_to_add)}"

    result = title
    return result

def _extract_legenda_rede(doc: BeautifulSoup, article: Optional[BeautifulSoup] = None) -> str:
    legenda = ''
    root = article or doc

    for card in root.select('.spec-card-glass'):
        label_el = card.select_one('small')
        value_el = card.select_one('strong')
        if not label_el or not value_el:
            continue
        if re.search(r'legend', label_el.get_text(' ', strip=True), re.I):
            value = value_el.get_text(' ', strip=True)
            if value:
                return value

    if not article:
        article = doc.find('article') or doc

    info_div = article.find('div', id='informacoes') if hasattr(article, 'find') else None
    if not info_div:
        return legenda

    info_html = str(info_div)

    simple_legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*[\n\r\t\s]*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma|$)', info_html, re.DOTALL)
    if simple_legenda_match:
        legenda = simple_legenda_match.group(1).strip()
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        legenda = re.sub(r'\s+', ' ', legenda).strip()
        stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda

    simple_legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma|$)', info_html, re.DOTALL)
    if simple_legenda_match:
        legenda = simple_legenda_match.group(1).strip()
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        legenda = re.sub(r'\s+', ' ', legenda).strip()
        stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda

    legenda_patterns = [
        r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|Nota|Tamanho|$)',
        r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|$)',
    ]

    for pattern in legenda_patterns:
        legenda_match = re.search(pattern, info_html, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
            for stop_word in stop_words:
                if stop_word in legenda:
                    idx = legenda.index(stop_word)
                    legenda = legenda[:idx].strip()
                    break
            if legenda:
                return legenda

    for p in article.select('div#informacoes > p'):
        html_content = str(p)
        html_content_preserved = html_content.replace('\t', ' ')
        html_content_preserved = re.sub(r'<br\s*\/?>', '<br>', html_content_preserved)

        legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*[\n\r\t]*\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
        if not legenda_match:
            legenda_match = re.search(r'(?i)<strong>Legendas?\s*:\s*</strong>\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)

        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            if legenda:
                return legenda

        legenda_match = re.search(r'(?i)<b>Legendas?\s*:</b>\s*([^<]+?)(?:<br|</div|</p|</b|$)', html_content_preserved, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            if legenda:
                return legenda

        legenda_match = re.search(r'(?i)Legendas?\s*:\s*(?:<br\s*/?>)?\s*([^<\n\r]+?)(?:<br|</div|</p|Nota|Tamanho|$)', html_content_preserved, re.DOTALL)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            if legenda:
                return legenda


        parts_by_br = html_content_preserved.split('<br>')
        for i, part in enumerate(parts_by_br):
            if re.search(r'(?i)<strong>Legendas?\s*:', part):
                match = re.search(r'(?i)</strong>\s*[\n\r\t]*\s*([^<\n\r]+?)(?:<br|$)', part, re.DOTALL)
                if match:
                    legenda = match.group(1).strip()
                    legenda = html.unescape(legenda)
                    legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                    legenda = re.sub(r'\s+', ' ', legenda).strip()
                    if legenda:
                        return legenda
                if i + 1 < len(parts_by_br):
                    next_part = parts_by_br[i + 1]
                    next_part_clean = re.sub(r'<[^>]+>', '', next_part).strip()
                    if next_part_clean and next_part_clean not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']:
                        if not re.search(r'(?i)^\s*<strong>', next_part):
                            legenda = next_part_clean.strip()
                            return legenda
            line_clean = re.sub(r'<[^>]*>', '', part).strip()
            if 'Legendas:' in line_clean or 'Legenda:' in line_clean:
                parts = line_clean.split(':')
                if len(parts) > 1:
                    extracted = ':'.join(parts[1:]).strip()
                    if extracted:
                        legenda = extracted
                        return legenda
                if i + 1 < len(parts_by_br):
                    next_line = re.sub(r'<[^>]*>', '', parts_by_br[i + 1]).strip()
                    if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio']:
                        legenda = next_line
                        return legenda


    info_text = info_div.get_text(separator='\n')
    lines = info_text.split('\n')
    for i, line in enumerate(lines):
        line_clean = line.strip()
        if re.search(r'(?i)^Legendas?\s*:', line_clean):
            match = re.search(r'(?i)Legendas?\s*:\s*(.+?)$', line_clean)
            if match:
                legenda = match.group(1).strip()
                stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']:
                    if not re.search(r'(?i)^(Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma)', next_line):
                        legenda = next_line.strip()
                        return legenda

    legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^\n]+?)(?:\n|Nota|Tamanho|Imdb|Vídeo|Áudio|$)', info_text)
    if legenda_match:
        legenda = legenda_match.group(1).strip()
        legenda = re.sub(r'\s+', ' ', legenda).strip()
        stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda

    for p in article.select('div#informacoes > p'):
        p_text = p.get_text(separator='\n')
        lines = p_text.split('\n')
        for i, line in enumerate(lines):
            line_clean = line.strip()
            if re.search(r'(?i)^Legendas?\s*:', line_clean):
                match = re.search(r'(?i)Legendas?\s*:\s*(.+?)$', line_clean)
                if match:
                    legenda = match.group(1).strip()
                    stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
                    for stop_word in stop_words:
                        if stop_word in legenda:
                            idx = legenda.index(stop_word)
                            legenda = legenda[:idx].strip()
                            break
                    if legenda:
                        return legenda
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and next_line not in ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']:
                        if not re.search(r'(?i)^(Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma)', next_line):
                            legenda = next_line.strip()
                            return legenda

        p_text_simple = p.get_text(separator=' ')
        legenda_match = re.search(r'(?i)Legendas?\s*:\s*([^\n\r]+?)(?:\s|$|Nota|Tamanho|Imdb|Vídeo|Áudio|Idioma)', p_text_simple)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = re.sub(r'\s+', ' ', legenda).strip()
            stop_words = ['Nota', 'Tamanho', 'Imdb', 'Vídeo', 'Áudio', 'Idioma']
            for stop_word in stop_words:
                if stop_word in legenda:
                    idx = legenda.index(stop_word)
                    legenda = legenda[:idx].strip()
                    break
            if legenda:
                return legenda

    return legenda

def _extract_legenda_bludv(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> str:
    legenda = ''

    if not content_div:
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')

    if content_div:
        content_html = str(content_div)

        legenda_patterns = [
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|$)',
            r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Qualidade|$)',
        ]

        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, content_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Qualidade', 'Duração', 'Formato']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda

    return legenda

def _extract_legenda_comand(doc: BeautifulSoup, content_div: Optional[BeautifulSoup] = None) -> str:
    legenda = ''

    if not content_div:
        content_div = doc.find('div', class_='content')
        if not content_div:
            content_div = doc.find('div', class_='entry-content')
        if not content_div:
            content_div = doc.find('article')

    if content_div:
        content_html = str(content_div)

        legenda_patterns = [
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|</span|Canais|Fansub|Qualidade|Duração|Formato|Vídeo|Nota|Tamanho|IMDb|Áudio|Audio|Status|$)',
            r'(?i)<[^>]*>Legendas?\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</div|</p|Canais|Fansub|Qualidade|$)',
            r'(?i)<strong>Legendas?\s*:\s*</strong>\s*(?:<br\s*/?>)?\s*\n\s*([^<\n\r]+?)(?:<br|</div|</p|</strong|Nota|Tamanho|$)',
        ]

        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, content_html, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Audio', 'Canais', 'Fansub', 'Qualidade', 'Duração', 'Formato', 'Status']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda

    return legenda

def _extract_legenda_starck(doc: BeautifulSoup, **kwargs) -> str:
    legenda = ''

    capa = doc.find('div', class_='capa')
    if not capa:
        return legenda

    for p in capa.select('.post-description p'):
        html_content = str(p)
        text = ' '.join(span.get_text() for span in p.find_all('span'))

        legenda_patterns = [
            r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</p|</div|Nota|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)',
            r'(?i)<[^>]*>Legenda\s*:\s*</[^>]*>([^<\n\r]+?)(?:<br|</p|</div|Nota|Tamanho|$)',
            r'(?i)Legendas?\s*:\s*([^<\n\r]+?)(?:<br|</p|</div|Nota|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)',
        ]

        for pattern in legenda_patterns:
            legenda_match = re.search(pattern, html_content, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = html.unescape(legenda)
                legenda = re.sub(r'<[^>]+>', '', legenda).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                stop_words = ['Nota', 'Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Idioma']
                for stop_word in stop_words:
                    if stop_word in legenda:
                        idx = legenda.index(stop_word)
                        legenda = legenda[:idx].strip()
                        break
                if legenda:
                    return legenda

        text_lower = text.lower()
        if 'legenda' in text_lower:
            legenda_match = re.search(r'(?i)legenda\s*:\s*([^\n\r]+?)(?:\n|Nota|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)', text, re.DOTALL)
            if legenda_match:
                legenda = legenda_match.group(1).strip()
                legenda = re.sub(r'\s+', ' ', legenda).strip()
                if legenda:
                    return legenda

    return legenda

def _extract_legenda_tfilme(doc: BeautifulSoup, **kwargs) -> str:
    legenda = ''

    article = doc.find('article')
    if not article:
        return legenda

    content_div = article.find('div', class_='content')
    if not content_div:
        return legenda

    content_html = str(content_div)

    legenda_match = re.search(r'(?i)<b>Legenda:</b>\s*([^<]+?)(?:<br|</div|</p|</b|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)', content_html)
    if legenda_match:
        legenda = legenda_match.group(1).strip()
        legenda = html.unescape(legenda)
        legenda = re.sub(r'<[^>]+>', '', legenda).strip()
        stop_words = ['Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Idioma']
        for stop_word in stop_words:
            if stop_word in legenda:
                idx = legenda.index(stop_word)
                legenda = legenda[:idx].strip()
                break
        if legenda:
            return legenda

    if not legenda:
        legenda_match = re.search(r'(?i)Legenda\s*:\s*([^<\n\r]+?)(?:<br|</div|</p|Tamanho|IMDb|Vídeo|Áudio|Idioma|$)', content_html)
        if legenda_match:
            legenda = legenda_match.group(1).strip()
            legenda = html.unescape(legenda)
            legenda = re.sub(r'<[^>]+>', '', legenda).strip()
            stop_words = ['Tamanho', 'IMDb', 'Vídeo', 'Áudio', 'Idioma']
            for stop_word in stop_words:
                if stop_word in legenda:
                    idx = legenda.index(stop_word)
                    legenda = legenda[:idx].strip()
                    break
            if legenda:
                return legenda

    return legenda

LEGENDA_EXTRACTORS = {
    'rede': _extract_legenda_rede,
    'bludv': _extract_legenda_bludv,
    'comand': _extract_legenda_comand,
    'starck': _extract_legenda_starck,
    'tfilme': _extract_legenda_tfilme,
}

def extract_legenda_from_page(doc: BeautifulSoup, scraper_type: Optional[str] = None, **kwargs) -> str:
    if not doc:
        return ''

    if scraper_type and scraper_type in LEGENDA_EXTRACTORS:
        try:
            extractor_func = LEGENDA_EXTRACTORS[scraper_type]
            return extractor_func(doc, **kwargs)
        except Exception as e:
            logger.debug(f"Erro ao extrair legenda com função específica de {scraper_type}: {e}")

    return ''

def determine_legend_info(legenda: str, magnet_processed: Optional[str] = None, info_hash: Optional[str] = None, skip_metadata: bool = False) -> Optional[str]:

    if legenda:
        legenda_original = legenda.strip()
        legenda_lower = legenda_original.lower()

        if legenda_original.upper() in ['S/L', 'S.L.'] or re.match(r'^\s*s[/\.]l\s*$', legenda_lower):
            return legenda_original.upper() if legenda_original.upper() in ['S/L', 'S.L.'] else legenda_original

        valores_detectados = []

        if 's/l' in legenda_lower or 's.l.' in legenda_lower or re.search(r'\bs[/\.]l\b', legenda_lower):
            if 'S/L' in legenda_original:
                valores_detectados.append('S/L')
            elif 'S.L.' in legenda_original:
                valores_detectados.append('S.L.')
            else:
                valores_detectados.append('legendado')

        if ('português' in legenda_lower or 'portugues' in legenda_lower or
            'pt-br' in legenda_lower or 'ptbr' in legenda_lower or
            'pt br' in legenda_lower or re.search(r'\bpt\s*[-:]?\s*br\b', legenda_lower)):
            valores_detectados.append('Português')

        if ('inglês' in legenda_lower or 'ingles' in legenda_lower or
            'english' in legenda_lower or re.search(r'\beng\b', legenda_lower)):
            valores_detectados.append('Inglês')

        if ('espanhol' in legenda_lower or 'espanol' in legenda_lower or
            'spanish' in legenda_lower or re.search(r'\besp\b', legenda_lower)):
            valores_detectados.append('Espanhol')

        if ('japonês' in legenda_lower or 'japones' in legenda_lower or
            'japanese' in legenda_lower or re.search(r'\bjap\b', legenda_lower)):
            valores_detectados.append('Japonês')

        valores_detectados = valores_detectados[:3]

        if valores_detectados:
            return ', '.join(valores_detectados) if len(valores_detectados) > 1 else valores_detectados[0]

    if magnet_processed:
        release_lower = magnet_processed.lower()
        if 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            return 'legendado'

    if info_hash and not skip_metadata:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name):
                    return 'legendado'
        except Exception:
            pass

    if info_hash and not skip_metadata:
        try:
            from utils.text import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower):
                        return 'legendado'
        except Exception:
            pass

    return None

def determine_legend_presence(legend_info_from_html: Optional[str] = None, audio_html_content: Optional[str] = None, magnet_processed: Optional[str] = None, info_hash: Optional[str] = None, skip_metadata: bool = False) -> bool:
    has_legenda = False

    if legend_info_from_html:
        legend_info_str = str(legend_info_from_html).lower()
        if 'legendado' in legend_info_str or 's/l' in legend_info_str or 's.l.' in legend_info_str or re.search(r'\bs[/\.]l\b', legend_info_str):
            has_legenda = True
            return has_legenda

    if audio_html_content and not has_legenda:
        if re.search(r'(?i)(?:legendado|legenda|\bleg\b|s[/\.]l\b)', audio_html_content):
            has_legenda = True
            return has_legenda

    if magnet_processed and not has_legenda:
        release_lower = magnet_processed.lower()
        if 'legendado' in release_lower or 'legenda' in release_lower or re.search(r'\bleg\b', release_lower):
            has_legenda = True
            return has_legenda

    if info_hash and not skip_metadata and not has_legenda:
        try:
            from magnet.metadata import fetch_metadata_from_itorrents
            metadata = fetch_metadata_from_itorrents(info_hash)
            if metadata and metadata.get('name'):
                metadata_name = metadata.get('name', '').lower()
                if 'legendado' in metadata_name or 'legenda' in metadata_name or re.search(r'\bleg\b', metadata_name):
                    has_legenda = True
                    return has_legenda
        except Exception:
            pass

    if info_hash and not skip_metadata and not has_legenda:
        try:
            from utils.text import get_cross_data_from_redis
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data and cross_data.get('magnet_processed'):
                cross_release = cross_data.get('magnet_processed')
                if cross_release and cross_release != 'N/A':
                    cross_release_lower = str(cross_release).lower()
                    if 'legendado' in cross_release_lower or 'legenda' in cross_release_lower or re.search(r'\bleg\b', cross_release_lower):
                        has_legenda = True
                        return has_legenda
        except Exception:
            pass

    return has_legenda

_request_cache = threading.local()

_LOCK = threading.Lock()
_LAST_REQUEST_TIME = {}
_MAX_DOMAIN_ENTRIES = 200
_MIN_DELAY_BETWEEN_REQUESTS = 0.2
_MAX_CONCURRENT_REQUESTS = 5
_REQUEST_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT_REQUESTS)

_DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

_BASE64_CHARS = set(string.ascii_letters + string.digits + '+/=')

_RE_MAGNET_FULL = re.compile(r'magnet:\?[^"\'\s<>]+')
_RE_MAGNET_QUOTED = re.compile(r'magnet:\?[^"\'\s\)]+')
_RE_MAGNET_EXTENDED = re.compile(r'magnet:\?[^"\']+')
_RE_META_REFRESH_URL = re.compile(r'url\s*=\s*([^;]+)', re.IGNORECASE)
_RE_HREF_RECEBER_PHP = re.compile(
    r'href=["\'](https?://[^"\']*(?:receber|recebi|link)\.php[^"\']*)["\']', re.IGNORECASE
)
_RE_HREF_GET_PHP = re.compile(
    r'href=["\'](https?://[^"\']*get\.php[^"\']*)["\']', re.IGNORECASE
)
_RE_LOCATION_REPLACE_HTML = re.compile(
    r'location\.replace\(["\']((?:[^"\'\\]|\\.)+)["\']\)', re.IGNORECASE
)
_RE_GO_PHP_REDIRECT = re.compile(
    r'(?:const|var|let)\s+redirect\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_JS_REDIRECT_PATTERNS = [
    re.compile(r'location\.replace\(["\']([^"\']+)["\']\)', re.IGNORECASE),
    re.compile(r'location\.replace\(["\']((?:[^"\'\\]|\\.)+)["\']\)', re.IGNORECASE),
    re.compile(r'location\.href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'location\.href\s*=\s*["\']((?:[^"\'\\]|\\.)+)["\']\)', re.IGNORECASE),
    re.compile(r'window\.location\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
]

_JS_MAGNET_PATTERNS = [
    re.compile(r'window\.location\s*=\s*["\'](magnet:[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'location\.href\s*=\s*["\'](magnet:[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'window\.open\(["\'](magnet:[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'redirect.*?["\'](magnet:[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'location\s*=\s*["\'](magnet:[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'["\'](magnet:\?[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'decodeURIComponent\(["\']([^"\']+)["\']\)', re.IGNORECASE | re.DOTALL),
]

_JS_RAW_MAGNET_PATTERNS = [
    re.compile(r'window\.location\s*=\s*["\'](magnet:\?[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'location\.href\s*=\s*["\'](magnet:\?[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'["\'](magnet:\?[^"\']+)["\']', re.IGNORECASE | re.DOTALL),
]

_SKIP_REDIRECT_PATTERNS = [
    re.compile(r'/[^/]+-[^/]+-[^/]+/'),
    re.compile(r'/[^/?]+\.html?$'),
]

def _pad_b64(s: str) -> str:
    mod = len(s) % 4
    return s + '=' * (4 - mod) if mod else s

def _try_b64_decode_magnet(value: str) -> Optional[str]:
    for candidate in [value, value.replace('-', '+').replace('_', '/')]:
        try:
            decoded = base64.b64decode(_pad_b64(candidate)).decode('utf-8')
            if decoded.startswith('magnet:'):
                return decoded
        except Exception:
            continue
    return None

def _cache_result(redis_client, protlink_url: str, magnet: str):
    if redis_client:
        try:
            from app.config import Config
            redis_client.setex(protlink_key(protlink_url), Config.RESOLVED_LINK_CACHE_TTL, magnet)
        except Exception:
            pass
    else:
        if not hasattr(_request_cache, 'protlink_cache'):
            _request_cache.protlink_cache = {}
        _request_cache.protlink_cache[protlink_url] = magnet

def _get_cached(redis_client, protlink_url: str) -> Optional[str]:
    if redis_client:
        try:
            cached = redis_client.get(protlink_key(protlink_url))
            if cached:
                return cached.decode('utf-8')
        except Exception:
            pass
    else:
        if hasattr(_request_cache, 'protlink_cache'):
            return _request_cache.protlink_cache.get(protlink_url)
    return None

def _rate_limit(domain: str):
    with _LOCK:
        last_time = _LAST_REQUEST_TIME.get(domain, 0)
        now = time.time()
        delay = max(0, _MIN_DELAY_BETWEEN_REQUESTS - (now - last_time))
        _LAST_REQUEST_TIME[domain] = now + delay
        if len(_LAST_REQUEST_TIME) > _MAX_DOMAIN_ENTRIES:
            oldest = min(_LAST_REQUEST_TIME, key=_LAST_REQUEST_TIME.get)
            del _LAST_REQUEST_TIME[oldest]

    if delay > 0:
        time.sleep(delay)

def _unescape_js_string(s: str) -> str:
    return s.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')

def _make_headers(referer: str) -> dict:
    return {**_DEFAULT_HEADERS, 'Referer': referer}

def _make_soup(html_content: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_content, 'lxml')
    except Exception:
        return BeautifulSoup(html_content, 'html.parser')

def _extract_magnet_from_html(doc: BeautifulSoup, html_content: str) -> Optional[str]:
    for a in doc.select('a[href^="magnet:"], a[href*="magnet:"]'):
        href = a.get('href', '')
        if href.startswith('magnet:'):
            return href

    for meta in doc.select('meta[http-equiv="refresh"]'):
        content = meta.get('content', '')
        if 'magnet:' in content:
            match = _RE_MAGNET_QUOTED.search(content)
            if match:
                magnet = match.group(0)
                extended = _RE_MAGNET_EXTENDED.search(content[match.start():])
                if extended and len(extended.group(0)) > len(magnet):
                    magnet = extended.group(0)
                return magnet

    for script in doc.select('script'):
        script_text = script.string or ''
        if not script_text:
            continue

        for pattern in _JS_MAGNET_PATTERNS:
            match = pattern.search(script_text)
            if match:
                potential = match.group(1)
                if not potential.startswith('magnet:'):
                    try:
                        potential = unquote(potential)
                    except Exception:
                        pass
                if potential.startswith('magnet:'):
                    return potential

        if 'magnet:' in script_text:
            matches = _RE_MAGNET_QUOTED.findall(script_text)
            if matches:
                return max(matches, key=len)

    for pattern in _JS_RAW_MAGNET_PATTERNS:
        matches = pattern.findall(html_content)
        if matches:
            return max(matches, key=len)

    for elem in doc.select('[data-download], [data-link], [data-magnet], [data-url], [data-u]'):
        for attr in ('data-download', 'data-link', 'data-magnet', 'data-url', 'data-u'):
            value = elem.get(attr, '')
            if not value:
                continue
            if value.startswith('magnet:'):
                return value
            if attr == 'data-u':
                decoded = decode_data_u(value)
                if decoded:
                    return decoded
            else:
                decoded = _try_b64_decode_magnet(value)
                if decoded:
                    return decoded

    match = _RE_MAGNET_FULL.search(html_content)
    if match:
        return match.group(0)

    return None

def _find_redirect_in_html(doc: BeautifulSoup, html_content: str, current_url: str) -> Optional[str]:
    for a in doc.select('a[id*="redirect"], a[id*="Redirect"], a[href*="receber.php"], a[href*="redirecionando"]'):
        href = a.get('href', '')
        if href and ('receber.php' in href or 'redirecionando' in href.lower() or 'recebi.php' in href):
            return href

    for meta in doc.select('meta[http-equiv="refresh"], meta[http-equiv="Refresh"]'):
        content = meta.get('content', '')
        match = _RE_META_REFRESH_URL.search(content)
        if match:
            return match.group(1).strip()

    for script in doc.select('script'):
        script_text = script.string or ''
        if not script_text:
            continue
        for pattern in _JS_REDIRECT_PATTERNS:
            match = pattern.search(script_text)
            if match:
                return _unescape_js_string(match.group(1))

    match = _RE_LOCATION_REPLACE_HTML.search(html_content)
    if match:
        return _unescape_js_string(match.group(1))

    match = _RE_HREF_RECEBER_PHP.search(html_content)
    if match:
        return match.group(1)

    is_systemads_page = (
        is_go_php_link(current_url) or 'get.php' in current_url or 'seuvideo.xyz' in current_url
    )
    if is_systemads_page:
        for a in doc.select('a[href]'):
            href = (a.get('href') or '').strip()
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            href_lower = href.lower()
            text = (a.get_text() or '').strip().lower()
            if (
                'get.php' in href_lower or 'receber' in href_lower or 'recebi' in href_lower or 'link.php' in href_lower
                or any(t in text for t in ('continuar', 'clique aqui', 'aguarde', 'ir para', 'acessar', 'download', 'magnet', 'get link', 'obter'))
                or 'go.php' in href_lower or 'seuvideo.xyz' in href_lower
            ):
                return href

        match = _RE_HREF_GET_PHP.search(html_content)
        if match:
            return match.group(1)

    return None

def is_go_php_link(href: str) -> bool:
    if not href:
        return False
    try:
        parsed = urlparse(href.strip())
        path = (parsed.path or '').lower()
        return path.endswith('/go.php') or path.endswith('go.php') or '/go.php' in path
    except Exception:
        return 'go.php' in href.lower()

def is_redirect_chain_link(href: str) -> bool:
    if not href:
        return False
    lower = href.lower()
    return any(x in lower for x in ('redirectad.net', 'enviar.php', 'receber.php', 'recebi.php'))

def is_direct_id_magnet_link(href: str) -> bool:
    if not href:
        return False
    try:
        parsed = urlparse(html.unescape(href.strip()))
        id_param = parse_qs(parsed.query).get('id', [None])[0]
        if not id_param:
            return False
        id_param = unquote(str(id_param).strip())
        if not id_param:
            return False
        normalized = id_param.replace('-', '+').replace('_', '/')
        return normalized.startswith('bWFnbmV0Oj')
    except Exception:
        return False

def is_offline_decodable_link(href: str) -> bool:
    if not href:
        return False
    if is_go_php_link(href):
        return False
    lower = href.lower()
    if 'get.php' in lower and 'id=' in lower:
        return True
    return is_direct_id_magnet_link(href)

def is_embedded_go_payload_link(href: str) -> bool:
    if not href:
        return False
    try:
        parsed = urlparse(html.unescape(href.strip()))
        go_param = parse_qs(parsed.query).get('go', [None])[0]
        return bool(go_param and '.p1.' in go_param)
    except Exception:
        return '.p1.' in href and ('?go=' in href.lower() or '&go=' in href.lower())


def decode_embedded_go_payload_link(href: str) -> Optional[str]:
    if not href:
        return None
    try:
        parsed = urlparse(html.unescape(href.strip()))
        go_param = parse_qs(parsed.query).get('go', [None])[0]
        if not go_param or '.p1.' not in go_param:
            return None

        payload_b64 = go_param.split('.p1.', 1)[1].strip()
        if not payload_b64:
            return None

        data = None
        for candidate in (payload_b64, payload_b64.replace('-', '+').replace('_', '/')):
            try:
                raw = base64.b64decode(_pad_b64(candidate))
                data = json.loads(raw.decode('utf-8'))
                break
            except Exception:
                continue
        if not isinstance(data, dict):
            return None

        u_value = data.get('u')
        if isinstance(u_value, str) and u_value.strip().lower().startswith('magnet:'):
            return u_value.strip()

        info_hash = str(data.get('m') or '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{32,64}', info_hash):
            return None
        if len(info_hash) > 40:
            info_hash = info_hash[:40]

        title = str(data.get('t') or '').strip()
        params = [f'xt=urn:btih:{info_hash}']
        if title:
            params.append(f'dn={quote(title)}')
        return f"magnet:?{'&'.join(params)}"
    except Exception as e:
        logger.debug("embedded go payload decode error: %s", type(e).__name__)
        return None


def is_protected_link(href: str, protected_patterns: Optional[List[str]] = None) -> bool:
    if not href:
        return False
    if is_embedded_go_payload_link(href):
        return True
    if is_offline_decodable_link(href):
        return True
    if protected_patterns is None:
        protected_patterns = [
            'go.php',
            'get.php',
            'links.php',
            'videosad.net',
            '?go=',
            '&go=',
            'seuvideo.xyz',
            'protlink',
            'encurtador',
            'encurta',
        ]
    return any(pattern in href.lower() for pattern in protected_patterns)

def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad < 1 or pad > 16:
        return data
    if data[-pad:] != bytes([pad]) * pad:
        return data
    return data[:-pad]

def _bytes_to_magnet(data: bytes) -> Optional[str]:
    if not data:
        return None
    for encoding in ('utf-8', 'latin-1'):
        try:
            text = data.decode(encoding, errors='strict')
            if text.startswith('magnet:'):
                return text
        except Exception:
            continue
    match = _RE_MAGNET_FULL.search(data.decode('utf-8', errors='ignore'))
    return match.group(0) if match else None

def _try_aes_decrypt_magnet(ciphertext: bytes, key_source: str) -> Optional[str]:
    if not ciphertext or not key_source:
        return None
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        return None

    key_candidates = []
    raw = key_source.encode('utf-8')
    key_candidates.append(raw.ljust(16, b'\0')[:16])
    key_candidates.append(raw.ljust(32, b'\0')[:32])
    key_candidates.append(hashlib.md5(raw).digest())

    for key in key_candidates:
        if len(key) not in (16, 24, 32):
            continue
        if len(ciphertext) > 16:
            iv, ct = ciphertext[:16], ciphertext[16:]
            try:
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
                decryptor = cipher.decryptor()
                pt = _pkcs7_unpad(decryptor.update(ct) + decryptor.finalize())
                result = _bytes_to_magnet(pt)
                if result:
                    return result
            except Exception:
                pass
        try:
            cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
            decryptor = cipher.decryptor()
            pt = _pkcs7_unpad(decryptor.update(ciphertext) + decryptor.finalize())
            result = _bytes_to_magnet(pt)
            if result:
                return result
        except Exception:
            pass
    return None

def _decode_id_param(id_param: str, rastrear: Optional[str] = None) -> Optional[str]:
    if not id_param:
        return None

    variants = []
    seen = set()

    def _add_variant(value: str) -> None:
        value = (value or '').strip()
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    _add_variant(id_param)
    _add_variant(unquote(id_param))
    _add_variant(codecs.decode(id_param, 'rot_13'))
    _add_variant(id_param[::-1])
    _add_variant(unquote(id_param)[::-1])

    for value in variants:
        result = _try_b64_decode_magnet(value)
        if result:
            return result

    for value in variants:
        for candidate in (value, value.replace('-', '+').replace('_', '/')):
            try:
                decoded_bytes = base64.b64decode(_pad_b64(candidate))
            except Exception:
                continue
            result = _bytes_to_magnet(decoded_bytes)
            if result:
                return result
            try:
                inflated = zlib.decompress(decoded_bytes, -zlib.MAX_WBITS)
                result = _bytes_to_magnet(inflated)
                if result:
                    return result
            except Exception:
                pass
            if rastrear:
                result = _try_aes_decrypt_magnet(decoded_bytes, rastrear)
                if result:
                    return result
                key_bytes = rastrear.encode('utf-8')
                xored = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(decoded_bytes))
                result = _bytes_to_magnet(xored)
                if result:
                    return result

    return None

def decode_redirect_chain_id(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        url = html.unescape(url)
        parsed = urlparse(url)
        id_param = parse_qs(parsed.query).get('id', [None])[0]
        if not id_param:
            return None
        id_param = unquote(str(id_param).strip())
        if not id_param:
            return None
        return _try_b64_decode_magnet(id_param[::-1])
    except Exception:
        return None

def _extract_go_php_redirect_url(html_content: str) -> Optional[str]:
    if not html_content:
        return None
    match = _RE_GO_PHP_REDIRECT.search(html_content)
    if not match:
        return None
    return html.unescape(match.group(1).strip())

def resolve_go_php_link(
    go_url: str,
    session: requests.Session,
    base_url: str = '',
    redis=None,
) -> Optional[str]:
    redis_client = redis or get_redis_client()
    cached = _get_cached(redis_client, go_url)
    if cached:
        return cached

    decoded = decode_ad_link(go_url)
    if decoded:
        _cache_result(redis_client, go_url, decoded)
        return decoded

    if is_redirect_chain_link(go_url):
        decoded = decode_redirect_chain_id(go_url)
        if decoded:
            _cache_result(redis_client, go_url, decoded)
        return decoded

    try:
        referer = base_url or go_url
        with _REQUEST_SEMAPHORE:
            response = session.get(
                go_url,
                allow_redirects=False,
                timeout=12,
                headers=_make_headers(referer),
            )
        if response.status_code in (301, 302, 303, 307, 308):
            location = html.unescape((response.headers.get('Location') or '').strip())
            if location.startswith('magnet:'):
                _cache_result(redis_client, go_url, location)
                return location
            if location:
                next_url = urljoin(go_url, location)
                if next_url.startswith('http://'):
                    next_url = 'https://' + next_url[7:]
                return resolve_protected_link(next_url, session, go_url, redis_client)
            return None

        if response.status_code != 200:
            logger.debug(
                "go.php status %s para %s",
                response.status_code,
                go_url[:80],
            )
            return None

        redirect_url = _extract_go_php_redirect_url(response.text)
        if redirect_url:
            magnet = decode_redirect_chain_id(redirect_url)
            if not magnet:
                magnet = decode_ad_link(redirect_url)
            if magnet:
                _cache_result(redis_client, go_url, magnet)
                return magnet
            logger.debug(
                "go.php redirect sem magnet decodificável: %s → %s",
                go_url[:60],
                redirect_url[:80],
            )
        else:
            logger.debug("go.php sem const redirect embutido: %s", go_url[:80])

        try:
            doc = _make_soup(response.text)
            magnet = _extract_magnet_from_html(doc, response.text)
            if magnet:
                _cache_result(redis_client, go_url, magnet)
                return magnet
        except Exception:
            pass
    except Exception as e:
        logger.debug("go.php resolve error: %s", type(e).__name__)

    return None

def decode_ad_link(ad_link: str) -> Optional[str]:
    if not ad_link:
        return None
    try:
        ad_link = html.unescape(ad_link)
        parsed_url = urlparse(ad_link)
        query_params = parse_qs(parsed_url.query)
        id_param = query_params.get('id', [None])[0]
        if not id_param:
            return None
        id_param = unquote(str(id_param).strip())
        if not id_param:
            return None

        rastrear = query_params.get('rastrear', [None])[0]
        rastrear = str(rastrear).strip() if rastrear else None

        return _decode_id_param(id_param, rastrear=rastrear)
    except Exception:
        return None

def _unshuffle_string(shuffled: str) -> Optional[str]:
    try:
        length = len(shuffled)
        original = [''] * length
        used = [False] * length
        step = 3
        index = 0

        for i in range(length):
            while used[index]:
                index = (index + 1) % length
            used[index] = True
            original[i] = shuffled[index]
            index = (index + step) % length

        return ''.join(original)
    except Exception:
        return None

def decode_data_u(data_u_value: str) -> Optional[str]:
    if not data_u_value:
        return None
    try:
        variants = [data_u_value]
        uq = unquote(data_u_value)
        if uq not in variants:
            variants.append(uq)
        he = html.unescape(data_u_value)
        if he not in variants:
            variants.append(he)
        uq_he = unquote(he)
        if uq_he not in variants:
            variants.append(uq_he)

        for raw in variants:
            unshuffled = _unshuffle_string(raw)
            if not unshuffled:
                continue
            if "magnet:" in unshuffled:
                m = _RE_MAGNET_FULL.search(unshuffled)
                if m:
                    return m.group(0)
                return unshuffled
            if unshuffled.lower().startswith(("http://", "https://")):
                return unshuffled
        return None
    except Exception:
        return None

def resolve_protected_link(protlink_url: str, session: requests.Session, base_url: str = '', redis=None) -> Optional[str]:
    redis_client = redis or get_redis_client()

    if protlink_url and base_url:
        parsed_in = urlparse(protlink_url.strip())
        if not parsed_in.scheme:
            protlink_url = urljoin(base_url, protlink_url)

    cached = _get_cached(redis_client, protlink_url)
    if cached:
        return cached

    if is_embedded_go_payload_link(protlink_url):
        decoded_magnet = decode_embedded_go_payload_link(protlink_url)
        if decoded_magnet:
            _cache_result(redis_client, protlink_url, decoded_magnet)
            return decoded_magnet
        logger.debug("Falha ao decodificar go payload embutido: %s", protlink_url[:100])

    if is_go_php_link(protlink_url):
        return resolve_go_php_link(protlink_url, session, base_url, redis_client)

    if is_redirect_chain_link(protlink_url):
        decoded_magnet = decode_redirect_chain_id(protlink_url)
        if decoded_magnet:
            _cache_result(redis_client, protlink_url, decoded_magnet)
            return decoded_magnet
        return None

    if is_offline_decodable_link(protlink_url):
        decoded_magnet = decode_ad_link(protlink_url)
        if decoded_magnet:
            _cache_result(redis_client, protlink_url, decoded_magnet)
            return decoded_magnet
        logger.debug("Falha ao decodificar get.php offline, tentando via HTTP: %s", protlink_url[:100])

    redirect_count = 0

    with _REQUEST_SEMAPHORE:
        try:
            current_url = protlink_url
            max_redirects = 10
            timeout = 5

            while redirect_count < max_redirects:
                try:
                    domain = urlparse(current_url).netloc or 'unknown'
                    _rate_limit(domain)
                except Exception:
                    pass

                request_timeout = 10 if 't.co' in current_url else timeout
                referer = base_url if redirect_count == 0 else current_url

                try:
                    response = session.get(
                        current_url,
                        allow_redirects=False,
                        timeout=request_timeout,
                        headers=_make_headers(referer),
                    )
                except requests.exceptions.ReadTimeout:
                    if 't.co' in current_url:
                        try:
                            response = session.get(
                                current_url,
                                allow_redirects=True,
                                timeout=10,
                                headers=_make_headers(referer),
                            )
                            current_url = response.url
                        except Exception:
                            break
                    else:
                        break
                except requests.exceptions.RequestException:
                    break

                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location', '')
                    if location.startswith('magnet:'):
                        _cache_result(redis_client, protlink_url, location)
                        return location
                    if location:
                        current_url = urljoin(current_url, location)
                        redirect_count += 1
                        continue
                    break

                if response.status_code != 200:
                    logger.warning(f"Status code não esperado: {response.status_code}")
                    break

                try:
                    html_content = response.text
                    doc = _make_soup(html_content)
                except Exception as e:
                    logger.error(f"Erro ao processar resposta HTML: {e}")
                    break

                magnet = _extract_magnet_from_html(doc, html_content)
                if magnet:
                    _cache_result(redis_client, protlink_url, magnet)
                    return magnet

                redirect_link = _find_redirect_in_html(doc, html_content, current_url)
                if redirect_link:
                    redirect_lower = redirect_link.lower()
                    is_protected_redirect = any(p in redirect_lower for p in (
                        'receber.php', 'recebi.php', 'link.php', 'get.php', '?id=', '&id=',
                    ))

                    if not is_protected_redirect and redirect_count < 5:
                        if any(p.search(redirect_link) for p in _SKIP_REDIRECT_PATTERNS):
                            redirect_link = None

                    if redirect_link:
                        current_url = urljoin(current_url, html.unescape(redirect_link))
                        redirect_count += 1
                        continue

                logger.warning(f"Magnet não encontrado na página após {redirect_count} redirects.")
                break

        except Exception as e:
            logger.debug(f"Link resolver error: {type(e).__name__}")

    logger.warning(f"Falha ao resolver link protegido após {redirect_count} redirects: {protlink_url[:80]}...")
    return None
