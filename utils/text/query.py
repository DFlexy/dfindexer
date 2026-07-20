# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
from typing import List, Optional, Set
from urllib.parse import urlparse

from utils.text.constants import STOP_WORDS
from utils.text.cleaning import remove_accents

_RE_YEAR = re.compile(r'\b((?:19|20)\d{2})\b')
# Sufixo de data em slugs de catálogo (ex.: scarlet-2025-27-05-2026 → remove -27-05-2026)
_RE_CATALOG_DATE_SUFFIX = re.compile(
    r'-(?:\d{1,2}-\d{1,2}-(?:19|20)\d{2}|(?:19|20)\d{2}-\d{1,2}-\d{1,2})$'
)
_RE_QUERY_TEMPORADA = re.compile(
    r'(?i)\b(?:temporada|season)\s*(\d{1,2})\b'
)
_RE_QUERY_SXX = re.compile(r'(?i)\bs(\d{1,2})(?:e\d{1,2})?\b')
_RE_TITLE_TEMPORADA = re.compile(
    r'(?i)\b(\d{1,2})\s*[ªºa]?\s*temporada\b'
    r'|\btemporada\s*(\d{1,2})\b'
    r'|\bseason\s*(\d{1,2})\b'
)
_RE_TITLE_SXX = re.compile(r'(?i)\bs(\d{1,2})(?:e\d{1,2}|[\W_]|$)')
_RE_SLUG_TEMPORADA = re.compile(
    r'(?i)(?:^|[-_/])(\d{1,2})a?-?temporada(?:[-_/]|$)'
    r'|(?:^|[-_/])temporada-?(\d{1,2})(?:[-_/]|$)'
    r'|(?:^|[-_/])s(\d{1,2})(?:e\d{1,2})?(?:[-_/]|$)'
)
# Palavras de season preservadas ao montar variações sem stopwords.
_SEASON_KEEP_WORDS = frozenset({'temporada', 'season'})


def strip_stop_words_keep_season(query: str) -> str:
    """Remove stopwords mas mantém temporada/season (e o restante da query)."""
    if not query or not str(query).strip():
        return ''
    words = []
    for w in str(query).split():
        low = w.lower()
        if low in _SEASON_KEEP_WORDS or low not in STOP_WORDS:
            words.append(w)
    return ' '.join(words)

def extract_query_year(query: str) -> Optional[str]:
    if not query or not query.strip():
        return None
    for word in query.lower().split():
        clean = re.sub(r'[^\w]', '', word, flags=re.UNICODE)
        if clean.isdigit() and len(clean) == 4 and clean.startswith(('19', '20')):
            return clean
    return None


def extract_query_season(query: str) -> Optional[int]:
    """Extrai número de temporada da query (temporada N / season N / S0N / dígito residual)."""
    if not query or not str(query).strip():
        return None
    q = str(query).strip()

    m = _RE_QUERY_TEMPORADA.search(q)
    if m:
        try:
            season = int(m.group(1))
            if 1 <= season <= 99:
                return season
        except (TypeError, ValueError):
            pass

    # SxxEyy / Sxx — só se não for ano disfarçado
    m = _RE_QUERY_SXX.search(q)
    if m:
        try:
            season = int(m.group(1))
            if 1 <= season <= 99:
                return season
        except (TypeError, ValueError):
            pass

    # Fallback: "house of the dragon 3" após stopwords → dígito curto residual.
    # Só quando há indício de série (temporada/season/Sxx já cobertos) OU
    # um único dígito 1–2 casas no fim da query com outras palavras de título.
    words = q.lower().split()
    trailing = []
    for word in reversed(words):
        clean = re.sub(r'[^\w]', '', word, flags=re.UNICODE)
        if not clean:
            continue
        if clean.isdigit() and len(clean) <= 2:
            trailing.append(clean)
            continue
        break
    if len(trailing) == 1:
        # Evita tratar ano truncado; só aceita se a query mencionou season-like
        # ou se "temporada"/"season" foram stopwords removíveis (já no STOP_WORDS).
        has_season_hint = any(
            re.sub(r'[^\w]', '', w, flags=re.UNICODE).lower() in _SEASON_KEEP_WORDS
            for w in words
        )
        if has_season_hint:
            try:
                season = int(trailing[0])
                if 1 <= season <= 99:
                    return season
            except (TypeError, ValueError):
                pass
    return None


def title_has_season(text: str, season: int) -> bool:
    """True se o texto indica a temporada pedida (Nª Temporada / S0N / season N)."""
    if not text or season is None:
        return False
    normalized = remove_accents(str(text).lower().replace('.', ' '))
    normalized = re.sub(r'\s+', ' ', normalized)

    for m in _RE_TITLE_TEMPORADA.finditer(normalized):
        for g in m.groups():
            if g is None:
                continue
            try:
                if int(g) == season:
                    return True
            except (TypeError, ValueError):
                continue

    padded = f'{int(season):02d}'
    bare = str(int(season))
    for m in _RE_TITLE_SXX.finditer(normalized):
        try:
            if int(m.group(1)) == season:
                return True
        except (TypeError, ValueError):
            continue

    # "3 temporada" / "temporada 3" já cobertos; aceita também "s03" colado.
    if re.search(rf'(?i)(?<![0-9a-z])s{re.escape(padded)}(?![0-9a-z])', normalized):
        return True
    if re.search(rf'(?i)(?<![0-9a-z])s{re.escape(bare)}(?![0-9a-z])', normalized):
        return True
    return False


def extract_years_from_text(text: str) -> set[str]:
    if not text:
        return set()
    return set(_RE_YEAR.findall(text))


def _url_slug(url: str) -> str:
    if not url:
        return ''
    path = urlparse(url).path if '://' in url else url
    slug = path.rstrip('/').split('/')[-1].split('?')[0]
    return slug


def _normalize_url_slug_for_year(url: str) -> str:
    return _RE_CATALOG_DATE_SUFFIX.sub('', _url_slug(url))


def slug_has_season(url: str, season: int) -> Optional[bool]:
    """
    None = slug sem indício de temporada (não filtrar).
    True/False = slug tem temporada e bate/não bate com a pedida.
    """
    if not url or season is None:
        return None
    slug = remove_accents(_normalize_url_slug_for_year(url).lower())
    found: Set[int] = set()
    for m in _RE_SLUG_TEMPORADA.finditer(slug):
        for g in m.groups():
            if g is None:
                continue
            try:
                found.add(int(g))
            except (TypeError, ValueError):
                continue
    if not found:
        return None
    return season in found


def filter_urls_by_query_season(query: str, urls: List[str]) -> List[str]:
    """Remove links cujo slug indica outra temporada que a da query."""
    season = extract_query_season(query)
    if season is None or not urls:
        return urls
    filtered: List[str] = []
    for url in urls:
        verdict = slug_has_season(url, season)
        if verdict is False:
            continue
        filtered.append(url)
    return filtered

def slug_year_matches_query_year(
    slug_year: str,
    query_year: str,
    tolerance: int = 1,
) -> bool:
    """True se o ano do slug está dentro de query_year ± tolerance."""
    try:
        return abs(int(slug_year) - int(query_year)) <= tolerance
    except (TypeError, ValueError):
        return False

def filter_urls_by_query_year(
    query: str,
    urls: List[str],
    tolerance: int = 1,
) -> List[str]:
    """
    Filtra links de busca pelo ano no slug da URL (antes de abrir a página).
    Objetivo: evitar coleta de metadata/trackers em páginas fora do ano da query.
    Slug sem ano explícito → mantém o link.
    """
    query_year = extract_query_year(query)
    if not query_year:
        return urls
    filtered = []
    for url in urls:
        slug = _normalize_url_slug_for_year(url)
        years = extract_years_from_text(slug)
        if not years:
            filtered.append(url)
            continue
        if any(slug_year_matches_query_year(y, query_year, tolerance) for y in years):
            filtered.append(url)
    return filtered

def check_query_match(query: str, title: str, title_original_html: str = '', title_translated_html: str = '') -> bool:
    query = str(query) if query is not None else ''
    title = str(title) if title is not None else ''
    title_original_html = str(title_original_html) if title_original_html is not None else ''
    title_translated_html = str(title_translated_html) if title_translated_html is not None else ''
    
    if not query or not query.strip():
        return True
    
    query_lower = query.lower().strip()
    query_words = query_lower.split()
    
    clean_query_words = []
    for word in query_words:
        clean_word = re.sub(r'[^\w]', '', word, flags=re.UNICODE)
        if len(clean_word) >= 1:
            if clean_word.isascii() and clean_word.lower() in STOP_WORDS:
                continue
            clean_query_words.append(clean_word.lower() if clean_word.isascii() else clean_word)
    
    if len(clean_query_words) == 0:
        return True
    
    non_year_words = [w for w in clean_query_words if not (w.isdigit() and len(w) == 4 and w.startswith(('19', '20')))]
    if non_year_words:
        clean_query_words = non_year_words
    
    first_title_word = None
    for word in clean_query_words:
        if not word.isdigit():
            first_title_word = word
            break
        elif len(word) >= 3:
            first_title_word = word
            break
    
    combined_title = f"{title} {title_original_html} {title_translated_html}".lower()
    combined_title = combined_title.replace('.', ' ')
    combined_title = re.sub(r'\s+', ' ', combined_title)
    
    combined_title = remove_accents(combined_title)

    query_season = extract_query_season(query)
    if query_season is not None and not title_has_season(combined_title, query_season):
        return False

    query_episode_match = re.search(r'(?i)s(\d{1,2})e(\d{1,2})', query)
    if query_episode_match:
        query_season = query_episode_match.group(1).zfill(2)
        query_episode_num = int(query_episode_match.group(2))
        
        title_season_ep_pattern = rf'(?i)s{query_season}e(\d{{1,2}})(?:[\.\-\sE]|$)'
        title_season_ep_match = re.search(title_season_ep_pattern, title)
        
        if not title_season_ep_match:
            return False
        
        episode_pattern = rf'(?i)s{query_season}e(\d{{1,2}})(?:[\.\-\sE]+(\d{{1,2}}))*'
        episode_match = re.search(episode_pattern, title)
        episodes_in_title = []
        
        if episode_match:
            first_ep = int(episode_match.group(1))
            episodes_in_title = [first_ep]
            
            match_text = episode_match.group(0)
            first_ep_str = episode_match.group(1)
            remaining_text = match_text[len(f's{query_season}e{first_ep_str}'):]
            episode_numbers = re.findall(r'(\d{1,2})', remaining_text)
            
            for ep_str in episode_numbers:
                try:
                    ep_num = int(ep_str)
                    if ep_num > episodes_in_title[-1]:
                        episodes_in_title.append(ep_num)
                except (ValueError, TypeError):
                    break
        else:
            return False
        
        if len(episodes_in_title) == 1:
            if episodes_in_title[0] != query_episode_num:
                return False
        else:
            if query_episode_num not in episodes_in_title:
                if len(episodes_in_title) >= 2:
                    start_ep = episodes_in_title[0]
                    end_ep = episodes_in_title[-1]
                    if not (start_ep <= query_episode_num <= end_ep):
                        return False
                else:
                    return False
    
    title_normalized = combined_title
    
    matches = 0
    matched_words = []
    first_title_word_matched = False
    
    for query_word in clean_query_words:
        query_word_normalized = remove_accents(query_word)
        
        pattern = r'\b' + re.escape(query_word_normalized) + r'\b'
        if re.search(pattern, title_normalized, re.IGNORECASE | re.UNICODE):
            matches += 1
            matched_words.append(query_word)
            if query_word == first_title_word:
                first_title_word_matched = True
            continue
        
        partial_pattern = r'\b' + re.escape(query_word_normalized) + r'(?=\w)'
        if re.search(partial_pattern, title_normalized, re.IGNORECASE | re.UNICODE):
            matches += 1
            matched_words.append(query_word)
            if query_word == first_title_word:
                first_title_word_matched = True
            continue

        if query_word_normalized.isdigit():
            season_patterns = [f"s{query_word_normalized}", f"s{query_word_normalized.zfill(2)}"]
            if any(sp in title_normalized for sp in season_patterns):
                matches += 1
                matched_words.append(query_word)

    if len(clean_query_words) > 1 and first_title_word and not first_title_word_matched:
        return False
    



    if len(clean_query_words) == 1:
        return matches == 1
    elif len(clean_query_words) == 2:
        return matches == 2
    else:
        has_title_match = False
        for word in matched_words:
            if not word.isdigit():
                has_title_match = True
                break
            elif len(word) >= 3:
                has_title_match = True
                break
        
        total_words = len(clean_query_words)
        if total_words >= 5:
            first_words_to_check = clean_query_words[:min(4, total_words)]
            first_words_matches = sum(1 for w in first_words_to_check if w in matched_words)
            
            min_matches_percent = max(2, int(total_words * 0.3))
            if first_words_matches >= 2 or matches >= min_matches_percent:
                return has_title_match
            
            return False
        
        title_words_in_query = [w for w in clean_query_words if not w.isdigit() or len(w) >= 3]
        title_words_count = len(title_words_in_query)
        
        title_word_matches = sum(1 for w in matched_words if not w.isdigit() or len(w) >= 3)
        
        season_match_count = 0
        for word in clean_query_words:
            if word.isdigit() and len(word) <= 2:
                season_patterns = [f"s{word}", f"s{word.zfill(2)}"]
                if any(sp in title_normalized for sp in season_patterns):
                    season_match_count += 1
        
        total_valid_matches = title_word_matches + season_match_count
        
        if total_words == 3:
            if total_valid_matches < title_words_count:
                return False
            return True
        
        if total_words == 4:
            if total_valid_matches < 3:
                return False
            return True
        
        return matches >= 2 and has_title_match

