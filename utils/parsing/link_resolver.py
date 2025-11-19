"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import logging
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)

# TTL para cache de links protegidos resolvidos (24 horas)
PROTECTED_LINK_CACHE_TTL = 24 * 60 * 60  # 86400 segundos


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
    
    try:
        # Segue todos os redirects manualmente até chegar na página final
        current_url = protlink_url
        max_redirects = 5
        redirect_count = 0
        timeout = 5  # Timeout reduzido de 10s para 5s
        
        while redirect_count < max_redirects:
            response = session.get(
                current_url,
                allow_redirects=False,
                timeout=timeout,
                headers={
                    'Referer': base_url if redirect_count == 0 else current_url,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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
            
            # Se chegou na página final (200), extrai o magnet
            if response.status_code == 200:
                html_content = response.text
                doc = BeautifulSoup(html_content, 'html.parser')
                
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
                
                # Método 4: Busca direto no texto HTML (último recurso)
                # IMPORTANTE: Preserva trackers completos usando regex mais permissivo
                if not magnet_link:
                    # Busca magnet completo incluindo todos os parâmetros até encontrar espaço, aspas ou tag HTML
                    # Permite caracteres especiais que podem aparecer em trackers
                    magnet_match = re.search(r'magnet:\?[^"\'\s<>]+', html_content)
                    if magnet_match:
                        magnet_link = magnet_match.group(0)
                
                # Se encontrou, salva no cache e retorna
                if magnet_link and redis:
                    try:
                        cache_key = f"protlink:{protlink_url}"
                        redis.setex(cache_key, PROTECTED_LINK_CACHE_TTL, magnet_link)
                    except Exception:
                        pass  # Ignora erros de cache
                
                if magnet_link:
                    return magnet_link
                
                # Se não encontrou, retorna None
                break
            
            # Se não é redirect nem 200, para
            break
        
    except Exception as e:
        logger.debug(f"Erro ao resolver link protegido {protlink_url}: {e}")
    
    return None

