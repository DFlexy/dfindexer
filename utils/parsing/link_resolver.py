# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import codecs
import hashlib
import json
import re
import logging
import base64
import html
import string
import time
import threading
import zlib
from typing import Optional, List
from urllib.parse import urljoin, urlparse, parse_qs, unquote, quote
from bs4 import BeautifulSoup
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import protlink_key

logger = logging.getLogger(__name__)

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
    """Detecta systemads (e similares) pelo path go.php — independente do domínio."""
    if not href:
        return False
    try:
        parsed = urlparse(href.strip())
        path = (parsed.path or '').lower()
        return path.endswith('/go.php') or path.endswith('go.php') or '/go.php' in path
    except Exception:
        return 'go.php' in href.lower()

def is_redirect_chain_link(href: str) -> bool:
    """redirectad.net / enviar.php — id usa reverse+base64 (sem seguir redirects)."""
    if not href:
        return False
    lower = href.lower()
    return any(x in lower for x in ('redirectad.net', 'enviar.php', 'receber.php', 'recebi.php'))

def is_offline_decodable_link(href: str) -> bool:
    """Links cujo magnet está no parâmetro id (decodificação local, sem HTTP)."""
    if not href:
        return False
    if is_go_php_link(href):
        return False
    lower = href.lower()
    return 'get.php' in lower and 'id=' in lower

def is_embedded_go_payload_link(href: str) -> bool:
    """XBR Torrent e similares: ?go=<id>.p1.<base64-json> com hash no campo m."""
    if not href:
        return False
    try:
        parsed = urlparse(html.unescape(href.strip()))
        go_param = parse_qs(parsed.query).get('go', [None])[0]
        return bool(go_param and '.p1.' in go_param)
    except Exception:
        return '.p1.' in href and ('?go=' in href.lower() or '&go=' in href.lower())


def decode_embedded_go_payload_link(href: str) -> Optional[str]:
    """
    Decodifica ?go=<token>.p1.<base64-json> sem HTTP.
    JSON esperado: {"m":"<infohash hex>","t":"<display name>", ...}
    """
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
    """Decodifica id de redirectad.net / enviar.php: reverse(string) + base64 → magnet"""
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
    """Resolve go.php: decodifica id offline quando possível; senão GET e lê const redirect."""
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
    """Decodifica magnet de go.php/get.php (systemads) a partir do parâmetro id"""
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
        # Cai para o fluxo HTTP abaixo (get.php pode redirecionar para uma
        # página com o magnet, como systemads.xyz/go.php faz).

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
