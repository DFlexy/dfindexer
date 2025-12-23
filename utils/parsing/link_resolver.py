"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import logging
import base64
import html
import time
import threading
from typing import Optional, List
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from bs4 import BeautifulSoup
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import protlink_key

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()

# Rate limiting
_LOCK = threading.Lock()
_LAST_REQUEST_TIME = {}
_MIN_DELAY_BETWEEN_REQUESTS = 0.2
_MAX_CONCURRENT_REQUESTS = 5
_REQUEST_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT_REQUESTS)


# ============================================================================
# GRUPO 1: VERIFICAÇÃO DE LINKS PROTEGIDOS
# ============================================================================

def is_protected_link(href: str, protected_patterns: Optional[List[str]] = None) -> bool:
    # Verifica se um link é protegido e precisa ser resolvido
    if not href:
        return False
    
    # Padrões padrão (configuráveis)
    if protected_patterns is None:
        protected_patterns = [
            'get.php',
            '?go=',
            '&go='
        ]
    
    return any(pattern in href for pattern in protected_patterns)


# ============================================================================
# GRUPO 2: RESOLVER DE LINKS DE ADWARE (systemads.org, seuvideo.xyz)
# ============================================================================

def decode_ad_link(ad_link: str) -> Optional[str]:
    # Decodifica link de adware (systemads.org, seuvideo.xyz)
    if not ad_link:
        return None
    
    try:
        parsed_url = urlparse(ad_link)
        query_params = parse_qs(parsed_url.query)
        id_param = query_params.get('id', [None])[0]
        
        if not id_param:
            return None
        
        # Tenta diferentes métodos de decodificação base64
        methods = [
            lambda x: x,
            lambda x: unquote(x),
            lambda x: x.replace('-', '+').replace('_', '/'),
        ]
        
        for method in methods:
            try:
                processed = method(id_param)
                padding = 4 - len(processed) % 4
                if padding != 4:
                    processed = processed + '=' * padding
                
                decoded_bytes = base64.b64decode(processed)
                decoded = decoded_bytes.decode('utf-8')
                
                if decoded.startswith('magnet:'):
                    return decoded
            except Exception:
                continue
        
        # Tenta múltiplas camadas de decodificação
        try:
            current = id_param
            for _ in range(3):
                padding = 4 - len(current) % 4
                if padding != 4:
                    current = current + '=' * padding
                
                decoded_bytes = base64.b64decode(current)
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
    # Replica a função unshuffleString do JavaScript do Starck Filmes
    # Desembaralha uma string usando step=3
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
    # Decodifica o atributo data-u seguindo o processo do JavaScript do Starck Filmes
    if not data_u_value:
        return None
    
    try:
        unshuffled = _unshuffle_string(data_u_value)
        if not unshuffled:
            return None
        
        if "magnet:" in unshuffled:
            return unshuffled
        
        if unshuffled.lower().startswith(("http://", "https://")):
            return unshuffled
        
        return None
        
    except Exception:
        return None


# ============================================================================
# GRUPO 4: RESOLVER DE BASE64 EMBARALHADO
# ============================================================================

def _extract_base64_from_scrambled(text: str) -> Optional[str]:
    # Tenta extrair Base64 de texto potencialmente embaralhado
    import string
    
    base64_chars = set(string.ascii_letters + string.digits + '+/=')
    cleaned = ''.join(c for c in text if c in base64_chars or c in '&')
    
    if '&' in cleaned:
        parts = cleaned.split('&')
        
        concatenated = ''.join(parts)
        result = _try_decode_base64_sequence(concatenated)
        if result:
            return result
        
        concatenated = ''.join(reversed(parts))
        result = _try_decode_base64_sequence(concatenated)
        if result:
            return result
        
        for part in parts:
            if len(part) >= 20:
                result = _try_decode_base64_sequence(part)
                if result:
                    return result
    else:
        result = _try_decode_base64_sequence(cleaned)
        if result:
            return result
    
    return None


def _try_decode_base64_sequence(text: str) -> Optional[str]:
    # Tenta decodificar uma sequência que pode ser Base64 válido
    if not text or len(text) < 20:
        return None
    
    # Remove caracteres não-Base64
    import string
    base64_chars = set(string.ascii_letters + string.digits + '+/=')
    cleaned = ''.join(c for c in text if c in base64_chars)
    
    if len(cleaned) < 20:
        return None
    
    # Tenta diferentes pontos de início e comprimentos
    for start in range(min(5, len(cleaned))):
        # Tenta diferentes comprimentos (múltiplos de 4)
        for length in range(20, min(len(cleaned) - start + 1, 500), 4):
            candidate = cleaned[start:start + length]
            
            if len(candidate) < 20:
                continue
            
            try:
                # Adiciona padding se necessário
                padding = 4 - len(candidate) % 4
                if padding != 4:
                    candidate_padded = candidate + '=' * padding
                else:
                    candidate_padded = candidate
                
                decoded_bytes = base64.b64decode(candidate_padded)
                decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
                
                if decoded_str.startswith('magnet:'):
                    return decoded_str
            except Exception:
                continue
    
    return None


# ============================================================================
# GRUPO 5: RESOLVER PRINCIPAL DE LINKS PROTEGIDOS (Redirects HTTP + Extração HTML)
# ============================================================================

def resolve_protected_link(protlink_url: str, session: requests.Session, base_url: str = '', redis=None) -> Optional[str]:
    # Resolve link protegido seguindo redirects e extraindo o magnet link
    # Usa Redis primeiro, memória se Redis não disponível
    redis_client = redis or get_redis_client()
    
    # Tenta Redis primeiro
    if redis_client:
        try:
            cache_key = protlink_key(protlink_url)
            cached = redis_client.get(cache_key)
            if cached:
                return cached.decode('utf-8')
        except Exception:
            pass
    
    # Usa memória apenas se Redis não está disponível desde o início
    if not redis_client:
        if not hasattr(_request_cache, 'protlink_cache'):
            _request_cache.protlink_cache = {}
        
        if protlink_url in _request_cache.protlink_cache:
            cached_magnet = _request_cache.protlink_cache[protlink_url]
            return cached_magnet
    
    # Tenta resolver usando decodificação de adware primeiro
    if 'systemads.org' in protlink_url or 'seuvideo.xyz' in protlink_url or 'get.php' in protlink_url:
        decoded_magnet = decode_ad_link(protlink_url)
        if decoded_magnet:
            # Tenta Redis primeiro
            if redis_client:
                try:
                    cache_key = protlink_key(protlink_url)
                    redis_client.setex(cache_key, 7 * 24 * 3600, decoded_magnet)
                except Exception:
                    pass
            else:
                # Salva em memória apenas se Redis não disponível
                if not hasattr(_request_cache, 'protlink_cache'):
                    _request_cache.protlink_cache = {}
                _request_cache.protlink_cache[protlink_url] = decoded_magnet
            return decoded_magnet
    
    redirect_count = 0
    
    with _REQUEST_SEMAPHORE:
        try:
            current_url = protlink_url
            max_redirects = 20
            timeout = 5
            
            while redirect_count < max_redirects:
                # Rate limiting por domínio
                try:
                    parsed_url = urlparse(current_url)
                    domain = parsed_url.netloc or parsed_url.hostname or 'unknown'
                    
                    with _LOCK:
                        last_time = _LAST_REQUEST_TIME.get(domain, 0)
                        current_time = time.time()
                        time_since_last = current_time - last_time
                        
                        if time_since_last < _MIN_DELAY_BETWEEN_REQUESTS:
                            delay = _MIN_DELAY_BETWEEN_REQUESTS - time_since_last
                            time.sleep(delay)
                        
                        _LAST_REQUEST_TIME[domain] = time.time()
                except Exception:
                    pass
                
                request_timeout = 10 if 't.co' in current_url else timeout
                
                try:
                    response = session.get(
                        current_url,
                        allow_redirects=False,
                        timeout=request_timeout,
                        headers={
                            'Referer': base_url if redirect_count == 0 else current_url,
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                            'Upgrade-Insecure-Requests': '1'
                        }
                    )
                except requests.exceptions.ReadTimeout:
                    if 't.co' in current_url:
                        try:
                            response = session.get(
                                current_url,
                                allow_redirects=True,
                                timeout=10,
                                headers={
                                    'Referer': base_url if redirect_count == 0 else current_url,
                                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                                    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                                    'Accept-Encoding': 'gzip, deflate',
                                    'Connection': 'keep-alive',
                                    'Upgrade-Insecure-Requests': '1'
                                }
                            )
                            current_url = response.url
                        except Exception:
                            break
                    else:
                        break
                except requests.exceptions.RequestException:
                    break
                
                # Processa redirects HTTP (301, 302, etc)
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location', '')
                    
                    if location.startswith('magnet:'):
                        # Tenta Redis primeiro
                        if redis_client:
                            try:
                                cache_key = protlink_key(protlink_url)
                                redis_client.setex(cache_key, 7 * 24 * 3600, location)
                            except Exception:
                                pass
                        else:
                            # Salva em memória apenas se Redis não disponível
                            if not hasattr(_request_cache, 'protlink_cache'):
                                _request_cache.protlink_cache = {}
                            _request_cache.protlink_cache[protlink_url] = location
                        return location
                    
                    if location:
                        current_url = urljoin(current_url, location)
                        redirect_count += 1
                        continue
                    else:
                        break
                
                # Processa resposta HTML (status 200)
                if response.status_code == 200:
                    try:
                        html_content = response.text
                        
                        if html_content and (html_content.startswith('\x1f\x8b') or '\x00' in html_content[:100] or not html_content.strip()):
                            import gzip
                            try:
                                html_content = gzip.decompress(response.content).decode('utf-8')
                            except Exception:
                                html_content = response.content.decode('utf-8', errors='ignore')
                        
                        doc = BeautifulSoup(html_content, 'html.parser')
                        redirect_link = None
                        
                        # Busca redirect no HTML (links, meta refresh, JavaScript)
                        for a in doc.select('a[id*="redirect"], a[id*="Redirect"], a[href*="receber.php"], a[href*="redirecionando"]'):
                            href = a.get('href', '')
                            if href and ('receber.php' in href or 'redirecionando' in href.lower() or 'recebi.php' in href):
                                redirect_link = href
                                break
                        
                        if not redirect_link:
                            for meta in doc.select('meta[http-equiv="refresh"], meta[http-equiv="Refresh"]'):
                                content = meta.get('content', '')
                                url_match = re.search(r'url\s*=\s*([^;]+)', content, re.IGNORECASE)
                                if url_match:
                                    redirect_link = url_match.group(1).strip()
                                    break
                        
                        if not redirect_link:
                            for script in doc.select('script'):
                                script_text = script.string or ''
                                if script_text:
                                    patterns = [
                                        r'location\.replace\(["\']([^"\']+)["\']\)',
                                        r'location\.replace\(["\']((?:[^"\'\\]|\\.)+)["\']\)',
                                        r'location\.href\s*=\s*["\']([^"\']+)["\']',
                                        r'location\.href\s*=\s*["\']((?:[^"\'\\]|\\.)+)["\']\)',
                                        r'window\.location\s*=\s*["\']([^"\']+)["\']',
                                    ]
                                    for pattern in patterns:
                                        match = re.search(pattern, script_text, re.IGNORECASE)
                                        if match:
                                            redirect_link = match.group(1)
                                            redirect_link = redirect_link.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                                            break
                                    if redirect_link:
                                        break
                            
                            if not redirect_link:
                                location_match = re.search(r'location\.replace\(["\']((?:[^"\'\\]|\\.)+)["\']\)', html_content, re.IGNORECASE)
                                if location_match:
                                    redirect_link = location_match.group(1)
                                    redirect_link = redirect_link.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                        
                        if not redirect_link:
                            redirect_match = re.search(r'href=["\'](https?://[^"\']*(?:receber|recebi|link)\.php[^"\']*)["\']', html_content, re.IGNORECASE)
                            if redirect_match:
                                redirect_link = redirect_match.group(1)
                        
                        # Verifica se já há magnet na página antes de seguir redirect
                        magnet_check = None
                        for a in doc.select('a[href^="magnet:"], a[href*="magnet:"]'):
                            magnet_href = a.get('href', '')
                            if magnet_href.startswith('magnet:'):
                                magnet_check = magnet_href
                                break
                        
                        if not magnet_check:
                            for script in doc.select('script'):
                                script_text = script.string or ''
                                if 'magnet:' in script_text:
                                    magnet_match = re.search(r'magnet:\?[^"\'\s\)]+', script_text)
                                    if magnet_match:
                                        magnet_check = magnet_match.group(0)
                                        break
                        
                        if not magnet_check:
                            magnet_match = re.search(r'magnet:\?[^"\'\s<>]+', html_content)
                            if magnet_match:
                                magnet_check = magnet_match.group(0)
                        
                        if magnet_check:
                            # Tenta Redis primeiro
                            if redis_client:
                                try:
                                    cache_key = protlink_key(protlink_url)
                                    redis_client.setex(cache_key, 7 * 24 * 3600, magnet_check)
                                except Exception:
                                    pass
                            else:
                                # Salva em memória apenas se Redis não disponível
                                if not hasattr(_request_cache, 'protlink_cache'):
                                    _request_cache.protlink_cache = {}
                                _request_cache.protlink_cache[protlink_url] = magnet_check
                            return magnet_check
                        
                        # Verifica se deve seguir redirect
                        if redirect_link:
                            redirect_lower = redirect_link.lower()
                            is_protected_redirect = (
                                'receber.php' in redirect_lower or 
                                'recebi.php' in redirect_lower or 
                                'link.php' in redirect_lower or
                                'get.php' in redirect_lower or
                                '?id=' in redirect_lower or
                                '&id=' in redirect_lower
                            )
                            
                            if not is_protected_redirect and redirect_count < 5:
                                skip_patterns = [
                                    r'/[^/]+-[^/]+-[^/]+/',
                                    r'/[^/?]+\.html?$',
                                ]
                                for pattern in skip_patterns:
                                    if re.search(pattern, redirect_link):
                                        redirect_link = None
                                        break
                            
                            if redirect_link:
                                redirect_link = html.unescape(redirect_link)
                                redirect_url = urljoin(current_url, redirect_link)
                                current_url = redirect_url
                                redirect_count += 1
                                continue
                    
                    except Exception as e:
                        logger.error(f"Erro ao processar resposta HTML: {e}")
                        break
                
                # Extrai magnet da página final usando múltiplas estratégias
                if response.status_code == 200:
                    magnet_link = None
                    
                    # Estratégia 1: Links <a> com href magnet
                    for a in doc.select('a[href^="magnet:"], a[href*="magnet:"]'):
                        magnet_href = a.get('href', '')
                        if magnet_href.startswith('magnet:'):
                            magnet_link = magnet_href
                            break
                    
                    # Estratégia 2: Meta refresh com magnet
                    if not magnet_link:
                        for meta in doc.select('meta[http-equiv="refresh"]'):
                            content = meta.get('content', '')
                            if 'magnet:' in content:
                                match = re.search(r'magnet:\?[^;\s"\']+', content)
                                if match:
                                    magnet_link = match.group(0)
                                    extended = re.search(r'magnet:\?[^"\']+', content[match.start():])
                                    if extended and len(extended.group(0)) > len(magnet_link):
                                        magnet_link = extended.group(0)
                                    break
                    
                    # Estratégia 3: JavaScript patterns
                    if not magnet_link:
                        js_patterns = [
                            r'window\.location\s*=\s*["\'](magnet:[^"\']+)["\']',
                            r'location\.href\s*=\s*["\'](magnet:[^"\']+)["\']',
                            r'window\.open\(["\'](magnet:[^"\']+)["\']',
                            r'redirect.*?["\'](magnet:[^"\']+)["\']',
                            r'location\s*=\s*["\'](magnet:[^"\']+)["\']',
                            r'["\'](magnet:\?[^"\']+)["\']',
                            r'decodeURIComponent\(["\']([^"\']+)["\']\)',
                        ]
                        for script in doc.select('script'):
                            script_text = script.string or ''
                            for pattern in js_patterns:
                                match = re.search(pattern, script_text, re.IGNORECASE | re.DOTALL)
                                if match:
                                    potential_magnet = match.group(1)
                                    if not potential_magnet.startswith('magnet:'):
                                        try:
                                            potential_magnet = unquote(potential_magnet)
                                        except:
                                            pass
                                    if potential_magnet.startswith('magnet:'):
                                        magnet_link = potential_magnet
                                        break
                            if magnet_link:
                                break
                    
                    # Estratégia 4: JavaScript raw patterns no HTML
                    if not magnet_link:
                        js_raw_patterns = [
                            r'window\.location\s*=\s*["\'](magnet:\?[^"\']+)["\']',
                            r'location\.href\s*=\s*["\'](magnet:\?[^"\']+)["\']',
                            r'["\'](magnet:\?[^"\']+)["\']',
                        ]
                        for pattern in js_raw_patterns:
                            matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
                            if matches:
                                magnet_link = max(matches, key=len)
                                break
                    
                    # Estratégia 5: Busca direta em scripts (primeiros 3)
                    if not magnet_link:
                        for script in doc.select('script')[:3]:
                            script_text = script.string or ''
                            if 'magnet:' in script_text:
                                matches = re.findall(r'magnet:\?[^"\'\s\)]+', script_text)
                                if matches:
                                    magnet_link = max(matches, key=len)
                                    for match in matches:
                                        if len(match) > len(magnet_link):
                                            magnet_link = match
                                    break
                    
                    # Estratégia 6: Busca em todos os scripts
                    if not magnet_link:
                        for script in doc.select('script'):
                            script_text = script.string or ''
                            if 'magnet:' in script_text:
                                patterns = [
                                    r'magnet:\?[^"\'\s\)]+',
                                    r'["\'](magnet:\?[^"\']+)["\']',
                                    r'=?\s*["\'](magnet:\?[^"\']+)["\']',
                                ]
                                for pattern in patterns:
                                    matches = re.findall(pattern, script_text)
                                    if matches:
                                        magnet_link = max(matches, key=len)
                                        break
                                if magnet_link:
                                    break
                    
                    # Estratégia 7: Atributos data-* (data-u, data-download, etc)
                    if not magnet_link:
                        data_attrs = doc.select('[data-download], [data-link], [data-magnet], [data-url], [data-u]')
                        for elem in data_attrs:
                            for attr in ['data-download', 'data-link', 'data-magnet', 'data-url', 'data-u']:
                                encoded_value = elem.get(attr, '')
                                if encoded_value:
                                    # Se é data-u, usa decodificação especializada (Grupo 3)
                                    if attr == 'data-u':
                                        decoded_magnet = decode_data_u(encoded_value)
                                        if decoded_magnet:
                                            magnet_link = decoded_magnet
                                            break
                                    else:
                                        # Para outros atributos, tenta decodificação padrão Base64
                                        try:
                                            padding = 4 - len(encoded_value) % 4
                                            if padding != 4:
                                                encoded_padded = encoded_value + '=' * padding
                                            else:
                                                encoded_padded = encoded_value
                                            
                                            decoded_bytes = base64.b64decode(encoded_padded)
                                            decoded_str = decoded_bytes.decode('utf-8')
                                            
                                            if decoded_str.startswith('magnet:'):
                                                magnet_link = decoded_str
                                                break
                                        except Exception:
                                            try:
                                                base64url = encoded_value.replace('-', '+').replace('_', '/')
                                                padding = 4 - len(base64url) % 4
                                                if padding != 4:
                                                    base64url = base64url + '=' * padding
                                                decoded_bytes = base64.b64decode(base64url)
                                                decoded_str = decoded_bytes.decode('utf-8')
                                                if decoded_str.startswith('magnet:'):
                                                    magnet_link = decoded_str
                                                    break
                                            except Exception:
                                                pass
                                    
                                    if encoded_value.startswith('magnet:'):
                                        magnet_link = encoded_value
                                        break
                            if magnet_link:
                                break
                    
                    # Estratégia 8: Busca direta por regex no HTML
                    if not magnet_link:
                        magnet_match = re.search(r'magnet:\?[^"\'\s<>]+', html_content)
                        if magnet_match:
                            magnet_link = magnet_match.group(0)
                    
                    if magnet_link:
                        # Tenta Redis primeiro
                        if redis_client:
                            try:
                                cache_key = protlink_key(protlink_url)
                                redis_client.setex(cache_key, 7 * 24 * 3600, magnet_link)
                            except Exception:
                                pass
                        else:
                            # Salva em memória apenas se Redis não disponível
                            if not hasattr(_request_cache, 'protlink_cache'):
                                _request_cache.protlink_cache = {}
                            _request_cache.protlink_cache[protlink_url] = magnet_link
                        return magnet_link
                    else:
                        logger.warning(f"Magnet não encontrado na página final após {redirect_count} redirects.")
                        break
                
                if response.status_code not in (200, 301, 302, 303, 307, 308):
                    logger.warning(f"Status code não esperado: {response.status_code}")
                    break
        
        except Exception as e:
            logger.debug(f"Link resolver error: {type(e).__name__}")
    
    logger.warning(f"Falha ao resolver link protegido após {redirect_count} redirects: {protlink_url[:80]}...")
    return None
