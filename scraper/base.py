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
    
    # Limite padrão de itens para testes do Prowlarr
    DEFAULT_MAX_ITEMS_FOR_TEST: int = 3
    
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
        """
        Obtém torrents de uma página específica
        
        Args:
            page: Número da página
            max_items: Limite máximo de itens. Se None, usa DEFAULT_MAX_ITEMS_FOR_TEST (3) como padrão
        """
        pass
    
    def _get_effective_max_items(self, max_items: Optional[int]) -> int:
        """
        Retorna o limite efetivo de itens a processar.
        Se max_items for None, retorna o padrão para testes (3).
        """
        return max_items if max_items is not None else self.DEFAULT_MAX_ITEMS_FOR_TEST

    def enrich_torrents(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False) -> List[Dict]:
        """
        Preenche dados de seeds/leechers via trackers (quando possível).
        
        Args:
            torrents: Lista de torrents para enriquecer
            skip_metadata: Se True, pula busca de metadata (útil para testes do Prowlarr)
            skip_trackers: Se True, pula scraping de trackers (útil para testes do Prowlarr)
        """
        if not torrents:
            return torrents
        
        # Busca metadata uma vez e reutiliza para size e date (evita buscas duplicadas)
        if Config.MAGNET_METADATA_ENABLED and not skip_metadata:
            self._fetch_metadata_batch(torrents)
        
        self._apply_size_fallback(torrents, skip_metadata=skip_metadata)
        self._apply_date_fallback(torrents, skip_metadata=skip_metadata)
        if not skip_trackers:
            self._attach_peers(torrents)
        return torrents
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        """
        Busca metadata para todos os torrents de uma vez e armazena no objeto torrent.
        Isso evita buscas duplicadas quando precisamos de size e date.
        """
        from magnet.metadata import fetch_metadata_from_itorrents
        from magnet.parser import MagnetParser
        
        for torrent in torrents:
            # Pula se já tem metadata ou não tem magnet
            if torrent.get('_metadata_fetched') or not torrent.get('magnet_link'):
                continue
            
            try:
                # Obtém info_hash
                info_hash = torrent.get('info_hash')
                if not info_hash:
                    try:
                        magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                        info_hash = magnet_data.get('info_hash')
                    except Exception:
                        continue
                
                if not info_hash:
                    continue
                
                # Busca metadata e armazena no torrent
                metadata = fetch_metadata_from_itorrents(info_hash)
                if metadata:
                    torrent['_metadata'] = metadata
                    torrent['_metadata_fetched'] = True
            except Exception:
                pass  # Ignora erros, os fallbacks vão tentar depois

    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """
        Aplica fallbacks para obter tamanho do torrent quando não encontrado no HTML.
        Ordem de tentativas (se metadata habilitado):
        1. Busca via metadata API (iTorrents.org) - PADRÃO
        2. Parâmetro 'xl' do magnet link - FALLBACK
        3. Mantém tamanho do HTML (se extraído pelo scraper)
        
        Args:
            torrents: Lista de torrents para processar
            skip_metadata: Se True, pula busca de metadata (útil para testes do Prowlarr)
        """
        # Verifica se metadata está habilitado e não deve ser pulado
        metadata_enabled = Config.MAGNET_METADATA_ENABLED and not skip_metadata
        
        for torrent in torrents:
            if torrent.get('size'):
                continue
            
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            # Parseia magnet uma vez para reutilizar
            magnet_data = None
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                pass
            
            # Tentativa 1: Busca via metadata API (iTorrents.org) - PADRÃO
            if metadata_enabled and not torrent.get('size'):
                # Tenta usar metadata já buscado primeiro
                if torrent.get('_metadata') and 'size' in torrent['_metadata']:
                    try:
                        from utils.text_processing import format_bytes
                        size_bytes = torrent['_metadata']['size']
                        formatted_size = format_bytes(size_bytes)
                        if formatted_size:
                            torrent['size'] = formatted_size
                            logger.debug(f"Tamanho obtido via metadata (cache) para {torrent.get('info_hash', 'unknown')}: {formatted_size}")
                            continue
                    except Exception:
                        pass
                
                # Se não tem metadata em cache, busca agora
                try:
                    from magnet.metadata import get_torrent_size
                    # Obtém info_hash do torrent ou do magnet parseado
                    info_hash = torrent.get('info_hash')
                    if not info_hash and magnet_data:
                        info_hash = magnet_data.get('info_hash')
                    
                    if info_hash:
                        metadata_size = get_torrent_size(magnet_link, info_hash)
                        if metadata_size:
                            torrent['size'] = metadata_size
                            logger.debug(f"Tamanho obtido via metadata para {info_hash}: {metadata_size}")
                            continue  # Tamanho encontrado, passa para próximo
                except Exception as e:
                    logger.debug(f"Erro ao buscar tamanho via metadata: {e}")
            
            # Tentativa 2: Parâmetro 'xl' do magnet link - FALLBACK
            if not torrent.get('size') and magnet_data:
                try:
                    xl_value = magnet_data.get('params', {}).get('xl')
                    if xl_value:
                        try:
                            formatted_size = format_bytes(int(xl_value))
                            if formatted_size:
                                torrent['size'] = formatted_size
                                logger.debug(f"Tamanho obtido via parâmetro 'xl' do magnet")
                                continue  # Tamanho encontrado, passa para próximo
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    pass
            
            # Se ainda não tem tamanho, mantém o que veio do HTML (se houver)
            # O scraper já tentou extrair do HTML antes de chamar enrich_torrents

    def _apply_date_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """
        Aplica fallback para obter data de criação do torrent via metadata API.
        Usa creation_date do torrent como date, mantendo date do HTML como fallback.
        
        Ordem de tentativas (se metadata habilitado):
        1. Busca creation_date via metadata API (iTorrents.org) - PADRÃO
        2. Mantém date do HTML (se extraído pelo scraper) - FALLBACK
        
        Args:
            torrents: Lista de torrents para processar
            skip_metadata: Se True, pula busca de metadata (útil para testes do Prowlarr)
        """
        from datetime import datetime
        
        # Verifica se metadata está habilitado e não deve ser pulado
        metadata_enabled = Config.MAGNET_METADATA_ENABLED and not skip_metadata
        
        if not metadata_enabled:
            return  # Se metadata desabilitado, mantém date do HTML
        
        for torrent in torrents:
            # Se já tem date do HTML, só substitui se conseguir via metadata
            has_html_date = bool(torrent.get('date'))
            
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            # Obtém info_hash
            info_hash = torrent.get('info_hash')
            if not info_hash:
                try:
                    magnet_data = MagnetParser.parse(magnet_link)
                    info_hash = magnet_data.get('info_hash')
                except Exception:
                    continue
            
            if not info_hash:
                continue
            
            # Busca metadata completo (reutiliza metadata já buscado se disponível)
            try:
                # Tenta usar metadata já buscado primeiro
                metadata = torrent.get('_metadata')
                if not metadata:
                    from magnet.metadata import fetch_metadata_from_itorrents
                    metadata = fetch_metadata_from_itorrents(info_hash)
                
                if metadata and metadata.get('creation_date'):
                    # Converte timestamp para datetime
                    creation_timestamp = metadata['creation_date']
                    try:
                        creation_date = datetime.fromtimestamp(creation_timestamp)
                        # Atualiza date com creation_date do torrent
                        torrent['date'] = creation_date.isoformat()
                        logger.debug(f"Date atualizado via metadata (creation_date) para {info_hash}")
                    except (ValueError, OSError) as e:
                        logger.debug(f"Erro ao converter timestamp {creation_timestamp} para datetime: {e}")
                        # Se falhar, mantém date do HTML (se houver)
            except Exception as e:
                logger.debug(f"Erro ao buscar date via metadata: {e}")
                # Se falhar, mantém date do HTML (se houver)

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

