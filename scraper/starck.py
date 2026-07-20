# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import html
import json
import re
import time
import logging
from datetime import datetime
from utils.parsing.date_extraction import parse_date_from_string
from typing import List, Dict, Optional, Callable, Tuple
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from app.config import Config
from scraper.base import BaseScraper
from utils.http.proxy import get_proxy_dict, get_proxy_url, is_proxy_local
from magnet.parser import MagnetParser
from utils.text.utils import find_year_from_text, find_sizes_from_text
from utils.parsing.audio_extraction import detect_audio_from_html
from utils.logging import format_error, format_link_preview, ScraperLogContext
from utils.parsing.link_resolver import decode_data_u

logger = logging.getLogger(__name__)

_log_ctx = ScraperLogContext("Starck", logger)

_RE_STARCK_DATA_U_DQ = re.compile(r'data-u\s*=\s*"([^"]*)"', re.I)
_RE_STARCK_DATA_U_SQ = re.compile(r"data-u\s*=\s*'([^']*)'", re.I)

# Fallback de UI/JS legado — só usado se o protocolo (timeMonit / endpoint) sumir.
_GATE_SOFT_MARKERS = (
    'createGenericNotification',
    'Análise de acesso',
    'Comunicado Importante',
    'Ir para o novo site',
    'sendVerification',
    'unshuffleString',
    'Verificação de Segurança',
    'Confirmo que sou um usuário humano',
    'Continuar para o site',
    'Verificação Automática',
    'Verificação concluída',
)
_DEFAULT_TIME_MONIT = '14542588'
_DEFAULT_VERIFY_PATH = '/current-address'
# Aceita timeMonit:"..." / timeMonit: "..." / "timeMonit":"..."
_TIME_MONIT_RE = re.compile(
    r'["\']?timeMonit["\']?\s*:\s*["\']([^"\']+)["\']',
    re.I,
)
# Literais JS curtos (path ofuscado ou não) candidatos a virar o endpoint.
_RE_JS_PATH_LITERAL = re.compile(r'["\'](/?[A-Za-z0-9_./-]{6,64})["\']')


def _unshuffle_string(text: str) -> str:
    if not text or not str(text).strip():
        return ''
    s = str(text).strip()
    if (len(s) >= 2) and ((s[0] == s[-1]) and s[0] in '"\''):
        s = s[1:-1]
    length = len(s)
    if length == 0:
        return ''
    used = [False] * length
    out = [''] * length
    n = 0
    for t in range(length):
        while used[n]:
            n = (n + 1) % length
        used[n] = True
        out[t] = s[n]
        n = (n + 3) % length
    return ''.join(out)


def _normalize_verify_path(path: str) -> Optional[str]:
    if not path:
        return None
    p = str(path).strip()
    if (len(p) >= 2) and ((p[0] == p[-1]) and p[0] in '"\''):
        p = p[1:-1].strip()
    if not p:
        return None
    if not p.startswith('/'):
        p = '/' + p
    # Só aceita path relativo simples (evita URLs absolutas acidentais).
    if '://' in p or '?' in p or '#' in p or ' ' in p:
        return None
    return p


def _is_current_address_path(path: str) -> bool:
    norm = _normalize_verify_path(path)
    return bool(norm) and norm.rstrip('/').lower() == _DEFAULT_VERIFY_PATH


def _scan_verify_path_candidates(chunk: str) -> Tuple[Optional[str], Optional[str]]:
    """Retorna (path_conhecido, path_api_fallback) a partir de literais JS."""
    if not chunk:
        return None, None
    fallback = None
    seen: set = set()
    for match in _RE_JS_PATH_LITERAL.finditer(chunk):
        raw = match.group(1)
        if raw in seen:
            continue
        seen.add(raw)
        for candidate in (raw, _unshuffle_string(raw)):
            if not candidate:
                continue
            if _is_current_address_path(candidate):
                return _DEFAULT_VERIFY_PATH, None
            norm = _normalize_verify_path(candidate)
            if not norm:
                continue
            leaf = norm.rsplit('/', 1)[-1]
            if '.' in leaf:
                continue
            if fallback is None and 6 <= len(norm) <= 48:
                fallback = norm
    return None, fallback


def _discover_starck_verify_path(html_content: str) -> Optional[str]:
    """Descobre o path do POST mesmo com literal embaralhado ou renomeado."""
    if not html_content:
        return None
    if _DEFAULT_VERIFY_PATH in html_content:
        return _DEFAULT_VERIFY_PATH

    known, _ = _scan_verify_path_candidates(html_content)
    if known:
        return known

    # Endpoint renomeado: pega path ofuscado na vizinhança do payload timeMonit.
    idx = html_content.find('timeMonit')
    if idx >= 0:
        window = html_content[max(0, idx - 400): idx + 3000]
        known, near = _scan_verify_path_candidates(window)
        if known:
            return known
        if near:
            return near
    return None


def _has_starck_catalog_html(html_content: str) -> bool:
    """Página real (home/busca/detalhe) — nunca tratar como gate."""
    if not html_content:
        return False
    if 'post-catalog' in html_content and '/catalog/' in html_content:
        return True
    if 'sub-item' in html_content and '/catalog/' in html_content:
        return True
    if 'post-buttons' in html_content or 'data-u=' in html_content:
        return True
    if 'class="post"' in html_content or "class='post'" in html_content:
        return True
    return False


def _soft_gate_score(html_content: str) -> int:
    score = sum(1 for marker in _GATE_SOFT_MARKERS if marker in html_content)
    low = html_content.lower()
    # UI genérica de challenge (textos mudam, mas costumam manter "verifica" + humano/segurança).
    if 'verifica' in low and (
        'humano' in low or 'segurança' in low or 'seguranca' in low or 'acesso' in low
    ):
        score += 1
    return score


def _is_starck_gate_page(html_content: str) -> bool:
    """
    Detecção resiliente: prioriza o protocolo da gate (timeMonit + endpoint),
    não o texto da UI — que o site troca com frequência.
    """
    if not html_content:
        return False
    if _has_starck_catalog_html(html_content):
        return False

    has_time_monit = 'timeMonit' in html_content
    verify_path = _discover_starck_verify_path(html_content)

    # Assinatura do protocolo — sobrevive a redesign de HTML/CSS/copy.
    if has_time_monit or verify_path:
        return True

    # Último recurso: UI legada / genérica sem catálogo.
    return _soft_gate_score(html_content) >= 2


def _extract_time_monit(html_content: str) -> str:
    match = _TIME_MONIT_RE.search(html_content or '')
    return match.group(1) if match else _DEFAULT_TIME_MONIT


def _resolve_starck_verify_url(origin: str, html_content: str) -> str:
    path = _discover_starck_verify_path(html_content) or _DEFAULT_VERIFY_PATH
    return urljoin(f'{origin.rstrip("/")}/', path.lstrip('/'))


def _invalidate_starck_gate_cache(redis, url: str) -> None:
    try:
        from cache.http_cache import get_http_cache
        from cache.redis_keys import html_long_key, html_short_key

        get_http_cache().delete(url)
        if redis:
            redis.delete(html_long_key(url))
            redis.delete(html_short_key(url))
    except Exception:
        pass


def _normalize_starck_base_url(url: str) -> Optional[str]:
    if not url or not url.startswith('http'):
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f'{parsed.scheme}://{parsed.netloc}/'


def _post_starck_verification_requests(
    session: requests.Session,
    verify_url: str,
    origin: str,
    referer: str,
    time_monit: str,
) -> Optional[str]:
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
        'Accept': '*/*',
        'Origin': origin,
        'Referer': referer,
    }
    payload = json.dumps({'timeMonit': time_monit})
    # Endpoint protegido costuma ser lento sob SOCKS; tolerance maior + retry.
    base_timeout = max(Config.HTTP_REQUEST_TIMEOUT, 30)
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = session.post(
                verify_url,
                data=payload,
                headers=headers,
                timeout=base_timeout,
            )
            break
        except requests.exceptions.ReadTimeout as e:
            if attempt < max_attempts:
                _log_ctx.warning(
                    'Timeout na verificação de acesso (tentativa {}/{}), retentando: {}',
                    attempt, max_attempts, type(e).__name__,
                )
                time.sleep(1.0 * attempt)
                continue
            _log_ctx.warning(
                'Timeout na verificação de acesso após {} tentativas para {}',
                max_attempts, verify_url,
            )
            return None
        except requests.exceptions.RequestException as e:
            _log_ctx.warning(
                'Erro de rede na verificação de acesso: {} para {}',
                type(e).__name__, verify_url,
            )
            return None
    else:
        return None

    if not response.ok:
        _log_ctx.warning(
            'Verificação de acesso retornou HTTP {} para {}',
            response.status_code,
            verify_url,
        )
        return None
    return _unshuffle_string(response.text)


def _post_starck_verification_flaresolverr(
    flaresolverr_client,
    session_id: str,
    verify_url: str,
    referer: str,
    time_monit: str,
) -> Optional[str]:
    payload = {
        'cmd': 'request.post',
        'url': verify_url,
        'session': session_id,
        'postData': json.dumps({'timeMonit': time_monit}),
        'headers': {
            'Content-Type': 'application/json; charset=UTF-8',
            'Referer': referer,
        },
        'maxTimeout': 60000,
    }
    proxy_url = get_proxy_url()
    if proxy_url:
        payload['proxy'] = proxy_url
    proxy_dict = get_proxy_dict() if not is_proxy_local() else None
    try:
        response = requests.post(
            flaresolverr_client.api_url,
            json=payload,
            timeout=90,
            headers={'Content-Type': 'application/json'},
            proxies=proxy_dict if proxy_dict else None,
        )
        response.raise_for_status()
        result = response.json()
        if result.get('status') != 'ok':
            _log_ctx.warning(
                'FlareSolverr falhou na verificação: {}',
                result.get('message', 'erro desconhecido'),
            )
            return None
        body = result.get('solution', {}).get('response', '')
        return _unshuffle_string(body) if body else None
    except Exception as e:
        _log_ctx.warning('Erro na verificação via FlareSolverr: {}', type(e).__name__)
        return None


def _bypass_starck_access(
    session: requests.Session,
    url: str,
    html_content: str,
    referer: Optional[str] = None,
    flaresolverr_client=None,
    flaresolverr_base_url: Optional[str] = None,
    is_test: bool = False,
) -> Optional[str]:
    parsed = urlparse(url)
    origin = f'{parsed.scheme}://{parsed.netloc}'
    verify_url = _resolve_starck_verify_url(origin, html_content)
    page_referer = referer or url
    time_monit = _extract_time_monit(html_content)
    _log_ctx.debug(
        'Bypass gate: verify_url={} timeMonit={}',
        verify_url,
        time_monit,
    )

    resolved: Optional[str] = None
    if flaresolverr_client and flaresolverr_base_url:
        fs_session = flaresolverr_client.get_or_create_session(
            flaresolverr_base_url,
        )
        if fs_session:
            resolved = _post_starck_verification_flaresolverr(
                flaresolverr_client,
                fs_session,
                verify_url,
                page_referer,
                time_monit,
            )

    if resolved is None:
        resolved = _post_starck_verification_requests(
            session,
            verify_url,
            origin,
            page_referer,
            time_monit,
        )

    if resolved is None:
        return None
    if resolved and 'http' in resolved.lower():
        return resolved
    return ''


def _apply_resolved_base_url(scraper: 'StarckScraper', resolved_url: str) -> None:
    new_base = _normalize_starck_base_url(resolved_url)
    if not new_base:
        return
    current = _normalize_starck_base_url(scraper.base_url)
    if current and urlparse(new_base).netloc == urlparse(current).netloc:
        return
    scraper.base_url = new_base


def _starck_raw_data_u_values(page_html: str) -> List[str]:
    if not page_html:
        return []
    low = page_html.lower()
    i = low.find('post-buttons')
    if i < 0:
        chunk = page_html
    else:
        j = low.find('post-content', i + 1)
        chunk = page_html[i:j] if j > i else page_html[i : i + 900000]
    out: List[str] = []
    seen = set()
    for rx in (_RE_STARCK_DATA_U_DQ, _RE_STARCK_DATA_U_SQ):
        for m in rx.finditer(chunk):
            v = m.group(1).strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    return out

class StarckScraper(BaseScraper):
    SCRAPER_TYPE = "starck"
    DEFAULT_BASE_URL = "https://www.starckfilmes-v23.com/"
    DISPLAY_NAME = "Starck"
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        super().__init__(base_url, use_flaresolverr)
        self.search_url = "?s="
        self.page_pattern = "page/{}/"
        self._gate_bypass_attempted: set = set()

    def _fetch_document(self, url: str, referer: str = ''):
        soup = super()._fetch_document(url, referer)
        page_html = self._get_fetched_html() or ''

        if not _is_starck_gate_page(page_html):
            return soup

        gate_key = url.rstrip('/').lower()
        if gate_key in self._gate_bypass_attempted:
            _log_ctx.warning('Página de verificação persistente após bypass: {}', url[:80])
            return None
        self._gate_bypass_attempted.add(gate_key)

        _invalidate_starck_gate_cache(self.redis, url)

        resolved = _bypass_starck_access(
            session=self.session,
            url=url,
            html_content=page_html,
            referer=referer or self.base_url,
            flaresolverr_client=self.flaresolverr_client if self.use_flaresolverr else None,
            flaresolverr_base_url=self.base_url,
            is_test=self._is_test,
        )
        if resolved is None:
            _log_ctx.warning('Falha ao passar pela verificação de acesso')
            return None

        if resolved:
            _apply_resolved_base_url(self, resolved)

        return super()._fetch_document(url, referer)
    
    def search(
        self,
        query: str,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        skip_trackers: bool = False,
        skip_metadata: bool = False,
    ) -> List[Dict]:
        return self._default_search(
            query, filter_func, skip_trackers=skip_trackers, skip_metadata=skip_metadata
        )
    
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        links = []
        seen_hrefs = set()
        
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog')
        if not catalog_div:
            catalog_div = doc
        
        items = catalog_div.select('.item')
        
        for item in items:

            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            
            all_links = sub_item.find_all('a', href=lambda h: h and 'catalog' in h)
            link_elem = None
            
            for link in all_links:
                parent_h3 = link.find_parent('h3')
                title_attr = link.get('title')
                
                if not parent_h3 and title_attr and title_attr.strip():
                    link_elem = link
                    break
            
            if link_elem:
                href = link_elem.get('href')
                title_attr = link_elem.get('title')
                
                if href and title_attr and title_attr.strip():
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    if href not in seen_hrefs:
                        links.append(href)
                        seen_hrefs.add(href)
        
        _log_ctx.debug(f"Encontrados {len(items)} itens na página e extraídos {len(links)} links únicos")
        return links
    
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        return self._default_get_page(page, max_items, is_test=is_test)
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        links = []
        seen_hrefs = set()
        
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog')
        if not catalog_div:
            catalog_div = doc
        
        for item in catalog_div.select('.item'):

            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            
            link_elem = sub_item.find('a', href=lambda h: h and 'catalog' in h, title=lambda t: t and t.strip())
            
            if link_elem:
                href = link_elem.get('href')
                title_attr = link_elem.get('title')
                
                if href and title_attr and title_attr.strip():
                    if not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    if href not in seen_hrefs:
                        links.append(href)
                        seen_hrefs.add(href)
        
        return links
    
    def _collect_search_result_titles(self, doc: BeautifulSoup) -> Dict[str, str]:
        """Starck: título do card via attr title / h3 a (além do coletor base)."""
        title_by_url = super()._collect_search_result_titles(doc)
        catalog_div = doc.select_one('div.post-catalog, div.home.post-catalog') or doc
        for item in catalog_div.select('.item'):
            sub_item = item.select_one('div.sub-item')
            if not sub_item:
                continue
            link_elem = sub_item.find(
                'a',
                href=lambda h: h and 'catalog' in h,
                title=lambda t: t and str(t).strip(),
            )
            if not link_elem:
                h3_link = sub_item.select_one('h3 a[href]')
                if h3_link and 'catalog' in (h3_link.get('href') or ''):
                    link_elem = h3_link
            if not link_elem:
                continue
            href = (link_elem.get('href') or '').strip()
            title_text = (link_elem.get('title') or link_elem.get_text(strip=True) or '').strip()
            normalized = self._normalize_search_result_url(href)
            if normalized and title_text and normalized not in title_by_url:
                title_by_url[normalized] = title_text
        return title_by_url

    def _filter_links_by_result_titles(self, doc: BeautifulSoup, links: List[str], query: str) -> List[str]:
        """Filtra cards Starck; aceita título PT quando a season da query bate."""
        from utils.text.query import (
            check_query_match,
            extract_query_season,
            slug_has_season,
            title_has_season,
        )

        if not links or not query or not query.strip():
            return links

        title_by_url = self._collect_search_result_titles(doc)
        season = extract_query_season(query)
        filtered: List[str] = []
        for href in links:
            if season is not None:
                verdict = slug_has_season(href, season)
                if verdict is False:
                    continue
                if verdict is True:
                    filtered.append(href)
                    continue

            normalized = self._normalize_search_result_url(href)
            title_text = title_by_url.get(normalized)
            if not title_text:
                filtered.append(href)
                continue
            if check_query_match(query, title_text, '', ''):
                filtered.append(href)
                continue
            # Query EN vs card PT: mantém se a season do título confere.
            if season is not None and title_has_season(title_text, season):
                filtered.append(href)
        return filtered

    def _search_variations(self, query: str) -> List[str]:
        from urllib.parse import urljoin, quote
        from utils.text.constants import STOP_WORDS
        from utils.text.query import strip_stop_words_keep_season

        links = []
        seen_urls = set()
        variations = [query]

        stripped = strip_stop_words_keep_season(query)
        if stripped and stripped != query:
            variations.append(stripped)

        query_words = query.split()

        if len(query_words) >= 2 and query_words[-1].isdigit() and len(query_words[-1]) == 4 and query_words[-1][:2] in ('19', '20'):
            without_year = ' '.join(query_words[:-1])
            if without_year not in variations:
                variations.append(without_year)

        if len(query_words) > 1 and len(query_words) < 3:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])

        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue

            page_links = self._extract_search_results(doc)
            # Filtra pelo título do card (PT) — páginas EN ainda passam pelo
            # skip em _get_torrents_from_page via original_title.
            page_links = self._filter_links_by_result_titles(doc, page_links, variation)
            for href in page_links:
                absolute_url = urljoin(self.base_url, href)
                if absolute_url not in seen_urls:
                    links.append(absolute_url)
                    seen_urls.add(absolute_url)

        return links
    
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        absolute_link = urljoin(self.base_url, link) if link and not link.startswith('http') else link
        doc = self.get_document(absolute_link, self.base_url)
        if not doc:
            return []
        
        from utils.parsing.date_extraction import extract_date_from_page
        date = extract_date_from_page(doc, absolute_link, self.SCRAPER_TYPE)
        
        torrents = []
        post = doc.find('div', class_='post')
        if not post:
            self._log_structure_miss(absolute_link, 'div.post')
            return []
        
        capa = post.find('div', class_='capa')
        if not capa:
            self._log_structure_miss(absolute_link, 'div.capa')
            return []
        
        page_title = ''
        title_elem = capa.select_one('.post-description > h2')
        if title_elem:
            page_title = title_elem.get_text(strip=True)
        
        original_title = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                if 'Nome Original:' in spans[0].get_text():
                    original_title = spans[1].get_text(strip=True)
                    break
        
        title_translated_processed = ''
        for p in capa.select('.post-description p'):
            spans = p.find_all('span')
            if len(spans) >= 2:
                span_text = spans[0].get_text()
                if 'Título Traduzido:' in span_text or 'Titulo Traduzido:' in span_text:
                    span2 = spans[1]
                    for tag in span2.find_all(['strong', 'em', 'b', 'i']):
                        tag.unwrap()
                    title_translated_processed = span2.get_text(strip=True)
                    title_translated_processed = html.unescape(title_translated_processed)
                    from utils.text.cleaning import clean_title_translated_processed
                    title_translated_processed = clean_title_translated_processed(title_translated_processed)
                    break
        
        if not title_translated_processed:
            post_title_elem = capa.select_one('h2.post-title')
            if post_title_elem:
                title_translated_processed = post_title_elem.get_text(strip=True)
                title_translated_processed = html.unescape(title_translated_processed)
                from utils.text.cleaning import clean_title_translated_processed
                title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        if title_translated_processed:
            title_translated_processed = re.sub(r'<[^>]+>', '', title_translated_processed)
            title_translated_processed = html.unescape(title_translated_processed)
            from utils.text.cleaning import clean_title_translated_processed
            title_translated_processed = clean_title_translated_processed(title_translated_processed)
        
        if self._should_skip_page_by_query(
            page_title, original_title, title_translated_processed, absolute_link,
        ):
            return []

        year = ''
        sizes = []
        imdb = ''
        audio_info = ''
        audio_html_content = ''
        all_paragraphs_html = []
        for p in capa.select('.post-description p'):
            text = ' '.join(span.get_text() for span in p.find_all('span'))
            html_content = str(p)
            all_paragraphs_html.append(html_content)
            y = find_year_from_text(text, page_title)
            if y:
                year = y
            sizes.extend(find_sizes_from_text(text))
            
            if not audio_info:
                audio_info = detect_audio_from_html(html_content)
        
        if all_paragraphs_html:
            audio_html_content = ' '.join(all_paragraphs_html)
        
        all_links = post.select('a[href]')

        magnet_links: List[str] = []
        seen_hashes: set = set()
        seen_data_u: set = set()

        def _add_magnet(magnet: str) -> None:
            if not magnet or not magnet.startswith('magnet:'):
                return
            try:
                key = MagnetParser.parse(magnet)['info_hash'].lower()
            except Exception:
                key = magnet
            if key in seen_hashes:
                return
            seen_hashes.add(key)
            magnet_links.append(magnet)

        def _append_decoded_magnets_from_data_u_values(values: List[str]) -> None:
            for data_u_value in values:
                v = html.unescape(data_u_value.strip())
                if not v or v in seen_data_u:
                    continue
                seen_data_u.add(v)
                decoded_magnet = decode_data_u(v)
                if decoded_magnet:
                    _add_magnet(decoded_magnet)

        # Starck expõe o magnet ofuscado no atributo data-u (decodificação local,
        # estável). O href é um get.php protegido server-side que hoje não
        # decodifica offline (AES com rastrear=Stark) nem via HTTP — gerava os
        # logs "Falha ao decodificar get.php". Priorizamos o data-u e só
        # tentamos o href quando a âncora não tem data-u.
        page_html = self._get_fetched_html()
        _append_decoded_magnets_from_data_u_values(_starck_raw_data_u_values(page_html))

        buttons_root = post.select_one('.post-buttons') or post
        for elem in buttons_root.select('[data-u]'):
            data_u_value = (elem.get('data-u') or '').strip()
            if not data_u_value or data_u_value in seen_data_u:
                continue
            seen_data_u.add(data_u_value)
            decoded_magnet = decode_data_u(data_u_value)
            if decoded_magnet:
                _add_magnet(decoded_magnet)

        # Fallback: âncoras sem data-u (magnets diretos ou links protegidos
        # resolvíveis via href). Pula get.php do Starck, que nunca resolve.
        for link in all_links:
            if link.get('data-u'):
                continue
            href = link.get('href', '')
            if not href or 'get.php' in href.lower():
                continue
            resolved_magnet = self._resolve_link(href)
            if resolved_magnet:
                _add_magnet(resolved_magnet)

        if not magnet_links:

            return []
        
        from utils.parsing.legend_extraction import extract_legenda_from_page, determine_legend_info
        legenda = extract_legenda_from_page(doc, scraper_type='starck')
        legend_info = determine_legend_info(legenda) if legenda else None

        from core.builders import build_torrents_from_magnets
        return build_torrents_from_magnets(
            magnet_links=magnet_links,
            sizes=sizes,
            page_title=page_title,
            original_title=original_title,
            title_translated_processed=title_translated_processed,
            year=year,
            imdb=imdb,
            audio_info=audio_info,
            audio_html_content=audio_html_content if audio_html_content else None,
            absolute_link=absolute_link,
            date=date,
            legend_info=legend_info,
            skip_metadata=self._skip_metadata,
            doc=doc,
            scraper_type=self.SCRAPER_TYPE,
            log_ctx=_log_ctx,
        )

