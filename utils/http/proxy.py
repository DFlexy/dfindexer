# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse
from app.config import Config

def get_proxy_url() -> Optional[str]:
    """Monta a URL do proxy a partir das variáveis de ambiente"""
    if not Config.PROXY_HOST or not Config.PROXY_PORT:
        return None
    
    host = str(Config.PROXY_HOST).strip()
    port = str(Config.PROXY_PORT).strip()
    
    if not host or not port:
        return None
    
    try:
        port_int = int(port)
        if port_int <= 0 or port_int > 65535:
            return None
    except (ValueError, TypeError):
        return None
    
    proxy_type = Config.PROXY_TYPE.lower().strip()
    valid_types = ['http', 'https', 'socks5', 'socks5h']
    if proxy_type not in valid_types:
        proxy_type = 'http'
    
    if Config.PROXY_USER and Config.PROXY_PASS:
        user = str(Config.PROXY_USER).strip()
        password = str(Config.PROXY_PASS).strip()
        if user and password:
            proxy_url = f"{proxy_type}://{user}:{password}@{host}:{port}"
        else:
            proxy_url = f"{proxy_type}://{host}:{port}"
    else:
        proxy_url = f"{proxy_type}://{host}:{port}"
    
    return proxy_url

def get_proxy_dict() -> Optional[dict]:
    proxy_url = get_proxy_url()
    if not proxy_url:
        return None
    
    return {
        'http': proxy_url,
        'https': proxy_url
    }

def _aiohttp_proxy_url_and_kwargs(proxy_url: str) -> tuple[str, dict]:
    if proxy_url.startswith('socks5h://'):
        return 'socks5://' + proxy_url[len('socks5h://'):], {'rdns': True}
    return proxy_url, {}

def get_aiohttp_proxy_connector():
    proxy_url = get_proxy_url()
    if not proxy_url:
        return None

    aiohttp_url, connector_kwargs = _aiohttp_proxy_url_and_kwargs(proxy_url)

    try:
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(aiohttp_url, **connector_kwargs)
        return connector
    except ImportError:
        try:
            from aiohttp import ProxyConnector as NativeProxyConnector
            connector = NativeProxyConnector.from_url(proxy_url)
            return connector
        except Exception:
            return None
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Erro ao criar ProxyConnector: {e}")
        return None

def get_aiohttp_proxy_url() -> Optional[str]:
    return get_proxy_url()

def is_proxy_local() -> bool:
    """Verifica se o proxy está na mesma rede local que o FlareSolverr"""
    if not Config.PROXY_HOST:
        return False
    
    flaresolverr_host = None
    if Config.FLARESOLVERR_ADDRESS:
        try:
            parsed = urlparse(Config.FLARESOLVERR_ADDRESS)
            flaresolverr_host = parsed.hostname or parsed.netloc.split(':')[0] if ':' in parsed.netloc else parsed.netloc
        except Exception:
            pass
    
    proxy_host = str(Config.PROXY_HOST).strip()
    
    if not flaresolverr_host:
        return False
    
    if proxy_host.lower() == flaresolverr_host.lower():
        return True
    
    try:
        proxy_ip = socket.gethostbyname(proxy_host)
        
        flaresolverr_ip = socket.gethostbyname(flaresolverr_host)
        
        if proxy_ip == flaresolverr_ip:
            return True
        
        try:
            proxy_ip_obj = ipaddress.ip_address(proxy_ip)
            flaresolverr_ip_obj = ipaddress.ip_address(flaresolverr_ip)
            
            is_proxy_private = proxy_ip_obj.is_private
            is_flaresolverr_private = flaresolverr_ip_obj.is_private
            
            if is_proxy_private and is_flaresolverr_private:
                proxy_network = '.'.join(proxy_ip.split('.')[:3])
                flaresolverr_network = '.'.join(flaresolverr_ip.split('.')[:3])
                if proxy_network == flaresolverr_network:
                    return True
        except (ValueError, AttributeError):
            pass
        
    except (socket.gaierror, socket.herror, OSError):
        pass
    
    return False

