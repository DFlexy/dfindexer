"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from typing import Optional
from app.config import Config


def get_proxy_url() -> Optional[str]:
    """
    Monta a URL do proxy a partir das variáveis de ambiente.
    
    Returns:
        URL do proxy no formato [protocol]://[user:pass@]host:port ou None se não configurado
        Protocolos suportados: http, https, socks5, socks5h
    """
    # Valida se host e porta estão configurados
    if not Config.PROXY_HOST or not Config.PROXY_PORT:
        return None
    
    # Remove espaços e valida se não está vazio
    host = str(Config.PROXY_HOST).strip()
    port = str(Config.PROXY_PORT).strip()
    
    if not host or not port:
        return None
    
    # Valida se a porta é um número válido
    try:
        port_int = int(port)
        if port_int <= 0 or port_int > 65535:
            return None
    except (ValueError, TypeError):
        return None
    
    # Valida e normaliza o tipo de proxy
    proxy_type = Config.PROXY_TYPE.lower().strip()
    valid_types = ['http', 'https', 'socks5', 'socks5h']
    if proxy_type not in valid_types:
        # Se tipo inválido, usa http como padrão
        proxy_type = 'http'
    
    # Monta URL base
    if Config.PROXY_USER and Config.PROXY_PASS:
        # Remove espaços das credenciais
        user = str(Config.PROXY_USER).strip()
        password = str(Config.PROXY_PASS).strip()
        if user and password:
            # Com autenticação
            proxy_url = f"{proxy_type}://{user}:{password}@{host}:{port}"
        else:
            # Sem autenticação (credenciais vazias)
            proxy_url = f"{proxy_type}://{host}:{port}"
    else:
        # Sem autenticação
        proxy_url = f"{proxy_type}://{host}:{port}"
    
    return proxy_url


def get_proxy_dict() -> Optional[dict]:
    """
    Retorna dicionário de proxy para uso com requests.
    
    Returns:
        Dicionário com 'http' e 'https' ou None se não configurado
    """
    proxy_url = get_proxy_url()
    if not proxy_url:
        return None
    
    return {
        'http': proxy_url,
        'https': proxy_url
    }


def get_aiohttp_proxy_connector():
    """
    Retorna connector de proxy para uso com aiohttp.
    
    Returns:
        ProxyConnector ou None se não configurado
    """
    proxy_url = get_proxy_url()
    if not proxy_url:
        return None
    
    try:
        from aiohttp import ProxyConnector
        # ProxyConnector.from_url() é a forma correta de criar um connector com proxy
        # O ProxyConnector gerencia automaticamente as conexões através do proxy
        connector = ProxyConnector.from_url(proxy_url)
        return connector
    except ImportError:
        return None
    except Exception as e:
        # Se houver erro ao criar o connector, retorna None
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Erro ao criar ProxyConnector: {e}")
        return None


def get_aiohttp_proxy_url() -> Optional[str]:
    """
    Retorna URL do proxy para uso direto com aiohttp.ClientSession(proxy=...).
    
    Returns:
        URL do proxy ou None se não configurado
    """
    return get_proxy_url()

