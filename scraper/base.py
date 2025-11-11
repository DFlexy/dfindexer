"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import requests
from cache.redis_client import get_redis_client
from app.config import Config
from tracker import get_tracker_service  # type: ignore[import]
from magnet.parser import MagnetParser
from utils.text_processing import format_bytes

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Classe base para scrapers"""

    SCRAPER_TYPE: str = ''
    DEFAULT_BASE_URL: str = ''
    DISPLAY_NAME: str = ''
    
    def __init__(self, base_url: Optional[str] = None):
        resolved_url = (base_url or self.DEFAULT_BASE_URL or '').strip()
        if resolved_url and not resolved_url.endswith('/'):
            resolved_url = f"{resolved_url}/"
        if not resolved_url:
            raise ValueError(
                f"{self.__class__.__name__} requer DEFAULT_BASE_URL definido ou um base_url explícito"
            )
        self.base_url = resolved_url
        self.redis = get_redis_client()  # Pode ser None se Redis não disponível
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        self.tracker_service = get_tracker_service()
    
    def get_document(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        """Obtém documento HTML do cache ou faz requisição"""
        # Tenta obter do cache de longa duração (se Redis disponível)
        if self.redis:
            try:
                cache_key = f"doc:{url}"
                cached = self.redis.get(cache_key)
                if cached:
                    logger.debug(f"Cache hit (long): {url}")
                    return BeautifulSoup(cached, 'html.parser')
            except:
                pass
        
        # Tenta obter do cache de curta duração (se Redis disponível)
        if self.redis:
            try:
                short_cache_key = f"short:{url}"
                cached = self.redis.get(short_cache_key)
                if cached:
                    logger.debug(f"Cache hit (short): {url}")
                    return BeautifulSoup(cached, 'html.parser')
            except:
                pass
        
        # Faz requisição HTTP
        headers = {'Referer': referer if referer else self.base_url}
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            html_content = response.content
            
            # Salva no cache (se Redis disponível)
            if self.redis:
                try:
                    short_cache_key = f"short:{url}"
                    self.redis.setex(
                        short_cache_key,
                        Config.SHORT_LIVED_CACHE_EXPIRATION,
                        html_content
                    )
                    
                    cache_key = f"doc:{url}"
                    self.redis.setex(
                        cache_key,
                        Config.LONG_LIVED_CACHE_EXPIRATION,
                        html_content
                    )
                except:
                    pass  # Ignora erros de cache
            
            logger.debug(f"Documento obtido: {url}")
            return BeautifulSoup(html_content, 'html.parser')
        
        except Exception as e:
            logger.error(f"Erro ao obter documento {url}: {e}")
            return None
    
    @abstractmethod
    def search(self, query: str) -> List[Dict]:
        """Busca torrents por query"""
        pass
    
    @abstractmethod
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        """Obtém torrents de uma página específica"""
        pass

    def enrich_torrents(self, torrents: List[Dict]) -> List[Dict]:
        """Preenche dados de seeds/leechers via trackers (quando possível)."""
        if not torrents:
            return torrents
        self._apply_size_fallback(torrents)
        self._attach_peers(torrents)
        return torrents

    def _apply_size_fallback(self, torrents: List[Dict]) -> None:
        for torrent in torrents:
            if torrent.get('size'):
                continue
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                continue
            xl_value = magnet_data.get('params', {}).get('xl')
            if not xl_value:
                continue
            try:
                formatted_size = format_bytes(int(xl_value))
            except (ValueError, TypeError):
                continue
            if formatted_size:
                torrent['size'] = formatted_size

    def _attach_peers(self, torrents: List[Dict]) -> None:
        if not self.tracker_service:
            return
        infohash_map: Dict[str, List[str]] = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            # Se o resultado já veio com contadores válidos, mantém para não repetir consultas
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            trackers = torrent.get('trackers') or []
            infohash_map.setdefault(info_hash, [])
            infohash_map[info_hash].extend(trackers)
        if not infohash_map:
            return
        peers_map = self.tracker_service.get_peers_bulk(infohash_map)
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash:
                continue
            leech_seed = peers_map.get(info_hash)
            if not leech_seed:
                continue
            leech, seed = leech_seed
            torrent['leech_count'] = leech
            torrent['seed_count'] = seed

