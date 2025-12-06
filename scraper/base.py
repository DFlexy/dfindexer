"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import threading
import time
import html
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable, Tuple
from bs4 import BeautifulSoup
import requests
from cache.redis_client import get_redis_client
from cache.redis_keys import html_long_key, html_short_key
from app.config import Config
from tracker import get_tracker_service  # type: ignore[import]
from magnet.parser import MagnetParser
from utils.text.text_processing import format_bytes
from utils.http.flaresolverr import FlareSolverrClient

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()


# Classe base para scrapers
class BaseScraper(ABC):
    SCRAPER_TYPE: str = ''
    DEFAULT_BASE_URL: str = ''
    DISPLAY_NAME: str = ''
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
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
        self._skip_metadata = False
        self._is_test = False
        
        # Estatísticas de cache para debug
        self._cache_stats = {
            'html': {'hits': 0, 'misses': 0},
            'metadata': {'hits': 0, 'misses': 0},
            'trackers': {'hits': 0, 'misses': 0}
        }
        
        # Inicializa FlareSolverr se habilitado e configurado
        self.use_flaresolverr = use_flaresolverr and Config.FLARESOLVERR_ADDRESS is not None
        self.flaresolverr_client: Optional[FlareSolverrClient] = None
        if self.use_flaresolverr:
            try:
                self.flaresolverr_client = FlareSolverrClient(Config.FLARESOLVERR_ADDRESS)
            except Exception as e:
                logger.warning(f"Falha ao inicializar FlareSolverr: {e}. Continuando sem FlareSolverr.")
                self.use_flaresolverr = False
    
    def get_document(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        if self.redis and not self._is_test:
            try:
                cache_key = html_long_key(url)
                cached = self.redis.get(cache_key)
                if cached:
                    self._cache_stats['html']['hits'] += 1
                    return BeautifulSoup(cached, 'html.parser')
            except:
                pass
        
        if self.redis and not self._is_test:
            try:
                short_cache_key = html_short_key(url)
                cached = self.redis.get(short_cache_key)
                if cached:
                    self._cache_stats['html']['hits'] += 1
                    return BeautifulSoup(cached, 'html.parser')
            except:
                pass
        
        # Cache miss - será buscado do site
        self._cache_stats['html']['misses'] += 1
        
        html_content = None
        use_flaresolverr_for_this_url = (
            self.use_flaresolverr and 
            self.flaresolverr_client and 
            "%3A" not in url and 
            "%3a" not in url.lower()
        )
        
        if use_flaresolverr_for_this_url:
            try:
                session_id = self.flaresolverr_client.get_or_create_session(
                    self.base_url,
                    skip_redis=self._is_test
                )
                if session_id:
                    html_content = self.flaresolverr_client.solve(
                        url,
                        session_id,
                        referer if referer else self.base_url,
                        self.base_url,
                        skip_redis=self._is_test
                    )
                    if html_content:
                        if self.redis and not self._is_test:
                            try:
                                short_cache_key = html_short_key(url)
                                self.redis.setex(
                                    short_cache_key,
                                    Config.HTML_CACHE_TTL_SHORT,
                                    html_content
                                )
                                
                                cache_key = html_long_key(url)
                                self.redis.setex(
                                    cache_key,
                                    Config.HTML_CACHE_TTL_LONG,
                                    html_content
                                )
                            except:
                                pass
                        
                        return BeautifulSoup(html_content, 'html.parser')
                    else:
                        failure_key = f"flaresolverr:failure:{url}"
                        should_retry = True
                        
                        # Tenta Redis primeiro
                        if self.redis and not self._is_test:
                            try:
                                if self.redis.exists(failure_key):
                                    logger.debug(f"URL {url} já falhou recentemente com FlareSolverr. Pulando retry.")
                                    should_retry = False
                                else:
                                    self.redis.setex(failure_key, 300, "1")
                            except Exception:
                                pass
                        # Usa memória apenas se Redis não disponível
                        elif not self.redis and not self._is_test:
                            if not hasattr(_request_cache, 'flaresolverr_failures'):
                                _request_cache.flaresolverr_failures = {}
                            
                            expire_at = _request_cache.flaresolverr_failures.get(failure_key, 0)
                            if time.time() < expire_at:
                                logger.debug(f"URL {url} já falhou recentemente com FlareSolverr (memória). Pulando retry.")
                                should_retry = False
                            else:
                                _request_cache.flaresolverr_failures[failure_key] = time.time() + 300  # 5 minutos
                        
                        if "%3A" in url or "%3a" in url.lower():
                            logger.debug(f"URL contém dois pontos codificados (%3A). FlareSolverr pode ter problemas. Pulando retry.")
                            should_retry = False
                        
                        if should_retry:
                            logger.debug(f"FlareSolverr retornou None para {url}. Tentando criar nova sessão.")
                            new_session_id = self.flaresolverr_client.get_or_create_session(
                                self.base_url,
                                skip_redis=self._is_test
                            )
                            if new_session_id and new_session_id != session_id:
                                html_content = self.flaresolverr_client.solve(
                                    url,
                                    new_session_id,
                                    referer if referer else self.base_url,
                                    self.base_url,
                                    skip_redis=self._is_test
                                )
                                if html_content:
                                    if self.redis and not self._is_test:
                                        try:
                                            self.redis.delete(failure_key)
                                            short_cache_key = html_short_key(url)
                                            self.redis.setex(
                                                short_cache_key,
                                                Config.HTML_CACHE_TTL_SHORT,
                                                html_content
                                            )
                                            
                                            cache_key = html_long_key(url)
                                            self.redis.setex(
                                                cache_key,
                                                Config.HTML_CACHE_TTL_LONG,
                                                html_content
                                            )
                                        except:
                                            pass
                                    
                                    return BeautifulSoup(html_content, 'html.parser')
                                else:
                                    # Tenta Redis primeiro
                                    if self.redis and not self._is_test:
                                        try:
                                            self.redis.setex(failure_key, 300, "1")  # 5 minutos
                                        except:
                                            pass
                                    # Salva em memória apenas se Redis não disponível
                                    elif not self.redis and not self._is_test:
                                        if not hasattr(_request_cache, 'flaresolverr_failures'):
                                            _request_cache.flaresolverr_failures = {}
                                        _request_cache.flaresolverr_failures[failure_key] = time.time() + 300  # 5 minutos
            except Exception as e:
                logger.debug(f"Erro ao usar FlareSolverr para {url}: {e}. Tentando requisição direta.")
        
        headers = {'Referer': referer if referer else self.base_url}
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            html_content = response.content
            
            if self.redis and not self._is_test:
                try:
                    short_cache_key = html_short_key(url)
                    self.redis.setex(
                        short_cache_key,
                        Config.HTML_CACHE_TTL_SHORT,
                        html_content
                    )
                    
                    cache_key = html_long_key(url)
                    self.redis.setex(
                        cache_key,
                        Config.HTML_CACHE_TTL_LONG,
                        html_content
                    )
                except:
                    pass
            
            return BeautifulSoup(html_content, 'html.parser')
        
        except Exception as e:
            logger.error(f"Erro ao obter documento {url}: {e}")
            return None
    
    @abstractmethod
    def search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        """
        Busca torrents por query
        
        Args:
            query: Query de busca
            filter_func: Função opcional para filtrar torrents antes do enriquecimento
        """
        pass
    
    def _prepare_page_flags(self, max_items: Optional[int] = None) -> Tuple[bool, bool, bool]:
        """
        Prepara flags para processamento de página baseado em max_items e configurações.
        Centraliza a lógica de controle de metadata/trackers durante testes (query vazia).
        
        Args:
            max_items: Limite máximo de itens. Se None, indica query vazia
            
        Returns:
            Tuple (is_using_default_limit, skip_metadata, skip_trackers)
        """
        is_using_default_limit = max_items is None
        skip_metadata = False
        skip_trackers = False
        self._skip_metadata = skip_metadata
        self._is_test = is_using_default_limit
        
        return is_using_default_limit, skip_metadata, skip_trackers
    
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        """
        Extrai links de torrents da página inicial.
        Deve ser implementado por cada scraper específico.
        
        Args:
            doc: BeautifulSoup document da página inicial
            
        Returns:
            Lista de URLs de páginas individuais de torrents
        """
        return []
    
    def _default_get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        """
        Implementação padrão de get_page que pode ser reutilizada pelos scrapers.
        """
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items)
        
        try:
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel, process_links_sequential
            )
            page_url = build_page_url(self.base_url, self.page_pattern, page)
            
            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []
            
            links = self._extract_links_from_page(doc)
            effective_max = get_effective_max_items(max_items)
            links = limit_list(links, effective_max)
            
            if effective_max > 0:
                all_torrents = process_links_sequential(
                    links,
                    self._get_torrents_from_page,
                    None
                )
            else:
                all_torrents = process_links_parallel(
                    links,
                    self._get_torrents_from_page,
                    None
                )
            
            enriched = self.enrich_torrents(
                all_torrents,
                skip_metadata=skip_metadata,
                skip_trackers=skip_trackers
            )
            return enriched
        finally:
            self._skip_metadata = False
            self._skip_metadata = False
    
    def _default_search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
        links = self._search_variations(query)
        
        all_torrents = []
        for link in links:
            torrents = self._get_torrents_from_page(link)
            all_torrents.extend(torrents)
        
        return self.enrich_torrents(all_torrents, filter_func=filter_func)
    
    @abstractmethod
    def get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        """
        Obtém torrents de uma página específica
        
        Args:
            page: Número da página
            max_items: Limite máximo de itens. Se None ou 0, não há limite (ilimitado)
        """
        pass
    
    @abstractmethod
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        """
        Extrai torrents de uma página individual de torrent.
        Deve ser implementado por cada scraper específico.
        
        Args:
            link: URL da página individual de torrent
            
        Returns:
            Lista de dicionários com dados dos torrents
        """
        pass

    def _resolve_link(self, href: str) -> Optional[str]:
        """
        Resolve automaticamente qualquer link (magnet direto ou protegido).
        Se for magnet direto, retorna como está. Se for link protegido, resolve via link_resolver.
        
        Args:
            href: URL do link (magnet ou protegido)
            
        Returns:
            URL do magnet link resolvido ou None se não conseguir resolver
        """
        if not href:
            return None
        
        # Se já é magnet direto, retorna como está
        if href.startswith('magnet:'):
            # Remove entidades HTML comuns
            href = href.replace('&amp;', '&').replace('&#038;', '&')
            return html.unescape(href)
        
        # Tenta resolver como link protegido
        try:
            from utils.parsing.link_resolver import is_protected_link, resolve_protected_link
            if is_protected_link(href):
                resolved = resolve_protected_link(href, self.session, self.base_url, redis=self.redis)
                return resolved
        except Exception as e:
            logger.debug(f"Erro ao resolver link {href[:50]}...: {e}")
        
        # Se não é magnet e não é protegido, retorna None
        return None
    
    def enrich_torrents(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        # Preenche dados de seeds/leechers via trackers
        from core.enrichers.torrent_enricher import TorrentEnricher
        from scraper import available_scraper_types
        
        if not hasattr(self, '_enricher'):
            self._enricher = TorrentEnricher()
        
        scraper_name = None
        if hasattr(self, 'SCRAPER_TYPE'):
            scraper_type = getattr(self, 'SCRAPER_TYPE', '')
            types_info = available_scraper_types()
            normalized_type = scraper_type.lower().strip()
            if normalized_type in types_info:
                scraper_name = types_info[normalized_type].get('display_name', scraper_type)
            else:
                scraper_name = getattr(self, 'DISPLAY_NAME', '') or scraper_type
        
        return self._enricher.enrich(torrents, skip_metadata, skip_trackers, filter_func, scraper_name=scraper_name)
    
    def _ensure_titles_complete(self, torrents: List[Dict]) -> None:
        # Garante que os títulos dos torrents estão completos
        from magnet.metadata import fetch_metadata_from_itorrents
        
        for torrent in torrents:
            title = torrent.get('title', '')
            if not title or len(title.strip()) < 10:
                info_hash = torrent.get('info_hash')
                if info_hash:
                    # Verifica cross_data primeiro (evita consulta desnecessária ao metadata)
                    try:
                        from utils.text.cross_data import get_cross_data_from_redis
                        cross_data = get_cross_data_from_redis(info_hash)
                        if cross_data and cross_data.get('release_title_magnet'):
                            # Se já temos release_title_magnet no cross_data, não precisa buscar metadata
                            # O título já foi processado corretamente durante o scraping
                            continue
                    except Exception:
                        pass
                    
                    # Só busca metadata se não encontrou no cross_data
                    try:
                        metadata = fetch_metadata_from_itorrents(info_hash)
                        if metadata and metadata.get('name'):
                            name = metadata.get('name', '').strip()
                            if name and len(name) >= 3:
                                torrent['title'] = name
                    except Exception:
                        pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        # Busca metadata para todos os torrents de uma vez com semáforo global
        from magnet.metadata import fetch_metadata_from_itorrents
        from magnet.parser import MagnetParser
        from utils.concurrency.metadata_semaphore import acquire_metadata_slot, release_metadata_slot
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            # Adquire slot no semáforo global antes de fazer requisição
            acquire_metadata_slot()
            try:
                # Obtém info_hash
                info_hash = torrent.get('info_hash')
                if not info_hash:
                    try:
                        magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                        info_hash = magnet_data.get('info_hash')
                    except Exception:
                        return (torrent, None)
                
                if not info_hash:
                    return (torrent, None)
                
                # Verifica cross_data primeiro (evita consulta desnecessária ao metadata)
                # Mas só pula se já tem TUDO que precisa (release_title_magnet, size, date)
                try:
                    from utils.text.cross_data import get_cross_data_from_redis
                    cross_data = get_cross_data_from_redis(info_hash)
                    if cross_data:
                        has_release_title = cross_data.get('release_title_magnet')
                        has_size = cross_data.get('size')
                        # Se já temos release_title_magnet E size no cross_data, pode pular metadata
                        # (date pode vir depois, mas não é crítico)
                        if has_release_title and has_size:
                            # Retorna None para indicar que não precisa buscar
                            return (torrent, None)
                except Exception:
                    pass
                
                metadata = fetch_metadata_from_itorrents(info_hash)
                return (torrent, metadata)
            except Exception:
                return (torrent, None)
            finally:
                # Sempre libera o slot, mesmo em caso de erro
                release_metadata_slot()
        
        if len(torrents_to_fetch) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            # Limita workers locais, mas o semáforo global controla requisições simultâneas
            max_workers = min(8, len(torrents_to_fetch))
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_torrent = {
                    executor.submit(fetch_metadata_for_torrent, t): t
                    for t in torrents_to_fetch
                }
                
                for future in as_completed(future_to_torrent):
                    try:
                        torrent, metadata = future.result(timeout=10)
                        if metadata:
                            torrent['_metadata'] = metadata
                            torrent['_metadata_fetched'] = True
                    except Exception as e:
                        pass
        else:
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                except Exception:
                    pass

    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        # Aplica fallbacks para obter tamanho do torrent
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        metadata_enabled = not skip_metadata
        
        for torrent in torrents:
            html_size = torrent.get('size', '')
            info_hash = torrent.get('info_hash', '').lower()
            
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            # Primeiro, tenta buscar do cross-data
            if info_hash and len(info_hash) == 40:
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data and cross_data.get('size'):
                    cross_size = cross_data.get('size')
                    if cross_size and cross_size.strip() and cross_size != 'N/A':
                        torrent['size'] = cross_size.strip()
                        continue
            
            magnet_data = None
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                pass
            
            torrent['size'] = ''
            
            if metadata_enabled:
                if torrent.get('_metadata') and 'size' in torrent['_metadata']:
                    try:
                        from utils.text.text_processing import format_bytes
                        size_bytes = torrent['_metadata']['size']
                        formatted_size = format_bytes(size_bytes)
                        if formatted_size:
                            torrent['size'] = formatted_size
                            # Salva no cross-data
                            if info_hash and len(info_hash) == 40:
                                try:
                                    save_cross_data_to_redis(info_hash, {'size': formatted_size})
                                except Exception:
                                    pass
                            continue
                    except Exception:
                        pass
                
                try:
                    from magnet.metadata import get_torrent_size
                    # Usa info_hash já definido (em lowercase) ou tenta extrair do magnet
                    current_info_hash = info_hash
                    if not current_info_hash and magnet_data:
                        current_info_hash = (magnet_data.get('info_hash') or '').lower()
                    
                    if current_info_hash and len(current_info_hash) == 40:
                        metadata_size = get_torrent_size(magnet_link, current_info_hash)
                        if metadata_size:
                            torrent['size'] = metadata_size
                            # Salva no cross-data
                            try:
                                save_cross_data_to_redis(current_info_hash, {'size': metadata_size})
                            except Exception:
                                pass
                            continue
                except Exception:
                    pass
            
            if not torrent.get('size') and magnet_data:
                try:
                    xl_value = magnet_data.get('params', {}).get('xl')
                    if xl_value:
                        try:
                            formatted_size = format_bytes(int(xl_value))
                            if formatted_size:
                                torrent['size'] = formatted_size
                                # Salva no cross-data
                                if info_hash and len(info_hash) == 40:
                                    try:
                                        save_cross_data_to_redis(info_hash, {'size': formatted_size})
                                    except Exception:
                                        pass
                                continue
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    pass
            
            if not torrent.get('size') and html_size:
                torrent['size'] = html_size
                continue
            
            if not torrent.get('size') and html_size:
                torrent['size'] = html_size

    def _apply_date_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        # Aplica fallback para obter data de criação do torrent
        from datetime import datetime
        
        metadata_enabled = not skip_metadata
        
        if not metadata_enabled:
            return
        
        for torrent in torrents:
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
            
            try:
                metadata = torrent.get('_metadata')
                if not metadata:
                    from magnet.metadata import fetch_metadata_from_itorrents
                    metadata = fetch_metadata_from_itorrents(info_hash)
                
                if metadata and metadata.get('creation_date'):
                    creation_timestamp = metadata['creation_date']
                    try:
                        creation_date = datetime.fromtimestamp(creation_timestamp)
                        torrent['date'] = creation_date.isoformat()
                    except (ValueError, OSError):
                        pass
            except Exception:
                pass

    def _attach_peers(self, torrents: List[Dict]) -> None:
        if not self.tracker_service:
            return
        
        # Primeiro, tenta buscar dados de tracker do cross-data
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        infohash_map: Dict[str, List[str]] = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            # Tenta buscar do cross-data primeiro
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                # Se ambos estão presentes (mesmo que sejam 0), usa do cross-data para evitar scrape desnecessário
                if tracker_seed is not None and tracker_leech is not None:
                    torrent['seed_count'] = tracker_seed
                    torrent['leech_count'] = tracker_leech
                    continue
            
            # Se não encontrou no cross-data, adiciona para fazer scrape
            trackers = torrent.get('trackers') or []
            
            # Se não tem trackers no torrent, tenta extrair do magnet_link
            if not trackers:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    try:
                        from utils.parsing.magnet_utils import extract_trackers_from_magnet
                        trackers = extract_trackers_from_magnet(magnet_link)
                    except Exception:
                        pass
            
            # Adiciona para fazer scrape (mesmo se trackers estiver vazio, o TrackerService usa lista dinâmica)
            if info_hash:
                infohash_map.setdefault(info_hash, [])
                if trackers:
                    infohash_map[info_hash].extend(trackers)
                # Se não tem trackers, adiciona mesmo assim (TrackerService usará lista dinâmica)
                elif info_hash not in infohash_map or not infohash_map[info_hash]:
                    infohash_map[info_hash] = []
        
        if not infohash_map:
            return
        
        # Faz scrape dos trackers
        peers_map = self.tracker_service.get_peers_bulk(infohash_map)
        
        # Atualiza torrents e salva no cross-data
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
            
            # Salva no cross-data sempre que obtém dados do tracker (mesmo se 0, para evitar consultas futuras)
            # Isso permite que outros scrapers reutilizem o resultado (0 ou não)
            try:
                cross_data_to_save = {
                    'tracker_seed': seed,
                    'tracker_leech': leech
                }
                save_cross_data_to_redis(info_hash, cross_data_to_save)
            except Exception as e:
                # Log silencioso - não queremos interromper o processamento por erro no cross-data
                logger.debug(f"Erro ao salvar tracker no cross-data para {info_hash[:16]}...: {e}")

