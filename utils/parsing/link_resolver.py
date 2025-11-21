"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import logging
import base64
import html
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)

# TTL para cache de links protegidos resolvidos (24 horas)
PROTECTED_LINK_CACHE_TTL = 24 * 60 * 60  # 86400 segundos


# Verifica se um link é protegido (precisa ser resolvido)
def is_protected_link(href: str) -> bool:
    """
    Verifica se um link é protegido e precisa ser resolvido.
    Retorna True se o link contém padrões de links protegidos.
    """
    if not href:
        return False
    
    protected_patterns = [
        'protlink=',
        'encurtador',
        'encurta',
        'get.php',
        'systemads'
    ]
    
    return any(pattern in href for pattern in protected_patterns)


# Decodifica link de adware (systemads, seuvideo) - extrai o parâmetro id e decodifica
def decode_ad_link(ad_link: str) -> Optional[str]:
    """
    Decodifica link de adware (systemads.org, seuvideo.xyz).
    Extrai o parâmetro 'id' da URL e decodifica para obter o magnet link.
    
    Baseado no código Go original que usa utils.DecodeAdLink.
    O algoritmo parece usar uma codificação customizada que precisa ser decodificada em etapas.
    """
    if not ad_link:
        return None
    
    try:
        # Parse a URL
        parsed_url = urlparse(ad_link)
        query_params = parse_qs(parsed_url.query)
        
        # Extrai o parâmetro 'id'
        id_param = query_params.get('id', [None])[0]
        if not id_param:
            return None
        
        # O código Go usa utils.DecodeAdLink que provavelmente faz uma decodificação customizada
        # Vamos tentar diferentes métodos baseados em padrões comuns
        
        # Método 1: Base64 padrão direto
        try:
            padding = 4 - len(id_param) % 4
            if padding != 4:
                id_padded = id_param + '=' * padding
            else:
                id_padded = id_param
            decoded_bytes = base64.b64decode(id_padded)
            decoded = decoded_bytes.decode('utf-8')
            if decoded.startswith('magnet:'):
                logger.debug("Decodificação base64 padrão funcionou!")
                return decoded
        except Exception:
            pass
        
        # Método 2: Base64 com URL decode primeiro
        try:
            id_decoded = unquote(id_param)
            padding = 4 - len(id_decoded) % 4
            if padding != 4:
                id_padded = id_decoded + '=' * padding
            else:
                id_padded = id_decoded
            decoded_bytes = base64.b64decode(id_padded)
            decoded = decoded_bytes.decode('utf-8')
            if decoded.startswith('magnet:'):
                logger.debug("Decodificação base64 com URL decode funcionou!")
                return decoded
        except Exception:
            pass
        
        # Método 3: Base64URL (com - e _)
        try:
            id_base64url = id_param.replace('-', '+').replace('_', '/')
            padding = 4 - len(id_base64url) % 4
            if padding != 4:
                id_base64url = id_base64url + '=' * padding
            decoded_bytes = base64.b64decode(id_base64url)
            decoded = decoded_bytes.decode('utf-8')
            if decoded.startswith('magnet:'):
                logger.debug("Decodificação base64url funcionou!")
                return decoded
        except Exception:
            pass
        
        # Método 4: Tenta decodificar como se fosse uma string codificada em múltiplas camadas
        # Alguns sistemas codificam múltiplas vezes
        try:
            current = id_param
            for _ in range(3):  # Tenta até 3 camadas
                padding = 4 - len(current) % 4
                if padding != 4:
                    current_padded = current + '=' * padding
                else:
                    current_padded = current
                decoded_bytes = base64.b64decode(current_padded)
                decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
                if decoded_str.startswith('magnet:'):
                    logger.debug(f"Decodificação em múltiplas camadas funcionou!")
                    return decoded_str
                # Se não é magnet, pode ser que precise decodificar mais uma vez
                current = decoded_str
        except Exception:
            pass
        
        # Nota: A decodificação direta do parâmetro 'id' geralmente falha porque o systemads
        # não usa decodificação direta - ele usa redirects HTTP até a página final onde
        # o magnet está codificado em base64 no atributo data-download do body.
        # Isso é esperado e o código continuará com o método de redirects.
        return None
        
    except Exception as e:
        return None


# Resolve link protegido (protlink) seguindo todos os redirects e extraindo o magnet real - retorna URL do magnet link ou None se não conseguir resolver
def resolve_protected_link(protlink_url: str, session: requests.Session, base_url: str = '', redis=None) -> Optional[str]:
    # Tenta obter do cache primeiro
    if redis:
        try:
            cache_key = f"protlink:{protlink_url}"
            cached = redis.get(cache_key)
            if cached:
                magnet_link = cached.decode('utf-8')
                logger.debug(f"Link protegido resolvido do cache: {protlink_url[:50]}...")
                return magnet_link
        except Exception:
            pass  # Ignora erros de cache
    
    # Para links systemads/seuvideo, tenta decodificar diretamente primeiro (mais rápido)
    if 'systemads.org' in protlink_url or 'seuvideo.xyz' in protlink_url or 'get.php' in protlink_url:
        decoded_magnet = decode_ad_link(protlink_url)
        if decoded_magnet:
            logger.debug(f"Link systemads/seuvideo decodificado com sucesso!")
            # Salva no cache
            if redis:
                try:
                    cache_key = f"protlink:{protlink_url}"
                    redis.setex(cache_key, PROTECTED_LINK_CACHE_TTL, decoded_magnet)
                except Exception:
                    pass
            return decoded_magnet
    # Se decodificação falhou ou não é systemads, segue com método de redirect
    try:
        # Segue todos os redirects manualmente até chegar na página final
        current_url = protlink_url
        max_redirects = 20  # Aumentado para 20 para systemads/autotop que podem ter muitos redirects
        redirect_count = 0
        timeout = 5  # Reduzido para 5s para melhor performance
        
        while redirect_count < max_redirects:
            response = session.get(
                current_url,
                allow_redirects=False,
                timeout=timeout,
                headers={
                    'Referer': base_url if redirect_count == 0 else current_url,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate',  # Removido 'br' que pode causar problemas
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
            )
            
            # Se recebeu um redirect, segue para o próximo
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location', '')
                
                if location.startswith('magnet:'):
                    # Se encontrou magnet diretamente no redirect, salva no cache
                    if redis:
                        try:
                            cache_key = f"protlink:{protlink_url}"
                            redis.setex(cache_key, PROTECTED_LINK_CACHE_TTL, location)
                        except Exception:
                            pass  # Ignora erros de cache
                    return location
                
                # Resolve URL relativa
                if location:
                    current_url = urljoin(current_url, location)
                    redirect_count += 1
                    continue
                else:
                    break
            
            # Se chegou na página final (200), verifica se há mais redirects no HTML
            if response.status_code == 200:
                # Processa o conteúdo da resposta
                try:
                    html_content = response.text
                    # Verifica se o conteúdo parece estar comprimido (caracteres binários)
                    if html_content and (html_content.startswith('\x1f\x8b') or '\x00' in html_content[:100] or not html_content.strip()):
                        # Parece estar comprimido ou inválido, tenta descomprimir manualmente
                        import gzip
                        try:
                            html_content = gzip.decompress(response.content).decode('utf-8')
                        except Exception:
                            # Tenta usar o conteúdo bruto com decode errors='ignore'
                            html_content = response.content.decode('utf-8', errors='ignore')
                    
                    doc = BeautifulSoup(html_content, 'html.parser')
                    
                    # Verifica se há um link de redirect no HTML (como redirectBtn)
                    # Isso acontece quando a página usa JavaScript para fazer redirect
                    redirect_link = None
                    
                    # Método 1: Busca por links <a> com ID que contenha "redirect" ou href que contenha "receber.php" ou "redirecionando"
                    for a in doc.select('a[id*="redirect"], a[id*="Redirect"], a[href*="receber.php"], a[href*="redirecionando"]'):
                        href = a.get('href', '')
                        if href and ('receber.php' in href or 'redirecionando' in href.lower() or 'recebi.php' in href):
                            redirect_link = href
                            break
                    
                    # Método 2: Busca em meta refresh
                    if not redirect_link:
                        for meta in doc.select('meta[http-equiv="refresh"], meta[http-equiv="Refresh"]'):
                            content = meta.get('content', '')
                            # Extrai URL do meta refresh: content="0;URL=http://..."
                            url_match = re.search(r'url\s*=\s*([^;]+)', content, re.IGNORECASE)
                            if url_match:
                                redirect_link = url_match.group(1).strip()
                                break
                    
                    # Método 3: Busca em JavaScript location.replace ou location.href
                    if not redirect_link:
                        for script in doc.select('script'):
                            script_text = script.string or ''
                            if script_text:
                                # Busca por location.replace("url") ou location.href = "url"
                                # Aceita URLs com escapes (\/) e sem escapes
                                patterns = [
                                    r'location\.replace\(["\']([^"\']+)["\']\)',
                                    r'location\.replace\(["\']((?:[^"\'\\]|\\.)+)["\']\)',  # Aceita escapes
                                    r'location\.href\s*=\s*["\']([^"\']+)["\']',
                                    r'location\.href\s*=\s*["\']((?:[^"\'\\]|\\.)+)["\']',  # Aceita escapes
                                    r'window\.location\s*=\s*["\']([^"\']+)["\']',
                                ]
                                for pattern in patterns:
                                    match = re.search(pattern, script_text, re.IGNORECASE)
                                    if match:
                                        redirect_link = match.group(1)
                                        # Remove escapes de barra e outros escapes comuns
                                        redirect_link = redirect_link.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                                        break
                                if redirect_link:
                                    break
                        
                        # Se ainda não encontrou, busca no HTML bruto por location.replace
                        if not redirect_link:
                            location_match = re.search(r'location\.replace\(["\']((?:[^"\'\\]|\\.)+)["\']\)', html_content, re.IGNORECASE)
                            if location_match:
                                redirect_link = location_match.group(1)
                                redirect_link = redirect_link.replace('\\/', '/').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                    
                    # Método 4: Busca no HTML bruto por padrões comuns
                    if not redirect_link:
                        # Busca por padrões como href="https://redirecionandovoce.info/receber.php?id=..."
                        redirect_match = re.search(r'href=["\'](https?://[^"\']*(?:receber|recebi|link)\.php[^"\']*)["\']', html_content, re.IGNORECASE)
                        if redirect_match:
                            redirect_link = redirect_match.group(1)
                    
                    # ANTES de seguir redirect, verifica se já há um magnet link na página atual
                    # Às vezes o magnet está visível antes do redirect JavaScript
                    magnet_check = None
                    # Busca em links <a>
                    for a in doc.select('a[href^="magnet:"], a[href*="magnet:"]'):
                        magnet_href = a.get('href', '')
                        if magnet_href.startswith('magnet:'):
                            magnet_check = magnet_href
                            break
                    
                    # Busca em scripts JavaScript
                    if not magnet_check:
                        for script in doc.select('script'):
                            script_text = script.string or ''
                            if 'magnet:' in script_text:
                                magnet_match = re.search(r'magnet:\?[^"\'\s\)]+', script_text)
                                if magnet_match:
                                    magnet_check = magnet_match.group(0)
                                    break
                    
                    # Busca direto no HTML bruto
                    if not magnet_check:
                        magnet_match = re.search(r'magnet:\?[^"\'\s<>]+', html_content)
                        if magnet_match:
                            magnet_check = magnet_match.group(0)
                    
                    # Se encontrou magnet, retorna imediatamente
                    if magnet_check:
                        if redis:
                            try:
                                cache_key = f"protlink:{protlink_url}"
                                redis.setex(cache_key, PROTECTED_LINK_CACHE_TTL, magnet_check)
                            except Exception:
                                pass
                        return magnet_check
                    
                    # Se encontrou um link de redirect, verifica se não é uma página de conteúdo normal
                    if redirect_link:
                        # Não segue redirects para páginas que parecem ser conteúdo/artigos normais
                        # (não são links protegidos com parâmetros id)
                        redirect_lower = redirect_link.lower()
                        skip_patterns = [
                            r'/[^/]+-[^/]+-[^/]+/',  # URLs com múltiplos hífens (artigos)
                            r'/[^/?]+\.html?$',  # URLs terminando em .html ou .htm
                            r'/[^/?]+/$',  # URLs terminando em / sem parâmetros
                        ]
                        
                        # Verifica se é um link protegido (tem parâmetros id ou é receber/recebi/link.php)
                        is_protected_redirect = (
                            'receber.php' in redirect_lower or 
                            'recebi.php' in redirect_lower or 
                            'link.php' in redirect_lower or
                            'get.php' in redirect_lower or
                            '?id=' in redirect_lower or
                            '&id=' in redirect_lower
                        )
                        
                        # Se não é um link protegido, verifica se deve seguir mesmo assim
                        # Às vezes o magnet está após alguns redirects para páginas de conteúdo
                        if not is_protected_redirect:
                            # Só pula se realmente parecer ser conteúdo E não tivermos seguido muitos redirects ainda
                            # Se já seguimos vários redirects protegidos, pode valer a pena seguir mais um
                            skip_patterns_filtered = [
                                r'/[^/]+-[^/]+-[^/]+/',  # URLs com múltiplos hífens (artigos)
                                r'/[^/?]+\.html?$',  # URLs terminando em .html ou .htm
                            ]
                            
                            # Se já seguimos muitos redirects protegidos (mais de 5), segue mesmo páginas de conteúdo
                            # porque o magnet pode estar logo após
                            should_skip = redirect_count < 5  # Só pula se ainda estamos no início
                            
                            if should_skip:
                                for pattern in skip_patterns_filtered:
                                    if re.search(pattern, redirect_link):
                                        redirect_link = None
                                        break
                        
                        if redirect_link:
                            # Resolve URL relativa e decodifica entidades HTML
                            redirect_link = html.unescape(redirect_link)
                            redirect_url = urljoin(current_url, redirect_link)
                            current_url = redirect_url
                            redirect_count += 1
                            continue  # Volta para o loop para seguir o redirect
                    
                except Exception as e:
                    logger.error(f"Erro ao processar resposta HTML: {e}")
                    break
                
                # Se não há mais redirects, extrai o magnet
                magnet_link = None
                
                # Método 1: Busca por links <a> com href magnet (preserva trackers completos)
                for a in doc.select('a[href^="magnet:"], a[href*="magnet:"]'):
                    magnet_href = a.get('href', '')
                    if magnet_href.startswith('magnet:'):
                        # Usa o href completo do elemento para preservar todos os parâmetros (incluindo trackers)
                        magnet_link = magnet_href
                        break
                
                # Método 2: Busca em meta refresh (preserva trackers completos)
                if not magnet_link:
                    for meta in doc.select('meta[http-equiv="refresh"]'):
                        content = meta.get('content', '')
                        if 'magnet:' in content:
                            # Busca magnet completo incluindo todos os parâmetros até encontrar espaço, aspas ou ponto e vírgula
                            # Permite caracteres especiais que podem aparecer em trackers (como &, =, /, :, etc)
                            match = re.search(r'magnet:\?[^;\s"\']+', content)
                            if match:
                                magnet_link = match.group(0)
                                # Tenta estender até encontrar o final real do magnet (pode ter mais parâmetros após ;)
                                extended = re.search(r'magnet:\?[^"\']+', content[match.start():])
                                if extended and len(extended.group(0)) > len(magnet_link):
                                    magnet_link = extended.group(0)
                                break
                
                # Método 2.5: Busca em window.location ou JavaScript de redirect
                if not magnet_link:
                    # Procura por padrões JavaScript comuns que fazem redirect para magnet
                    js_patterns = [
                        r'window\.location\s*=\s*["\'](magnet:[^"\']+)["\']',
                        r'location\.href\s*=\s*["\'](magnet:[^"\']+)["\']',
                        r'window\.open\(["\'](magnet:[^"\']+)["\']',
                        r'redirect.*?["\'](magnet:[^"\']+)["\']',
                        r'location\s*=\s*["\'](magnet:[^"\']+)["\']',  # location sem window
                        r'["\'](magnet:\?[^"\']+)["\']',  # Qualquer magnet entre aspas
                        r'decodeURIComponent\(["\']([^"\']+)["\']\)',  # Pode estar codificado
                    ]
                    for script in doc.select('script'):
                        script_text = script.string or ''
                        for pattern in js_patterns:
                            match = re.search(pattern, script_text, re.IGNORECASE | re.DOTALL)
                            if match:
                                potential_magnet = match.group(1)
                                # Se não começa com magnet:, pode estar codificado
                                if not potential_magnet.startswith('magnet:'):
                                    try:
                                        from urllib.parse import unquote
                                        potential_magnet = unquote(potential_magnet)
                                    except:
                                        pass
                                if potential_magnet.startswith('magnet:'):
                                    magnet_link = potential_magnet
                                    break
                        if magnet_link:
                            break
                    
                    # Se ainda não encontrou, busca no HTML bruto por padrões JavaScript
                    if not magnet_link:
                        js_raw_patterns = [
                            r'window\.location\s*=\s*["\'](magnet:\?[^"\']+)["\']',
                            r'location\.href\s*=\s*["\'](magnet:\?[^"\']+)["\']',
                            r'["\'](magnet:\?[^"\']+)["\']',
                        ]
                        for pattern in js_raw_patterns:
                            matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
                            if matches:
                                # Pega o match mais longo
                                magnet_link = max(matches, key=len)
                                logger.debug("Magnet encontrado em JavaScript no HTML bruto!")
                                break
                
                # Método 3: Busca em scripts JavaScript (limitado aos primeiros 3 scripts para performance)
                # IMPORTANTE: Preserva trackers completos usando regex mais permissivo
                if not magnet_link:
                    for script in doc.select('script')[:3]:  # Limita a 3 scripts para não demorar muito
                        script_text = script.string or ''
                        if 'magnet:' in script_text:
                            # Busca todos os matches possíveis
                            # Permite caracteres especiais que podem aparecer em trackers
                            matches = re.findall(r'magnet:\?[^"\'\s\)]+', script_text)
                            if matches:
                                # Pega o match mais longo (mais completo, com mais trackers)
                                magnet_link = max(matches, key=len)
                                # Tenta encontrar um match ainda mais completo procurando até o final da linha ou próximo caractere especial
                                for match in matches:
                                    if len(match) > len(magnet_link):
                                        magnet_link = match
                                break
                
                # Método 4: Busca em todos os scripts (não apenas os primeiros 3)
                if not magnet_link:
                    for script in doc.select('script'):
                        script_text = script.string or ''
                        if 'magnet:' in script_text:
                            # Busca padrões mais específicos de magnet em JavaScript
                            patterns = [
                                r'magnet:\?[^"\'\s\)]+',  # Padrão original
                                r'["\'](magnet:\?[^"\']+)["\']',  # Entre aspas
                                r'=?\s*["\'](magnet:\?[^"\']+)["\']',  # Com = antes
                            ]
                            for pattern in patterns:
                                matches = re.findall(pattern, script_text)
                                if matches:
                                    # Pega o match mais longo
                                    magnet_link = max(matches, key=len)
                                    logger.debug("Magnet encontrado em script JavaScript!")
                                    break
                            if magnet_link:
                                break
                
                # Método 5: Busca em atributos data-* (como data-download) que podem conter magnet codificado em base64
                if not magnet_link:
                    # Busca por atributos data-download, data-link, data-magnet, etc.
                    data_attrs = doc.select('[data-download], [data-link], [data-magnet], [data-url]')
                    for elem in data_attrs:
                        for attr in ['data-download', 'data-link', 'data-magnet', 'data-url']:
                            encoded_value = elem.get(attr, '')
                            if encoded_value:
                                # Tenta decodificar base64 (pode estar em formato URL-safe)
                                try:
                                    # Tenta base64 padrão primeiro
                                    padding = 4 - len(encoded_value) % 4
                                    if padding != 4:
                                        encoded_padded = encoded_value + '=' * padding
                                    else:
                                        encoded_padded = encoded_value
                                    
                                    decoded_bytes = base64.b64decode(encoded_padded)
                                    decoded_str = decoded_bytes.decode('utf-8')
                                    
                                    # Se decodificou e começa com magnet:, usa
                                    if decoded_str.startswith('magnet:'):
                                        magnet_link = decoded_str
                                        break
                                except Exception:
                                    # Tenta base64url (com - e _)
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
                                
                                # Se não está codificado, verifica se já é um magnet direto
                                if encoded_value.startswith('magnet:'):
                                    magnet_link = encoded_value
                                    break
                        if magnet_link:
                            break
                
                # Método 6: Busca direto no texto HTML (último recurso)
                # IMPORTANTE: Preserva trackers completos usando regex mais permissivo
                if not magnet_link:
                    # Busca magnet completo incluindo todos os parâmetros até encontrar espaço, aspas ou tag HTML
                    # Permite caracteres especiais que podem aparecer em trackers
                    magnet_match = re.search(r'magnet:\?[^"\'\s<>]+', html_content)
                    if magnet_match:
                        magnet_link = magnet_match.group(0)
                
                # Se encontrou, salva no cache e retorna
                if magnet_link:
                    if redis:
                        try:
                            cache_key = f"protlink:{protlink_url}"
                            redis.setex(cache_key, PROTECTED_LINK_CACHE_TTL, magnet_link)
                        except Exception:
                            pass  # Ignora erros de cache
                    return magnet_link
                else:
                    logger.warning(f"Magnet não encontrado na página final após {redirect_count} redirects.")
                
                # Se não encontrou, retorna None
                break
            
            # Se não é redirect nem 200, para
            logger.warning(f"Status code não esperado: {response.status_code}")
            break
        
    except Exception as e:
        logger.error(f"Erro ao resolver link protegido {protlink_url[:80]}...: {e}", exc_info=True)
    
    logger.warning(f"Falha ao resolver link protegido após {redirect_count} redirects: {protlink_url[:80]}...")
    return None

