"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import logging
import base64
import html
import string
import time
import threading
from typing import Optional, List
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from bs4 import BeautifulSoup
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import protlink_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes e configuração
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Regex pré-compilados
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

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
            redis_client.setex(protlink_key(protlink_url), 7 * 24 * 3600, magnet)
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
        # Evita crescimento indefinido do dicionário
        if len(_LAST_REQUEST_TIME) > _MAX_DOMAIN_ENTRIES:
            oldest = min(_LAST_REQUEST_TIME, key=_LAST_REQUEST_TIME.get)
            del _LAST_REQUEST_TIME[oldest]

    if delay > 0:
        time.sleep(delay)


def _unescape_js_string(s: str) -> str:
    return s.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')


def _make_headers(referer: str) -> dict:
    return {**_DEFAULT_HEADERS, 'Referer': referer}


# ---------------------------------------------------------------------------
# Extração de magnet do HTML (unificado)
# ---------------------------------------------------------------------------

def _extract_magnet_from_html(doc: BeautifulSoup, html_content: str) -> Optional[str]:
    # 1. Links <a> com href magnet
    for a in doc.select('a[href^="magnet:"], a[href*="magnet:"]'):
        href = a.get('href', '')
        if href.startswith('magnet:'):
            return href

    # 2. Meta refresh com magnet
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

    # 3. JavaScript patterns em <script> + busca raw de magnet (passada única)
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

    # 4. JavaScript raw patterns no HTML completo
    for pattern in _JS_RAW_MAGNET_PATTERNS:
        matches = pattern.findall(html_content)
        if matches:
            return max(matches, key=len)

    # 5. Atributos data-* (data-u, data-download, etc)
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

    # 6. Busca direta por regex no HTML
    match = _RE_MAGNET_FULL.search(html_content)
    if match:
        return match.group(0)

    return None


# ---------------------------------------------------------------------------
# Busca de redirect links no HTML
# ---------------------------------------------------------------------------

def _find_redirect_in_html(doc: BeautifulSoup, html_content: str, current_url: str) -> Optional[str]:
    # Links de redirect explícitos
    for a in doc.select('a[id*="redirect"], a[id*="Redirect"], a[href*="receber.php"], a[href*="redirecionando"]'):
        href = a.get('href', '')
        if href and ('receber.php' in href or 'redirecionando' in href.lower() or 'recebi.php' in href):
            return href

    # Meta refresh
    for meta in doc.select('meta[http-equiv="refresh"], meta[http-equiv="Refresh"]'):
        content = meta.get('content', '')
        match = _RE_META_REFRESH_URL.search(content)
        if match:
            return match.group(1).strip()

    # JavaScript redirects em <script> tags
    for script in doc.select('script'):
        script_text = script.string or ''
        if not script_text:
            continue
        for pattern in _JS_REDIRECT_PATTERNS:
            match = pattern.search(script_text)
            if match:
                return _unescape_js_string(match.group(1))

    # JavaScript redirect no HTML raw (fallback)
    match = _RE_LOCATION_REPLACE_HTML.search(html_content)
    if match:
        return _unescape_js_string(match.group(1))

    # Links para receber/recebi/link.php
    match = _RE_HREF_RECEBER_PHP.search(html_content)
    if match:
        return match.group(1)

    # Fallback para páginas tipo systemads
    is_systemads_page = ('systemads.org' in current_url or 'get.php' in current_url or 'seuvideo.xyz' in current_url)
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
                or 'systemads.org' in href_lower or 'seuvideo.xyz' in href_lower
            ):
                return href

        match = _RE_HREF_GET_PHP.search(html_content)
        if match:
            return match.group(1)

    return None


# ============================================================================
# GRUPO 1: VERIFICAÇÃO DE LINKS PROTEGIDOS
# ============================================================================

def is_protected_link(href: str, protected_patterns: Optional[List[str]] = None) -> bool:
    if not href:
        return False
    if protected_patterns is None:
        protected_patterns = [
            'get.php',
            '?go=',
            '&go=',
            'systemads.org',
            'seuvideo.xyz',
        ]
    return any(pattern in href for pattern in protected_patterns)


# ============================================================================
# GRUPO 2: RESOLVER DE LINKS DE ADWARE (systemads.org, seuvideo.xyz)
# ============================================================================

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

        # Reversed + base64 (systemads.org inverte o base64 do magnet)
        result = _try_b64_decode_magnet(id_param[::-1])
        if result:
            return result

        # Base64 direto
        result = _try_b64_decode_magnet(id_param)
        if result:
            return result

        # URL-decoded + base64 (caso esteja duplamente codificado)
        unquoted = unquote(id_param)
        if unquoted != id_param:
            result = _try_b64_decode_magnet(unquoted)
            if result:
                return result

        # Múltiplas camadas de decodificação
        try:
            current = id_param
            for _ in range(3):
                decoded_bytes = base64.b64decode(_pad_b64(current))
                decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
                if decoded_str.startswith('magnet:'):
                    return decoded_str
                current = decoded_str
        except Exception:
            pass

        return None
    except Exception:
        return None


# ============================================================================
# GRUPO 3: RESOLVER DE DATA-U
# ============================================================================

def _unshuffle_string(shuffled: str) -> Optional[str]:
    # Replica a função unshuffleString do JavaScript do Starck Filmes (step=3)
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


# ============================================================================
# GRUPO 4: RESOLVER PRINCIPAL DE LINKS PROTEGIDOS
# ============================================================================

def resolve_protected_link(protlink_url: str, session: requests.Session, base_url: str = '', redis=None) -> Optional[str]:
    redis_client = redis or get_redis_client()

    cached = _get_cached(redis_client, protlink_url)
    if cached:
        return cached

    # Tenta decodificação offline primeiro (sem HTTP)
    if 'systemads.org' in protlink_url or 'seuvideo.xyz' in protlink_url or 'get.php' in protlink_url:
        decoded_magnet = decode_ad_link(protlink_url)
        if decoded_magnet:
            _cache_result(redis_client, protlink_url, decoded_magnet)
            return decoded_magnet

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

                # Redirect HTTP (301/302/303/307/308)
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

                # Processa resposta HTML
                try:
                    html_content = response.text
                    doc = BeautifulSoup(html_content, 'lxml')
                except Exception as e:
                    logger.error(f"Erro ao processar resposta HTML: {e}")
                    break

                # Extrai magnet (todas as estratégias unificadas)
                magnet = _extract_magnet_from_html(doc, html_content)
                if magnet:
                    _cache_result(redis_client, protlink_url, magnet)
                    return magnet

                # Busca redirect no HTML para seguir
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
