"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable, Tuple
from bs4 import BeautifulSoup
import requests
from cache.redis_client import get_redis_client
from app.config import Config
from tracker import get_tracker_service  # type: ignore[import]
from magnet.parser import MagnetParser
from utils.text.text_processing import format_bytes
from utils.http.flaresolverr import FlareSolverrClient

logger = logging.getLogger(__name__)


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
        self._skip_metadata = False  # Flag temporário para controlar busca de metadata durante extração
        self._is_test = False  # Flag para indicar se está em modo de teste (não usa Redis)
        
        # Inicializa FlareSolverr se habilitado e configurado
        self.use_flaresolverr = use_flaresolverr and Config.FLARESOLVERR_ADDRESS is not None
        self.flaresolverr_client: Optional[FlareSolverrClient] = None
        if self.use_flaresolverr:
            try:
                self.flaresolverr_client = FlareSolverrClient(Config.FLARESOLVERR_ADDRESS)
            except Exception as e:
                logger.warning(f"Falha ao inicializar FlareSolverr: {e}. Continuando sem FlareSolverr.")
                self.use_flaresolverr = False
    
    # Obtém documento HTML do cache ou faz requisição
    def get_document(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        # Tenta obter do cache de longa duração (se Redis disponível e não for teste)
        if self.redis and not self._is_test:
            try:
                cache_key = f"doc:{url}"
                cached = self.redis.get(cache_key)
                if cached:
                    return BeautifulSoup(cached, 'html.parser')
            except:
                pass
        
        # Tenta obter do cache de curta duração (se Redis disponível e não for teste)
        if self.redis and not self._is_test:
            try:
                short_cache_key = f"short:{url}"
                cached = self.redis.get(short_cache_key)
                if cached:
                    return BeautifulSoup(cached, 'html.parser')
            except:
                pass
        
        # Faz requisição HTTP
        html_content = None
        
        # Tenta usar FlareSolverr se habilitado
        # Mas pula se URL contém dois pontos codificados (%3A) - problema conhecido do FlareSolverr
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
                        # Sucesso com FlareSolverr, salva no cache (se não for teste)
                        if self.redis and not self._is_test:
                            try:
                                short_cache_key = f"short:{url}"
                                self.redis.setex(
                                    short_cache_key,
                                    Config.HTML_CACHE_TTL_SHORT,
                                    html_content
                                )
                                
                                cache_key = f"doc:{url}"
                                self.redis.setex(
                                    cache_key,
                                    Config.HTML_CACHE_TTL_LONG,
                                    html_content
                                )
                            except:
                                pass  # Ignora erros de cache
                        
                        return BeautifulSoup(html_content, 'html.parser')
                    else:
                        # Se solve retornou None (erro 500 ou outro)
                        # Verifica se já tentou com essa URL recentemente (cache de falhas)
                        failure_key = f"flaresolverr:failure:{url}"
                        should_retry = True
                        
                        if self.redis and not self._is_test:
                            try:
                                if self.redis.exists(failure_key):
                                    logger.debug(f"URL {url} já falhou recentemente com FlareSolverr. Pulando retry.")
                                    should_retry = False
                                else:
                                    # Marca como falha por 5 minutos ANTES de tentar retry
                                    self.redis.setex(failure_key, 300, "1")
                            except Exception:
                                pass  # Se Redis falhar, continua com retry
                        
                        # Verifica se URL contém dois pontos codificados (%3A) - problema conhecido do FlareSolverr
                        if "%3A" in url or "%3a" in url.lower():
                            logger.debug(f"URL contém dois pontos codificados (%3A). FlareSolverr pode ter problemas. Pulando retry.")
                            should_retry = False
                        
                        if should_retry:
                            logger.debug(f"FlareSolverr retornou None para {url}. Tentando criar nova sessão.")
                            # Força criação de nova sessão (invalidação já foi feita no solve)
                            new_session_id = self.flaresolverr_client.get_or_create_session(
                                self.base_url,
                                skip_redis=self._is_test
                            )
                            if new_session_id and new_session_id != session_id:
                                # Tenta novamente com nova sessão
                                html_content = self.flaresolverr_client.solve(
                                    url,
                                    new_session_id,
                                    referer if referer else self.base_url,
                                    self.base_url,
                                    skip_redis=self._is_test
                                )
                                if html_content:
                                    # Sucesso com nova sessão, remove marca de falha e salva no cache (se não for teste)
                                    if self.redis and not self._is_test:
                                        try:
                                            self.redis.delete(failure_key)
                                            short_cache_key = f"short:{url}"
                                            self.redis.setex(
                                                short_cache_key,
                                                Config.HTML_CACHE_TTL_SHORT,
                                                html_content
                                            )
                                            
                                            cache_key = f"doc:{url}"
                                            self.redis.setex(
                                                cache_key,
                                                Config.HTML_CACHE_TTL_LONG,
                                                html_content
                                            )
                                        except:
                                            pass  # Ignora erros de cache
                                    
                                    return BeautifulSoup(html_content, 'html.parser')
                                else:
                                    # Se ainda falhou, confirma a marca de falha (se não for teste)
                                    if self.redis and not self._is_test:
                                        try:
                                            self.redis.setex(failure_key, 300, "1")
                                        except:
                                            pass
            except Exception as e:
                logger.debug(f"Erro ao usar FlareSolverr para {url}: {e}. Tentando requisição direta.")
        
        # Fallback: requisição HTTP direta (ou se FlareSolverr não habilitado)
        headers = {'Referer': referer if referer else self.base_url}
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            html_content = response.content
            
            # Salva no cache (se Redis disponível e não for teste)
            if self.redis and not self._is_test:
                try:
                    short_cache_key = f"short:{url}"
                    self.redis.setex(
                        short_cache_key,
                        Config.HTML_CACHE_TTL_SHORT,
                        html_content
                    )
                    
                    cache_key = f"doc:{url}"
                    self.redis.setex(
                        cache_key,
                        Config.HTML_CACHE_TTL_LONG,
                        html_content
                    )
                except:
                    pass  # Ignora erros de cache
            
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
            max_items: Limite máximo de itens. Se None, indica teste do Prowlarr (query vazia)
            
        Returns:
            Tuple (is_using_default_limit, skip_metadata, skip_trackers)
        """
        is_using_default_limit = max_items is None
        
        # Durante testes (query vazia), controla se coleta metadata/trackers via variável de ambiente
        # Se EMPTY_QUERY_COLLECT_METADATA_TRACKERS=true, coleta normalmente mesmo em testes
        skip_metadata = is_using_default_limit and not Config.EMPTY_QUERY_COLLECT_METADATA_TRACKERS
        skip_trackers = is_using_default_limit and not Config.EMPTY_QUERY_COLLECT_METADATA_TRACKERS
        
        # Configura flags do scraper
        self._skip_metadata = skip_metadata
        self._is_test = is_using_default_limit
        
        return is_using_default_limit, skip_metadata, skip_trackers
    
    # Extrai links da página inicial (deve ser implementado por cada scraper)
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
    
    # Método helper padrão para get_page - pode ser usado pela maioria dos scrapers
    def _default_get_page(self, page: str = '1', max_items: Optional[int] = None) -> List[Dict]:
        """
        Implementação padrão de get_page que pode ser reutilizada pelos scrapers.
        Apenas extrai links usando _extract_links_from_page e processa.
        """
        # Prepara flags de teste/metadata/trackers (centralizado no BaseScraper)
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items)
        
        try:
            # Constrói URL da página usando função utilitária
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel, process_links_sequential
            )
            page_url = build_page_url(self.base_url, self.page_pattern, page)
            
            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []
            
            # Extrai links usando método específico do scraper
            links = self._extract_links_from_page(doc)
            
            # Obtém limite efetivo usando função utilitária
            effective_max = get_effective_max_items(max_items)
            
            # Limita links se houver limite (EMPTY_QUERY_MAX_LINKS limita quantos links processar)
            links = limit_list(links, effective_max)
            
            # Quando há limite configurado, processa sequencialmente para manter ordem original
            # Caso contrário, processa em paralelo para melhor performance
            if effective_max > 0:
                all_torrents = process_links_sequential(
                    links,
                    self._get_torrents_from_page,
                    None  # Sem limite no processamento - já limitamos os links acima
                )
            else:
                all_torrents = process_links_parallel(
                    links,
                    self._get_torrents_from_page,
                    None  # Sem limite no processamento - já limitamos os links acima
                )
            
            # Enriquece torrents (usa flags preparadas pelo BaseScraper)
            enriched = self.enrich_torrents(
                all_torrents,
                skip_metadata=skip_metadata,
                skip_trackers=skip_trackers
            )
            # Retorna todos os magnets encontrados (sem limite nos resultados finais)
            return enriched
        finally:
            # Restaura flags após processamento
            self._skip_metadata = False
            self._is_test = False
    
    # Método helper padrão para search - pode ser usado pela maioria dos scrapers
    def _default_search(self, query: str, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        """
        Implementação padrão de search que pode ser reutilizada pelos scrapers.
        Usa _search_variations para buscar links e processa sequencialmente.
        """
        # Normaliza query para FlareSolverr (substitui dois pontos por espaço)
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
        
        # Busca variações da query (deve ser implementado por cada scraper)
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

    def enrich_torrents(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
        """Preenche dados de seeds/leechers via trackers (quando possível) - delega para TorrentEnricher do core"""
        from core.enrichers.torrent_enricher import TorrentEnricher
        
        if not hasattr(self, '_enricher'):
            self._enricher = TorrentEnricher()
        
        return self._enricher.enrich(torrents, skip_metadata, skip_trackers, filter_func)
    
    def _ensure_titles_complete(self, torrents: List[Dict]) -> None:
        """
        Garante que os títulos dos torrents estão completos, buscando metadata se necessário.
        Isso é importante para que o filtro funcione corretamente com títulos completos.
        
        NOTA: Torrents com 'dn' completo já têm título completo do prepare_release_title,
        então só buscamos metadata para títulos muito curtos (< 10 chars) que podem ter
        falhado na busca anterior ou não tinham 'dn'.
        """
        from magnet.metadata import fetch_metadata_from_itorrents
        
        for torrent in torrents:
            # Só busca metadata se o título parece incompleto (muito curto)
            # Torrents com 'dn' completo já têm título completo, então não precisam buscar
            title = torrent.get('title', '')
            if not title or len(title.strip()) < 10:
                info_hash = torrent.get('info_hash')
                if info_hash:
                    try:
                        metadata = fetch_metadata_from_itorrents(info_hash)
                        if metadata and metadata.get('name'):
                            name = metadata.get('name', '').strip()
                            if name and len(name) >= 3:
                                # Atualiza o título se encontrou um melhor
                                torrent['title'] = name
                    except Exception:
                        pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        """
        Busca metadata para todos os torrents de uma vez e armazena no objeto torrent.
        Isso evita buscas duplicadas quando precisamos de size e date.
        Processa em paralelo para melhor performance.
        """
        from magnet.metadata import fetch_metadata_from_itorrents
        from magnet.parser import MagnetParser
        
        # Filtra torrents que precisam de metadata
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        # Função auxiliar para buscar metadata de um único torrent - retorna (torrent, metadata)
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
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
                
                # Busca metadata com timeout
                metadata = fetch_metadata_from_itorrents(info_hash)
                return (torrent, metadata)
            except Exception:
                return (torrent, None)
        
        # Processa em paralelo se houver múltiplos torrents
        if len(torrents_to_fetch) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            max_workers = min(6, len(torrents_to_fetch))  # Máximo de 6 workers simultâneos
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_torrent = {
                    executor.submit(fetch_metadata_for_torrent, t): t
                    for t in torrents_to_fetch
                }
                
                for future in as_completed(future_to_torrent):
                    try:
                        torrent, metadata = future.result(timeout=10)  # Timeout de 10 segundos
                        if metadata:
                            torrent['_metadata'] = metadata
                            torrent['_metadata_fetched'] = True
                    except Exception as e:
                        # Ignora erros, os fallbacks vão tentar depois
                        pass
        else:
            # Processa sequencialmente se houver apenas 1 torrent
            for torrent in torrents_to_fetch:
                try:
                    torrent, metadata = fetch_metadata_for_torrent(torrent)
                    if metadata:
                        torrent['_metadata'] = metadata
                        torrent['_metadata_fetched'] = True
                except Exception:
                    pass  # Ignora erros, os fallbacks vão tentar depois

    def _apply_size_fallback(self, torrents: List[Dict], skip_metadata: bool = False) -> None:
        """
        Aplica fallbacks para obter tamanho do torrent.
        
        Ordem de prioridade (metadata é mais confiável):
        1. Busca via metadata API (iTorrents.org) - PRIORIDADE (mais confiável)
           - Verifica cache Redis primeiro
           - Se não tiver em cache, busca no iTorrents.org
        2. Parâmetro 'xl' do magnet link - FALLBACK
           - Extrai do próprio link magnet (mais rápido, mas nem sempre disponível)
        3. Tamanho do HTML (extraído pelo scraper) - FALLBACK FINAL
           - Usa o tamanho que o scraper extraiu do HTML do site
        
        Args:
            torrents: Lista de torrents para processar
            skip_metadata: Se True, pula busca de metadata (útil para testes do Prowlarr)
        """
        # Verifica se metadata está habilitado e não deve ser pulado
        metadata_enabled = Config.MAGNET_METADATA_ENABLED and not skip_metadata
        
        for torrent in torrents:
            # Salva tamanho do HTML como fallback final (se existir)
            html_size = torrent.get('size', '')
            
            magnet_link = torrent.get('magnet_link')
            if not magnet_link:
                continue
            
            # Parseia magnet uma vez para reutilizar
            magnet_data = None
            try:
                magnet_data = MagnetParser.parse(magnet_link)
            except Exception:
                pass
            
            # Limpa tamanho atual para tentar metadata primeiro
            torrent['size'] = ''
            
            # Tentativa 1: Busca via metadata API (iTorrents.org) - PRIORIDADE
            if metadata_enabled:
                # Tenta usar metadata já buscado primeiro
                if torrent.get('_metadata') and 'size' in torrent['_metadata']:
                    try:
                        from utils.text.text_processing import format_bytes
                        size_bytes = torrent['_metadata']['size']
                        formatted_size = format_bytes(size_bytes)
                        if formatted_size:
                            torrent['size'] = formatted_size
                            continue  # Tamanho encontrado, passa para próximo
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
                            continue  # Tamanho encontrado, passa para próximo
                except Exception:
                    pass
            
            # Tentativa 2: Parâmetro 'xl' do magnet link - FALLBACK
            if not torrent.get('size') and magnet_data:
                try:
                    xl_value = magnet_data.get('params', {}).get('xl')
                    if xl_value:
                        try:
                            formatted_size = format_bytes(int(xl_value))
                            if formatted_size:
                                torrent['size'] = formatted_size
                                continue  # Tamanho encontrado, passa para próximo
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    pass
            
            # Tentativa 3: Usa tamanho do HTML (fallback final)
            if not torrent.get('size') and html_size:
                torrent['size'] = html_size
                continue  # Tamanho encontrado, passa para próximo
            
            # Se ainda não tem tamanho, mantém o que veio do HTML (se houver)
            if not torrent.get('size') and html_size:
                torrent['size'] = html_size

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
                    except (ValueError, OSError):
                        # Se falhar, mantém date do HTML (se houver)
                        pass
            except Exception:
                # Se falhar, mantém date do HTML (se houver)
                pass

    def _attach_peers(self, torrents: List[Dict]) -> None:
        # Verifica se trackers estão habilitados via variável de ambiente
        if not Config.TRACKER_SCRAPING_ENABLED:
            return
        
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

