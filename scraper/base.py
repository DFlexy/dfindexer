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
from utils.text.utils import format_bytes
from utils.http.flaresolverr import FlareSolverrClient

logger = logging.getLogger(__name__)

# Cache em memória por requisição (apenas quando Redis não está disponível)
_request_cache = threading.local()

# Lock por URL para evitar requisições HTTP duplicadas simultâneas
_url_locks = {}
_url_locks_lock = threading.Lock()
_url_fetching = set()  # Conjunto para rastrear URLs sendo buscadas
_url_fetching_lock = threading.Lock()  # Lock para o conjunto _url_fetching


def _get_url_lock(url: str):
    """
    Obtém um lock específico para uma URL, evitando requisições simultâneas.
    """
    with _url_locks_lock:
        if url not in _url_locks:
            _url_locks[url] = threading.Lock()
        return _url_locks[url]


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
        
        # Configura session com connection pooling otimizado
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=Config.HTTP_POOL_CONNECTIONS if hasattr(Config, 'HTTP_POOL_CONNECTIONS') else 50,
            pool_maxsize=Config.HTTP_POOL_MAXSIZE if hasattr(Config, 'HTTP_POOL_MAXSIZE') else 100,
            max_retries=3,
            pool_block=False
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
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
        
        # Se use_flaresolverr está True mas FLARESOLVERR_ADDRESS não está configurado, mostra warning
        if use_flaresolverr and Config.FLARESOLVERR_ADDRESS is None:
            logger.warning("[[ FlareSolverr Não Conectado ]] - FLARESOLVERR_ADDRESS não configurado")
            self.use_flaresolverr = False
        
        if self.use_flaresolverr:
            try:
                self.flaresolverr_client = FlareSolverrClient(Config.FLARESOLVERR_ADDRESS)
                # Testa conexão básica (timeout curto para não travar inicialização)
                try:
                    test_response = requests.get(f"{Config.FLARESOLVERR_ADDRESS.rstrip('/')}/v1", timeout=2)
                    if test_response.status_code not in (200, 404, 405):  # 404/405 são OK (API existe)
                        raise Exception(f"FlareSolverr retornou status {test_response.status_code}")
                except requests.exceptions.ConnectionError:
                    raise Exception("Connection refused")
                except requests.exceptions.Timeout:
                    raise Exception("Connection timeout")
                except Exception as test_e:
                    # Se o teste falhar, mostra warning mas continua (pode ser temporário)
                    error_type = type(test_e).__name__
                    error_msg = str(test_e).split('\n')[0][:100] if str(test_e) else str(test_e)
                    logger.warning(f"[[ FlareSolverr Não Conectado ]] - {error_type}: {error_msg}")
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
                logger.warning(f"[[ FlareSolverr Não Conectado ]] - {error_type}: {error_msg}")
                self.use_flaresolverr = False
    
    def get_document(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        # Verifica cache local primeiro (mais rápido que Redis)
        from cache.http_cache import get_http_cache
        http_cache = get_http_cache()
        
        if not self._is_test:
            cached_local = http_cache.get(url)
            if cached_local:
                self._cache_stats['html']['hits'] += 1
                return BeautifulSoup(cached_local, 'html.parser')
        
        # Verifica Redis
        if self.redis and not self._is_test:
            try:
                cache_key = html_long_key(url)
                cached = self.redis.get(cache_key)
                if cached:
                    self._cache_stats['html']['hits'] += 1
                    return BeautifulSoup(cached, 'html.parser')
            except (AttributeError, TypeError) as e:
                # Redis client error ou cache inválido - continua para buscar do site
                logger.debug(f"Redis cache error (long): {type(e).__name__}")
            except Exception as e:
                # Outros erros de Redis - loga mas continua
                logger.debug(f"Unexpected Redis error (long): {type(e).__name__}")
        
        if self.redis and not self._is_test:
            try:
                short_cache_key = html_short_key(url)
                cached = self.redis.get(short_cache_key)
                if cached:
                    self._cache_stats['html']['hits'] += 1
                    return BeautifulSoup(cached, 'html.parser')
            except (AttributeError, TypeError) as e:
                # Redis client error ou cache inválido - continua para buscar do site
                logger.debug(f"Redis cache error (short): {type(e).__name__}")
            except Exception as e:
                # Outros erros de Redis - loga mas continua
                logger.debug(f"Unexpected Redis error (short): {type(e).__name__}")
        
        # Cache miss - será buscado do site
        # Usa lock por URL para evitar requisições simultâneas para a mesma URL
        url_lock = _get_url_lock(url)
        with url_lock:
            # Verifica cache novamente após adquirir lock (outra thread pode ter cacheado)
            if self.redis and not self._is_test:
                try:
                    cache_key = html_long_key(url)
                    cached = self.redis.get(cache_key)
                    if cached:
                        self._cache_stats['html']['hits'] += 1
                        return BeautifulSoup(cached, 'html.parser')
                except Exception:
                    pass
            
            if self.redis and not self._is_test:
                try:
                    short_cache_key = html_short_key(url)
                    cached = self.redis.get(short_cache_key)
                    if cached:
                        self._cache_stats['html']['hits'] += 1
                        return BeautifulSoup(cached, 'html.parser')
                except Exception:
                    pass
            
            # Verifica se já está sendo buscado por outra thread (evita logs duplicados)
            is_fetching = False
            with _url_fetching_lock:
                if url in _url_fetching:
                    is_fetching = True
                else:
                    _url_fetching.add(url)
            
            # Se já está sendo buscado, espera um pouco e verifica cache novamente
            if is_fetching:
                import time
                for _ in range(20):  # Tenta por até 2 segundos (20 * 0.1s)
                    time.sleep(0.1)  # Espera 100ms
                    if self.redis and not self._is_test:
                        try:
                            cache_key = html_long_key(url)
                            cached = self.redis.get(cache_key)
                            if cached:
                                with _url_fetching_lock:
                                    _url_fetching.discard(url)
                                self._cache_stats['html']['hits'] += 1
                                return BeautifulSoup(cached, 'html.parser')
                        except Exception:
                            pass
                # Se não encontrou após esperar, continua a busca (pode ter falhado ou demorado demais)
            
        self._cache_stats['html']['misses'] += 1
        
        html_content = None
        use_flaresolverr_for_this_url = (
            self.use_flaresolverr and 
            self.flaresolverr_client and 
            "%3A" not in url and 
            "%3a" not in url.lower()
        )
        
        # Log para debug: verifica se FlareSolverr deveria ser usado
        if self.use_flaresolverr and not use_flaresolverr_for_this_url:
            if not self.flaresolverr_client:
                logger.debug(f"FlareSolverr habilitado mas cliente não disponível para {url[:50]}...")
            elif "%3A" in url or "%3a" in url.lower():
                logger.debug(f"FlareSolverr pulado: URL contém %3A para {url[:50]}...")
        
        if use_flaresolverr_for_this_url:
            try:
                # LOCK: Serializa requisições ao FlareSolverr para evitar race conditions
                # quando múltiplas threads processam URLs diferentes simultaneamente
                from utils.http.flaresolverr import _get_flaresolverr_lock
                flaresolverr_lock = _get_flaresolverr_lock(self.base_url)
                
                with flaresolverr_lock:
                    session_id = self.flaresolverr_client.get_or_create_session(
                        self.base_url,
                        skip_redis=self._is_test
                    )
                    if session_id:
                        pass  # Sessão obtida com sucesso
                    else:
                        logger.warning(f"FlareSolverr: não foi possível obter/criar sessão para {url[:50]}... - tentando requisição direta (pode resultar em 403)")
                    if session_id:
                        html_content = self.flaresolverr_client.solve(
                            url,
                            session_id,
                            referer if referer else self.base_url,
                            self.base_url,
                            skip_redis=self._is_test
                        )
                    if html_content:
                        # VALIDAÇÃO: Verifica se o HTML retornado corresponde à URL solicitada
                        # Isso evita salvar HTML errado no cache
                        html_str = html_content.decode('utf-8', errors='ignore') if isinstance(html_content, bytes) else str(html_content)
                        url_slug = url.rstrip('/').split('/')[-1]
                        url_in_html = url in html_str or url_slug in html_str
                        
                        if not url_in_html:
                            logger.warning(f"FlareSolverr: HTML retornado não corresponde à URL! URL: {url[:80]}... | HTML size: {len(html_str)} bytes")
                            # Não salva no cache e não retorna - vai tentar retry ou requisição direta
                            html_content = None
                        else:
                            logger.debug(f"FlareSolverr: sucesso para {url[:50]}... ({len(html_content)} bytes)")
                            # Salva no cache local primeiro (mais rápido)
                            if not self._is_test:
                                try:
                                    from cache.http_cache import get_http_cache
                                    http_cache = get_http_cache()
                                    http_cache.set(url, html_content)
                                except:
                                    pass
                            
                            # Salva no Redis
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
                            
                            result = BeautifulSoup(html_content, 'html.parser')
                            with _url_fetching_lock:
                                _url_fetching.discard(url)
                            return result
                    else:
                        # Log removido para reduzir verbosidade - retry será tentado automaticamente
                        from cache.redis_keys import flaresolverr_failure_key
                        failure_key = flaresolverr_failure_key(url)
                        should_retry = True
                        
                        # Tenta Redis primeiro
                        if self.redis and not self._is_test:
                            try:
                                if self.redis.exists(failure_key):
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
                                should_retry = False
                            else:
                                _request_cache.flaresolverr_failures[failure_key] = time.time() + 300  # 5 minutos
                        
                        if "%3A" in url or "%3a" in url.lower():
                            should_retry = False
                        
                        if should_retry:
                            # Retry ainda está dentro do lock, então continua usando o mesmo lock
                            # Tenta obter/criar sessão (pode retornar a mesma se não foi invalidada)
                            new_session_id = self.flaresolverr_client.get_or_create_session(
                                self.base_url,
                                skip_redis=self._is_test
                            )
                            if new_session_id:
                                # Se a sessão mudou, tenta com a nova. Se for a mesma, tenta novamente (pode ser erro temporário)
                                if new_session_id != session_id:
                                    logger.debug(f"FlareSolverr: usando nova sessão (anterior: {session_id[:20]}..., nova: {new_session_id[:20]}...)")
                                
                                html_content = self.flaresolverr_client.solve(
                                    url,
                                    new_session_id,
                                    referer if referer else self.base_url,
                                    self.base_url,
                                    skip_redis=self._is_test
                                )
                                if html_content:
                                    # VALIDAÇÃO: Verifica se o HTML retornado corresponde à URL solicitada
                                    html_str = html_content.decode('utf-8', errors='ignore') if isinstance(html_content, bytes) else str(html_content)
                                    url_slug = url.rstrip('/').split('/')[-1]
                                    url_in_html = url in html_str or url_slug in html_str
                                    
                                    if not url_in_html:
                                        logger.warning(f"FlareSolverr retry: HTML retornado não corresponde à URL! URL: {url[:80]}... | HTML size: {len(html_str)} bytes")
                                        html_content = None
                                    else:
                                        # Salva no cache local primeiro
                                        if not self._is_test:
                                            try:
                                                from cache.http_cache import get_http_cache
                                                http_cache = get_http_cache()
                                                http_cache.set(url, html_content)
                                            except:
                                                pass
                                        
                                        # Salva no Redis
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
                                        
                                        result = BeautifulSoup(html_content, 'html.parser')
                                        with _url_fetching_lock:
                                            _url_fetching.discard(url)
                                        return result
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
                logger.debug(f"FlareSolverr error: {type(e).__name__} - tentando requisição direta")
        
        # Se FlareSolverr está habilitado mas ainda não tentou (ou falhou anteriormente),
        # verifica se o cache de falha expirou e tenta novamente antes de fazer requisição direta
        if use_flaresolverr_for_this_url and not html_content:
            from cache.redis_keys import flaresolverr_failure_key
            failure_key = flaresolverr_failure_key(url)
            should_try_flaresolverr = True
            
            # Verifica se há cache de falha ainda ativo
            if self.redis and not self._is_test:
                try:
                    if self.redis.exists(failure_key):
                        should_try_flaresolverr = False
                except Exception:
                    pass
            elif not self.redis and not self._is_test:
                if hasattr(_request_cache, 'flaresolverr_failures'):
                    expire_at = _request_cache.flaresolverr_failures.get(failure_key, 0)
                    if time.time() < expire_at:
                        should_try_flaresolverr = False
            
            # Se o cache de falha expirou, tenta novamente com FlareSolverr
            if should_try_flaresolverr and self.flaresolverr_client:
                try:
                    # LOCK: Serializa requisições ao FlareSolverr para evitar race conditions
                    # IMPORTANTE: Mesmo no retry, usa o lock para garantir serialização
                    from utils.http.flaresolverr import _get_flaresolverr_lock
                    flaresolverr_lock = _get_flaresolverr_lock(self.base_url)
                    
                    with flaresolverr_lock:
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
                            # VALIDAÇÃO: Verifica se o HTML retornado corresponde à URL solicitada
                            html_str = html_content.decode('utf-8', errors='ignore') if isinstance(html_content, bytes) else str(html_content)
                            url_slug = url.rstrip('/').split('/')[-1]
                            url_in_html = url in html_str or url_slug in html_str
                            
                            if not url_in_html:
                                logger.warning(f"FlareSolverr retry (cache expirado): HTML retornado não corresponde à URL! URL: {url[:80]}... | HTML size: {len(html_str)} bytes")
                                html_content = None
                            else:
                                # Salva no cache local primeiro
                                if not self._is_test:
                                    try:
                                        from cache.http_cache import get_http_cache
                                        http_cache = get_http_cache()
                                        http_cache.set(url, html_content)
                                    except:
                                        pass
                                
                                # Salva no Redis e remove cache de falha
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
                                
                                result = BeautifulSoup(html_content, 'html.parser')
                                with _url_fetching_lock:
                                    _url_fetching.discard(url)
                                return result
                        else:
                            # Marca como falha novamente
                            if self.redis and not self._is_test:
                                try:
                                    self.redis.setex(failure_key, 300, "1")
                                except:
                                    pass
                            elif not self.redis and not self._is_test:
                                if not hasattr(_request_cache, 'flaresolverr_failures'):
                                    _request_cache.flaresolverr_failures = {}
                                _request_cache.flaresolverr_failures[failure_key] = time.time() + 300
                except Exception as e:
                    logger.debug(f"FlareSolverr retry error: {type(e).__name__} - tentando requisição direta")
        
        # Se FlareSolverr está habilitado mas não foi usado, loga aviso apenas em DEBUG para reduzir verbosidade
        if self.use_flaresolverr and not html_content:
            logger.debug(f"FlareSolverr habilitado mas requisição direta será feita para {url[:50]}... (pode resultar em 403)")
        
        headers = {'Referer': referer if referer else self.base_url}
        
        try:
            import time as time_module
            start_time = time_module.time()
            response = self.session.get(url, headers=headers, timeout=Config.HTTP_REQUEST_TIMEOUT)
            elapsed_time = time_module.time() - start_time
            response.raise_for_status()
            html_content = response.content
            
            # Salva no cache local primeiro (mais rápido)
            if not self._is_test:
                try:
                    from cache.http_cache import get_http_cache
                    http_cache = get_http_cache()
                    http_cache.set(url, html_content)
                except:
                    pass
            
            # Salva no Redis
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
            
            result = BeautifulSoup(html_content, 'html.parser')
            with _url_fetching_lock:
                _url_fetching.discard(url)
            return result
        
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
            
            # Erros HTTP do servidor (500, 502, 503, 520, etc) são esperados e não indicam problema no nosso código
            # Loga como WARNING em vez de ERROR
            # A mensagem de erro HTTP já inclui a URL, então não precisamos duplicar
            if error_type == 'HTTPError' and ('500' in error_msg or '502' in error_msg or '503' in error_msg or '520' in error_msg or '521' in error_msg or '522' in error_msg or '523' in error_msg or '524' in error_msg):
                logger.warning(f"Document error: {error_type} - {error_msg}")
            else:
                # Para outros erros, adiciona a URL se não estiver na mensagem
                url_preview = url[:50] if url else 'N/A'
                if url and url not in error_msg:
                    logger.error(f"Document error: {error_type} - {error_msg} (url: {url_preview}...)")
                else:
                    logger.error(f"Document error: {error_type} - {error_msg}")
            
            # Remove do conjunto de URLs sendo buscadas mesmo em caso de erro
            with _url_fetching_lock:
                _url_fetching.discard(url)
            
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
    
    def _prepare_page_flags(self, max_items: Optional[int] = None, is_test: bool = False) -> Tuple[bool, bool, bool]:
        """
        Prepara flags para processamento de página baseado em max_items e configurações.
        Centraliza a lógica de controle de metadata/trackers durante testes (query vazia).
        
        Args:
            max_items: Limite máximo de itens. Se None, indica query vazia
            is_test: Flag indicando se é uma busca sem query (teste do Prowlarr)
                     Quando True, o cache HTML não é usado para sempre buscar HTML fresco
            
        Returns:
            Tuple (is_using_default_limit, skip_metadata, skip_trackers)
        """
        is_using_default_limit = max_items is None
        skip_metadata = False
        skip_trackers = False
        self._skip_metadata = skip_metadata
        # IMPORTANTE: _is_test deve ser True quando is_test=True (query vazia)
        # Isso garante que consultas sem query sempre busquem HTML fresco e vejam novos links atualizados
        # O IndexerService passa is_test=True explicitamente quando a query está vazia
        self._is_test = is_test or is_using_default_limit
        
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
    
    def _default_get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        """
        Implementação padrão de get_page que pode ser reutilizada pelos scrapers.
        """
        is_using_default_limit, skip_metadata, skip_trackers = self._prepare_page_flags(max_items, is_test=is_test)
        
        try:
            from utils.concurrency.scraper_helpers import (
                build_page_url, get_effective_max_items, limit_list,
                process_links_parallel
            )
            page_url = build_page_url(self.base_url, self.page_pattern, page)
            
            doc = self.get_document(page_url, self.base_url)
            if not doc:
                return []
            
            links = self._extract_links_from_page(doc)
            effective_max = get_effective_max_items(max_items)
            # Limita links ANTES do processamento (EMPTY_QUERY_MAX_LINKS limita quantos links processar)
            links = limit_list(links, effective_max)
            
            # Usa processamento paralelo centralizado (mantém ordem automaticamente)
            # NÃO passa limite de torrents - o limite já foi aplicado nos links acima
            all_torrents = process_links_parallel(
                links,
                self._get_torrents_from_page,
                None,  # Sem limite de torrents - processa todos os links limitados
                scraper_name=self.SCRAPER_TYPE if hasattr(self, 'SCRAPER_TYPE') else None,
                use_flaresolverr=self.use_flaresolverr
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
    
    def _search_variations(self, query: str) -> List[str]:
        """
        Implementação base de busca com variações.
        Pode ser sobrescrita por scrapers que precisam de lógica específica.
        
        Args:
            query: Termo de busca
            
        Returns:
            Lista de URLs de páginas de torrents encontradas
        """
        from urllib.parse import urljoin, quote
        from utils.text.constants import STOP_WORDS
        
        links = []
        seen_urls = set()  # Para evitar duplicatas entre variações
        variations = [query]
        
        # Remove stop words
        words = [w for w in query.split() if w.lower() not in STOP_WORDS]
        if words and ' '.join(words) != query:
            variations.append(' '.join(words))
        
        # Primeira palavra (apenas se não for stop word)
        # IMPORTANTE: Para queries com 3+ palavras, NÃO usa apenas a primeira palavra
        # pois isso gera muitos resultados irrelevantes (ex: "great flood 2025" → busca só "great")
        query_words = query.split()
        if len(query_words) > 1 and len(query_words) < 3:
            # Apenas para queries de 2 palavras, permite buscar só a primeira
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])
        
        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue
            
            # Extrai links usando o método específico do scraper
            page_links = self._extract_search_results(doc)
            for href in page_links:
                absolute_url = urljoin(self.base_url, href)
                # Verifica duplicatas antes de adicionar
                if absolute_url not in seen_urls:
                    links.append(absolute_url)
                    seen_urls.add(absolute_url)
        
        return links
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        """
        Extrai links dos resultados de busca.
        Deve ser sobrescrito por cada scraper com seus seletores específicos.
        
        Args:
            doc: BeautifulSoup document da página de resultados
            
        Returns:
            Lista de hrefs (URLs relativas ou absolutas)
        """
        return []
    
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
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        """
        Obtém torrents de uma página específica
        
        Args:
            page: Número da página
            max_items: Limite máximo de itens. Se None ou 0, não há limite (ilimitado)
            is_test: Flag indicando se é uma busca sem query (teste do Prowlarr) - quando True, não usa cache HTML
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
            logger.debug(f"Link resolver error: {type(e).__name__}")
        
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
            title = torrent.get('title_processed', '')
            if not title or len(title.strip()) < 10:
                info_hash = torrent.get('info_hash')
                if info_hash:
                    # Verifica cross_data primeiro (evita consulta desnecessária ao metadata)
                    try:
                        from utils.text.cross_data import get_cross_data_from_redis
                        cross_data = get_cross_data_from_redis(info_hash)
                        if cross_data and cross_data.get('magnet_processed'):
                            # Se já temos magnet_processed no cross_data, não precisa buscar metadata
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
                                torrent['title_processed'] = name
                    except Exception:
                        pass
    
    def _fetch_metadata_batch(self, torrents: List[Dict]) -> None:
        # Busca metadata para todos os torrents de uma vez com semáforo global
        from magnet.metadata import fetch_metadata_from_itorrents
        from magnet.parser import MagnetParser
        from utils.concurrency.metadata_semaphore import metadata_slot
        
        torrents_to_fetch = [
            t for t in torrents
            if not t.get('_metadata_fetched') and t.get('magnet_link')
        ]
        
        if not torrents_to_fetch:
            return
        
        def fetch_metadata_for_torrent(torrent: Dict) -> tuple:
            # Obtém info_hash ANTES de adquirir slot (economiza slots)
            info_hash = torrent.get('info_hash')
            if not info_hash:
                try:
                    from magnet.parser import MagnetParser
                    magnet_data = MagnetParser.parse(torrent.get('magnet_link'))
                    info_hash = magnet_data.get('info_hash')
                except Exception:
                    return (torrent, None)
            
            if not info_hash:
                return (torrent, None)
                
            # Verifica cross_data ANTES de adquirir slot (economiza slots)
            try:
                from utils.text.cross_data import get_cross_data_from_redis
                cross_data = get_cross_data_from_redis(info_hash)
                if cross_data:
                    has_release_title = cross_data.get('magnet_processed')
                    has_size = cross_data.get('size')
                    # Se já temos magnet_processed E size no cross_data, pode pular metadata
                    if has_release_title and has_size:
                        return (torrent, None)
            except Exception:
                pass
            
            # Verifica cache de metadata ANTES de adquirir slot (economiza slots)
            try:
                from cache.metadata_cache import MetadataCache
                metadata_cache = MetadataCache()
                cached_metadata = metadata_cache.get(info_hash.lower())
                if cached_metadata:
                    return (torrent, cached_metadata)
            except Exception:
                pass
            
            # Só adquire slot se realmente precisa buscar metadata
            from utils.concurrency.metadata_semaphore import metadata_slot
            with metadata_slot():
                try:
                    from magnet.metadata import fetch_metadata_from_itorrents
                    metadata = fetch_metadata_from_itorrents(info_hash)
                    return (torrent, metadata)
                except Exception:
                    return (torrent, None)
        
        if len(torrents_to_fetch) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            # Limita workers locais, mas o semáforo global controla requisições simultâneas
            # Aumentado de 8 para 16 para permitir mais paralelismo (o semáforo global limita a 64)
            max_workers = min(16, len(torrents_to_fetch))
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_torrent = {
                    executor.submit(fetch_metadata_for_torrent, t): t
                    for t in torrents_to_fetch
                }
                
                for future in as_completed(future_to_torrent):
                    try:
                        torrent, metadata = future.result(timeout=30)  # Aumentado de 10s para 30s
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
                        from utils.text.utils import format_bytes
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
        # Aplica fallback para obter data: 1) Metadata API, 2) Campo "Lançamento", 3) Data atual
        from datetime import datetime
        
        for torrent in torrents:
            # Só aplica fallback se date estiver vazio
            current_date = torrent.get('date', '')
            if current_date:
                continue  # Já tem data, não precisa de fallback
            
            # Tentativa 1: Metadata API (se habilitado)
            if not skip_metadata:
                magnet_link = torrent.get('magnet_link')
                if magnet_link:
                    # Obtém info_hash
                    info_hash = torrent.get('info_hash')
                    if not info_hash:
                        try:
                            magnet_data = MagnetParser.parse(magnet_link)
                            info_hash = magnet_data.get('info_hash')
                        except Exception:
                            pass
                    
                    if info_hash:
                        try:
                            metadata = torrent.get('_metadata')
                            if not metadata:
                                from magnet.metadata import fetch_metadata_from_itorrents
                                metadata = fetch_metadata_from_itorrents(info_hash)
                            
                            if metadata and metadata.get('creation_date'):
                                creation_timestamp = metadata['creation_date']
                                try:
                                    creation_date = datetime.fromtimestamp(creation_timestamp)
                                    # Formato ISO 8601 com Z (Prowlarr espera: YYYY-MM-DDTHH:MM:SSZ)
                                    torrent['date'] = creation_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                                    continue  # Encontrou no metadata, não precisa de fallback final
                                except (ValueError, OSError):
                                    pass
                        except Exception:
                            pass
            
            # Tentativa 2: Campo "Lançamento" (extrai ano e usa 31/12/YYYY)
            # Tenta buscar o documento HTML novamente usando details (URL)
            details_url = torrent.get('details', '')
            if details_url:
                try:
                    doc = self.get_document(details_url, self.base_url)
                    if doc:
                        from utils.parsing.date_extraction import extract_release_year_date_from_page
                        release_year_date = extract_release_year_date_from_page(doc, self.SCRAPER_TYPE)
                        if release_year_date:
                            # Formato ISO 8601 com Z (Prowlarr espera: YYYY-MM-DDTHH:MM:SSZ)
                            torrent['date'] = release_year_date.strftime('%Y-%m-%dT%H:%M:%SZ')
                            continue  # Encontrou no campo "Lançamento", não precisa de fallback final
                except Exception:
                    pass  # Se falhar, continua para fallback final
            
            # Tentativa 3: Fallback final - Data atual (formato ISO 8601 com Z)
            torrent['date'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')

    def _attach_peers(self, torrents: List[Dict]) -> None:
        if not self.tracker_service:
            return
        
        # Primeiro, tenta buscar dados de tracker do cross-data
        from utils.text.cross_data import get_cross_data_from_redis, save_cross_data_to_redis
        
        # Obtém nome do scraper para logs
        scraper_name = None
        if hasattr(self, 'SCRAPER_TYPE'):
            scraper_type = getattr(self, 'SCRAPER_TYPE', '')
            if scraper_type:
                from scraper import available_scraper_types
                types_info = available_scraper_types()
                normalized_type = scraper_type.lower().strip()
                if normalized_type in types_info:
                    scraper_name = types_info[normalized_type].get('display_name', scraper_type)
                else:
                    scraper_name = getattr(self, 'DISPLAY_NAME', '') or scraper_type
        
        infohash_map: Dict[str, List[str]] = {}
        for torrent in torrents:
            info_hash = (torrent.get('info_hash') or '').lower()
            if not info_hash or len(info_hash) != 40:
                continue
            if (torrent.get('seed_count') or 0) > 0 or (torrent.get('leech_count') or 0) > 0:
                continue
            
            # Monta identificação para o log
            log_parts = []
            if scraper_name:
                log_parts.append(f"[{scraper_name}]")
            title = torrent.get('title_processed', '')
            if title:
                title_preview = title[:120] if len(title) > 120 else title
                log_parts.append(title_preview)
            log_parts.append(f"(hash: {info_hash})")
            log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
            
            # Tenta buscar do cross-data primeiro
            cross_data = get_cross_data_from_redis(info_hash)
            if cross_data:
                tracker_seed = cross_data.get('tracker_seed')
                tracker_leech = cross_data.get('tracker_leech')
                # Se ambos estão presentes e não são ambos 0, usa do cross-data para evitar scrape desnecessário
                if tracker_seed is not None and tracker_leech is not None:
                    # Se ambos são 0, prossegue para fazer scrape ao invés de usar os valores
                    if not (tracker_seed == 0 and tracker_leech == 0):
                        torrent['seed_count'] = tracker_seed
                        torrent['leech_count'] = tracker_leech
                        # Log removido - hits do Redis são muito comuns
                        continue
                    else:
                        # Ambos são 0, não usa e prossegue para scrape
                        logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
                else:
                    # Não tem ambos valores, prossegue para scrape
                    logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
            else:
                # Não encontrou no cross-data, prossegue para scrape
                logger.debug(f"[Tracker] Buscando tracker: {log_id} → Não encontrado")
            
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
            saved_to_redis = False
            try:
                cross_data_to_save = {
                    'tracker_seed': seed,
                    'tracker_leech': leech
                }
                save_cross_data_to_redis(info_hash, cross_data_to_save)
                saved_to_redis = True
            except Exception as e:
                # Log silencioso - não queremos interromper o processamento por erro no cross-data
                logger.debug(f"Cross-data save error: {info_hash[:16]}")
            
            # Log com resultado da busca e salvamento
            log_parts = []
            if scraper_name:
                log_parts.append(f"[{scraper_name}]")
            title = torrent.get('title_processed', '')
            if title:
                title_preview = title[:120] if len(title) > 120 else title
                log_parts.append(title_preview)
            log_parts.append(f"(hash: {info_hash})")
            log_id = " ".join(log_parts) if log_parts else f"hash: {info_hash}"
            
            if saved_to_redis:
                logger.debug(f"[Tracker] Buscando tracker: {log_id} → Salvo no Redis")
            else:
                logger.debug(f"[Tracker] Buscando tracker: {log_id} → Scrape realizado (erro ao salvar no Redis)")

