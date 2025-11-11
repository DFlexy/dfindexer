"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import os


def _parse_duration(duration_str: str) -> int:
    """Converte duração (10m, 12h, 7d) para segundos"""
    duration_str = duration_str.strip().lower()
    
    if duration_str.endswith('s'):
        return int(duration_str[:-1])
    elif duration_str.endswith('m'):
        return int(duration_str[:-1]) * 60
    elif duration_str.endswith('h'):
        return int(duration_str[:-1]) * 3600
    elif duration_str.endswith('d'):
        return int(duration_str[:-1]) * 86400
    else:
        # Assume segundos se não especificado
        return int(duration_str)


def _normalize_url(url: str) -> str:
    """Normaliza URL garantindo que termine com /"""
    if not url:
        return ''
    if not url.endswith('/'):
        return url + '/'
    return url


class Config:
    """Configurações da aplicação via variáveis de ambiente"""
    
    # Servidor
    PORT: int = int(os.getenv('PORT', '7006'))
    METRICS_PORT: int = int(os.getenv('METRICS_PORT', '8081'))
    # Trackers / scrape
    TRACKER_SCRAPE_TIMEOUT: float = float(os.getenv('TRACKER_SCRAPE_TIMEOUT', '0.5'))
    TRACKER_SCRAPE_RETRIES: int = int(os.getenv('TRACKER_SCRAPE_RETRIES', '2'))
    TRACKER_SCRAPE_MAX_TRACKERS: int = int(os.getenv('TRACKER_SCRAPE_MAX_TRACKERS', '0'))
    TRACKER_CACHE_TTL: int = _parse_duration(os.getenv('TRACKER_CACHE_TTL', '24h'))
    
    # Redis
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    
    # Cache
    SHORT_LIVED_CACHE_EXPIRATION: int = _parse_duration(
        os.getenv('SHORT_LIVED_CACHE_EXPIRATION', '10m')
    )
    LONG_LIVED_CACHE_EXPIRATION: int = _parse_duration(
        os.getenv('LONG_LIVED_CACHE_EXPIRATION', '12h')
    )
    
    # Sites configuráveis - suporta SITE1, SITE2, SITE3, etc.
    SITE1: str = _normalize_url(os.getenv('SITE1', 'https://starckfilmes-v3.com/'))
    SITE2: str = _normalize_url(os.getenv('SITE2', ''))
    SITE3: str = _normalize_url(os.getenv('SITE3', ''))
    SITE4: str = _normalize_url(os.getenv('SITE4', ''))
    SITE5: str = _normalize_url(os.getenv('SITE5', ''))
    SITE6: str = _normalize_url(os.getenv('SITE6', ''))
    SITE7: str = _normalize_url(os.getenv('SITE7', ''))
    
    # Tipos de sites - suporta SITE1_TYPE, SITE2_TYPE, etc.
    SITE1_TYPE: str = os.getenv('SITE1_TYPE', 'starck')
    SITE2_TYPE: str = os.getenv('SITE2_TYPE', 'starck')
    SITE3_TYPE: str = os.getenv('SITE3_TYPE', 'starck')
    SITE4_TYPE: str = os.getenv('SITE4_TYPE', 'starck')
    SITE5_TYPE: str = os.getenv('SITE5_TYPE', 'starck')
    SITE6_TYPE: str = os.getenv('SITE6_TYPE', 'starck')
    SITE7_TYPE: str = os.getenv('SITE7_TYPE', 'starck')
    
    # Logging
    # LOG_LEVEL: 0 (debug), 1 (info), 2 (warn), 3 (error) - valores numéricos como no Go
    LOG_LEVEL: int = int(os.getenv('LOG_LEVEL', '1'))  # Padrão: 1 (info)
    LOG_FORMAT: str = os.getenv('LOG_FORMAT', 'console')  # 'json' ou 'console'
    
    @classmethod
    def get_sites_dict(cls) -> dict:
        """Retorna dicionário de sites configurados {nome: url}"""
        sites = {}
        if cls.SITE1:
            sites['site1'] = cls.SITE1
        if cls.SITE2:
            sites['site2'] = cls.SITE2
        if cls.SITE3:
            sites['site3'] = cls.SITE3
        if cls.SITE4:
            sites['site4'] = cls.SITE4
        if cls.SITE5:
            sites['site5'] = cls.SITE5
        if cls.SITE6:
            sites['site6'] = cls.SITE6
        if cls.SITE7:
            sites['site7'] = cls.SITE7
        return sites
    
    @classmethod
    def get_site_by_name(cls, site_name: str) -> tuple:
        """Retorna (URL, TYPE) do site pelo nome"""
        sites = cls.get_sites_dict()
        site_url = sites.get(site_name, '')
        if not site_url:
            return ('', '')
        
        # Retorna URL e tipo baseado no nome do site
        site_num = site_name.replace('site', '')
        type_attr = f"SITE{site_num}_TYPE"
        site_type = getattr(cls, type_attr, 'starck')
        
        return (site_url, site_type)
    
    @classmethod
    def get_sites(cls) -> list:
        """Retorna lista de URLs de sites configurados"""
        return list(cls.get_sites_dict().values())

