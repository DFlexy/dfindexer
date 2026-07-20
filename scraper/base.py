# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

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
from utils.http.flaresolverr import FlareSolverrClient
from utils.http.proxy import get_proxy_dict, is_proxy_local

logger = logging.getLogger(__name__)

_request_cache = threading.local()
# HTML da última fetch por thread (evita race no processamento paralelo de páginas)
_thread_fetched_html = threading.local()

_url_locks = {}
_url_locks_lock = threading.Lock()
_MAX_URL_LOCKS = 500
_url_fetching = set()
_url_fetching_lock = threading.Lock()

def _get_url_lock(url: str):
    with _url_locks_lock:
        if len(_url_locks) > _MAX_URL_LOCKS:
            keys_to_remove = list(_url_locks.keys())[:len(_url_locks) // 2]
            for key in keys_to_remove:
                del _url_locks[key]
        if url not in _url_locks:
            _url_locks[url] = threading.Lock()
        return _url_locks[url]

def cleanup_url_state():
    """Limpa estado global de URLs (locks e fetching set). Chamar entre requisições."""
    with _url_locks_lock:
        _url_locks.clear()
    with _url_fetching_lock:
        _url_fetching.clear()

class BaseScraper(ABC):
    SCRAPER_TYPE: str = ''
    DEFAULT_BASE_URL: str = ''
    DISPLAY_NAME: str = ''
    USE_FLARESOLVERR_DEFAULT: bool = False
    
    def __init__(self, base_url: Optional[str] = None, use_flaresolverr: bool = False):
        env_url = ''
        if self.SCRAPER_TYPE:
            import os
            env_url = (os.getenv(f'SCRAPER_URL_{self.SCRAPER_TYPE.upper()}') or '').strip()
        resolved_url = (base_url or env_url or self.DEFAULT_BASE_URL or '').strip()
        if resolved_url and not resolved_url.endswith('/'):
            resolved_url = f"{resolved_url}/"
        if not resolved_url:
            raise ValueError(
                f"{self.__class__.__name__} requer DEFAULT_BASE_URL definido ou um base_url explícito"
            )
        self.base_url = resolved_url
        self.redis = get_redis_client()
        
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=Config.HTTP_POOL_CONNECTIONS,
            pool_maxsize=Config.HTTP_POOL_MAXSIZE,
            max_retries=Config.HTTP_RETRY_MAX_ATTEMPTS,
            pool_block=False
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        proxy_dict = get_proxy_dict()
        if proxy_dict:
            self.session.proxies.update(proxy_dict)
        self._skip_metadata = False
        self._is_test = False
        self._closed = False
        self._last_fetched_html: Optional[str] = None
        self._active_search_query: str = ''
        
        self._cache_stats = {
            'html': {'hits': 0, 'misses': 0},
            'metadata': {'hits': 0, 'misses': 0},
            'trackers': {'hits': 0, 'misses': 0}
        }
        
        self.use_flaresolverr = use_flaresolverr and Config.FLARESOLVERR_ADDRESS is not None
        self.flaresolverr_client: Optional[FlareSolverrClient] = None
        
        if use_flaresolverr and Config.FLARESOLVERR_ADDRESS is None:
            logger.warning("[[ FlareSolverr Não Conectado ]] - FLARESOLVERR_ADDRESS não configurado")
            self.use_flaresolverr = False
        
        if self.use_flaresolverr:
            try:
                self.flaresolverr_client = FlareSolverrClient(Config.FLARESOLVERR_ADDRESS)
                try:
                    _fs_proxy = get_proxy_dict() if not is_proxy_local() else None
                    test_response = requests.get(f"{Config.FLARESOLVERR_ADDRESS.rstrip('/')}/v1", timeout=2, proxies=_fs_proxy)
                    if test_response.status_code not in (200, 404, 405):
                        raise Exception(f"FlareSolverr retornou status {test_response.status_code}")
                except requests.exceptions.ConnectionError:
                    raise Exception("Connection refused")
                except requests.exceptions.Timeout:
                    raise Exception("Connection timeout")
                except Exception as test_e:
                    error_type = type(test_e).__name__
                    error_msg = str(test_e).split('\n')[0][:100] if str(test_e) else str(test_e)
                    logger.warning(f"[[ FlareSolverr Não Conectado ]] - {error_type}: {error_msg}")
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
                logger.warning(f"[[ FlareSolverr Não Conectado ]] - {error_type}: {error_msg}")
                self.use_flaresolverr = False
    
    def close(self):
        """Libera recursos do scraper (session HTTP, etc)."""
        if not self._closed:
            self._closed = True
            try:
                self.session.close()
            except Exception:
                pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
    
    def _soup_from_html(self, html_content) -> Optional[BeautifulSoup]:
        """Faz parse do HTML e armazena o texto para consumo por scrapers (ex.: Starck data-u)."""
        if html_content is None:
            return None
        if isinstance(html_content, bytes):
            html_str = html_content.decode('utf-8', errors='ignore')
        else:
            html_str = str(html_content)
        _thread_fetched_html.html = html_str
        self._last_fetched_html = html_str
        try:
            return BeautifulSoup(html_content, 'lxml')
        except Exception:
            return BeautifulSoup(html_content, 'html.parser')

    def _get_fetched_html(self) -> str:
        """HTML da última get_document nesta thread (seguro com process_links_parallel)."""
        thread_html = getattr(_thread_fetched_html, 'html', None)
        if thread_html:
            return thread_html
        return self._last_fetched_html or ''
    
    def get_document(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        self._last_fetched_html = None
        _thread_fetched_html.html = None
        from cache.http_cache import get_http_cache
        http_cache = get_http_cache()
        
        if not self._is_test:
            cached_local = http_cache.get(url)
            if cached_local:
                self._cache_stats['html']['hits'] += 1
                return self._soup_from_html(cached_local)
        
        if self.redis and not self._is_test:
            try:
                cache_key = html_long_key(url)
                cached = self.redis.get(cache_key)
                if cached:
                    self._cache_stats['html']['hits'] += 1
                    return self._soup_from_html(cached)
            except (AttributeError, TypeError) as e:
                logger.debug(f"Redis cache error (long): {type(e).__name__}")
            except Exception as e:
                logger.debug(f"Unexpected Redis error (long): {type(e).__name__}")
        
        if self.redis and not self._is_test:
            try:
                short_cache_key = html_short_key(url)
                cached = self.redis.get(short_cache_key)
                if cached:
                    self._cache_stats['html']['hits'] += 1
                    return self._soup_from_html(cached)
            except (AttributeError, TypeError) as e:
                logger.debug(f"Redis cache error (short): {type(e).__name__}")
            except Exception as e:
                logger.debug(f"Unexpected Redis error (short): {type(e).__name__}")
        
        url_lock = _get_url_lock(url)
        with url_lock:
            if self.redis and not self._is_test:
                try:
                    cache_key = html_long_key(url)
                    cached = self.redis.get(cache_key)
                    if cached:
                        self._cache_stats['html']['hits'] += 1
                        return self._soup_from_html(cached)
                except Exception:
                    pass
            
            if self.redis and not self._is_test:
                try:
                    short_cache_key = html_short_key(url)
                    cached = self.redis.get(short_cache_key)
                    if cached:
                        self._cache_stats['html']['hits'] += 1
                        return self._soup_from_html(cached)
                except Exception:
                    pass
            
            is_fetching = False
            with _url_fetching_lock:
                if url in _url_fetching:
                    is_fetching = True
                else:
                    _url_fetching.add(url)
            
            if is_fetching:
                import time
                for _ in range(20):
                    time.sleep(0.1)
                    if self.redis and not self._is_test:
                        try:
                            cache_key = html_long_key(url)
                            cached = self.redis.get(cache_key)
                            if cached:
                                self._cache_stats['html']['hits'] += 1
                                return self._soup_from_html(cached)
                        except Exception:
                            pass
        
        _added_to_fetching = not is_fetching
        try:
            return self._fetch_document(url, referer)
        finally:
            if _added_to_fetching:
                with _url_fetching_lock:
                    _url_fetching.discard(url)
    
    def _fetch_document(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        self._cache_stats['html']['misses'] += 1
        
        html_content = None
        use_flaresolverr_for_this_url = (
            self.use_flaresolverr and 
            self.flaresolverr_client and 
            "%3A" not in url and 
            "%3a" not in url.lower()
        )
        
        if self.use_flaresolverr and not use_flaresolverr_for_this_url:
            if not self.flaresolverr_client:
                logger.debug(f"FlareSolverr habilitado mas cliente não disponível para {url[:50]}...")
            elif "%3A" in url or "%3a" in url.lower():
                logger.debug(f"FlareSolverr pulado: URL contém %3A para {url[:50]}...")
        
        if use_flaresolverr_for_this_url:
            try:
                from utils.http.flaresolverr import _get_flaresolverr_lock
                flaresolverr_lock = _get_flaresolverr_lock(self.base_url)
                
                with flaresolverr_lock:
                    session_id = self.flaresolverr_client.get_or_create_session(
                        self.base_url,
                    )
                    if session_id:
                        pass
                    else:
                        logger.warning(f"FlareSolverr: não foi possível obter/criar sessão para {url[:50]}... - tentando requisição direta (pode resultar em 403)")
                    if session_id:
                        html_content = self.flaresolverr_client.solve(
                            url,
                            session_id,
                            referer if referer else self.base_url,
                            self.base_url,
                        )
                    if html_content:
                        html_str = html_content.decode('utf-8', errors='ignore') if isinstance(html_content, bytes) else str(html_content)
                        url_slug = url.rstrip('/').split('/')[-1]
                        url_in_html = url in html_str or url_slug in html_str
                        
                        if not url_in_html:
                            logger.warning(f"FlareSolverr: HTML retornado não corresponde à URL! URL: {url[:80]}... | HTML size: {len(html_str)} bytes")
                            html_content = None
                        else:
                            logger.debug(f"FlareSolverr: sucesso para {url[:50]}... ({len(html_content)} bytes)")
                            if not self._is_test:
                                try:
                                    from cache.http_cache import get_http_cache
                                    http_cache = get_http_cache()
                                    http_cache.set(url, html_content)
                                except Exception:
                                    pass
                            
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
                                except Exception:
                                    pass
                            
                            return self._soup_from_html(html_content)
                    else:
                        from cache.redis_keys import flaresolverr_failure_key
                        failure_key = flaresolverr_failure_key(url)
                        should_retry = True
                        
                        if self.redis and not self._is_test:
                            try:
                                if self.redis.exists(failure_key):
                                    should_retry = False
                                else:
                                    self.redis.setex(failure_key, 300, "1")
                            except Exception:
                                pass
                        elif not self.redis and not self._is_test:
                            if not hasattr(_request_cache, 'flaresolverr_failures'):
                                _request_cache.flaresolverr_failures = {}
                            
                            expire_at = _request_cache.flaresolverr_failures.get(failure_key, 0)
                            if time.time() < expire_at:
                                should_retry = False
                            else:
                                _request_cache.flaresolverr_failures[failure_key] = time.time() + 300
                        
                        if "%3A" in url or "%3a" in url.lower():
                            should_retry = False
                        
                        if should_retry:
                            new_session_id = self.flaresolverr_client.get_or_create_session(
                                self.base_url,
                            )
                            if new_session_id:
                                if new_session_id != session_id:
                                    logger.debug(f"FlareSolverr: usando nova sessão (anterior: {session_id[:20]}..., nova: {new_session_id[:20]}...)")
                                
                                html_content = self.flaresolverr_client.solve(
                                    url,
                                    new_session_id,
                                    referer if referer else self.base_url,
                                    self.base_url,
                                )
                                if html_content:
                                    html_str = html_content.decode('utf-8', errors='ignore') if isinstance(html_content, bytes) else str(html_content)
                                    url_slug = url.rstrip('/').split('/')[-1]
                                    url_in_html = url in html_str or url_slug in html_str
                                    
                                    if not url_in_html:
                                        logger.warning(f"FlareSolverr retry: HTML retornado não corresponde à URL! URL: {url[:80]}... | HTML size: {len(html_str)} bytes")
                                        html_content = None
                                    else:
                                        if not self._is_test:
                                            try:
                                                from cache.http_cache import get_http_cache
                                                http_cache = get_http_cache()
                                                http_cache.set(url, html_content)
                                            except Exception:
                                                pass
                                        
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
                                            except Exception:
                                                pass
                                        
                                        return self._soup_from_html(html_content)
                                else:
                                    if self.redis and not self._is_test:
                                        try:
                                            self.redis.setex(failure_key, 300, "1")
                                        except Exception:
                                            pass
                                    elif not self.redis and not self._is_test:
                                        if not hasattr(_request_cache, 'flaresolverr_failures'):
                                            _request_cache.flaresolverr_failures = {}
                                        _request_cache.flaresolverr_failures[failure_key] = time.time() + 300
            except Exception as e:
                logger.debug(f"FlareSolverr error: {type(e).__name__} - tentando requisição direta")
        
        if use_flaresolverr_for_this_url and not html_content:
            from cache.redis_keys import flaresolverr_failure_key
            failure_key = flaresolverr_failure_key(url)
            should_try_flaresolverr = True
            
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
            
            if should_try_flaresolverr and self.flaresolverr_client:
                try:
                    from utils.http.flaresolverr import _get_flaresolverr_lock
                    flaresolverr_lock = _get_flaresolverr_lock(self.base_url)
                    
                    with flaresolverr_lock:
                        session_id = self.flaresolverr_client.get_or_create_session(
                            self.base_url,
                        )
                        if session_id:
                            html_content = self.flaresolverr_client.solve(
                                url,
                                session_id,
                                referer if referer else self.base_url,
                                self.base_url,
                            )
                        if html_content:
                            html_str = html_content.decode('utf-8', errors='ignore') if isinstance(html_content, bytes) else str(html_content)
                            url_slug = url.rstrip('/').split('/')[-1]
                            url_in_html = url in html_str or url_slug in html_str
                            
                            if not url_in_html:
                                logger.warning(f"FlareSolverr retry (cache expirado): HTML retornado não corresponde à URL! URL: {url[:80]}... | HTML size: {len(html_str)} bytes")
                                html_content = None
                            else:
                                if not self._is_test:
                                    try:
                                        from cache.http_cache import get_http_cache
                                        http_cache = get_http_cache()
                                        http_cache.set(url, html_content)
                                    except Exception:
                                        pass
                                
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
                                    except Exception:
                                        pass
                                
                                return self._soup_from_html(html_content)
                        else:
                            if self.redis and not self._is_test:
                                try:
                                    self.redis.setex(failure_key, 300, "1")
                                except Exception:
                                    pass
                            elif not self.redis and not self._is_test:
                                if not hasattr(_request_cache, 'flaresolverr_failures'):
                                    _request_cache.flaresolverr_failures = {}
                                _request_cache.flaresolverr_failures[failure_key] = time.time() + 300
                except Exception as e:
                    logger.debug(f"FlareSolverr retry error: {type(e).__name__} - tentando requisição direta")
        
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
            
            if not self._is_test:
                try:
                    from cache.http_cache import get_http_cache
                    http_cache = get_http_cache()
                    http_cache.set(url, html_content)
                except Exception:
                    pass
            
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
                except Exception:
                    pass
            
            return self._soup_from_html(html_content)
        
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
            
            if error_type == 'HTTPError' and ('500' in error_msg or '502' in error_msg or '503' in error_msg or '520' in error_msg or '521' in error_msg or '522' in error_msg or '523' in error_msg or '524' in error_msg):
                logger.warning(f"Document error: {error_type} - {error_msg}")
            else:
                url_preview = url[:50] if url else 'N/A'
                if url and url not in error_msg:
                    logger.error(f"Document error: {error_type} - {error_msg} (url: {url_preview}...)")
                else:
                    logger.error(f"Document error: {error_type} - {error_msg}")
            
            return None
    
    @abstractmethod
    def search(
        self,
        query: str,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        skip_trackers: bool = False,
        skip_metadata: bool = False,
    ) -> List[Dict]:
        pass
    
    def _prepare_page_flags(self, max_items: Optional[int] = None, is_test: bool = False) -> Tuple[bool, bool, bool]:
        """Prepara flags para processamento de página baseado em max_items e configurações"""
        is_using_default_limit = max_items is None
        skip_metadata = False
        skip_trackers = False
        self._skip_metadata = skip_metadata
        self._is_test = is_test or is_using_default_limit
        
        return is_using_default_limit, skip_metadata, skip_trackers
    
    def _extract_links_from_page(self, doc: BeautifulSoup) -> List[str]:
        return []
    
    def _default_get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        """Implementação padrão de get_page que pode ser reutilizada pelos scrapers"""
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
            links = limit_list(links, effective_max)
            
            all_torrents = process_links_parallel(
                links,
                self._get_torrents_from_page,
                None,
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
    
    def _search_variations(self, query: str) -> List[str]:
        """Implementação base de busca com variações"""
        from urllib.parse import urljoin, quote
        from utils.text.constants import STOP_WORDS
        from utils.text.query import strip_stop_words_keep_season

        links = []
        seen_urls = set()
        variations = [query]

        stripped = strip_stop_words_keep_season(query)
        if stripped and stripped != query:
            variations.append(stripped)

        query_words = query.split()

        if len(query_words) >= 2 and query_words[-1].isdigit() and len(query_words[-1]) == 4 and query_words[-1][:2] in ('19', '20'):
            without_year = ' '.join(query_words[:-1])
            if without_year not in variations:
                variations.append(without_year)

        if len(query_words) > 1 and len(query_words) < 3:
            first_word = query_words[0].lower()
            if first_word not in STOP_WORDS:
                variations.append(query_words[0])

        for variation in variations:
            search_url = f"{self.base_url}{self.search_url}{quote(variation)}"
            doc = self.get_document(search_url, self.base_url)
            if not doc:
                continue

            page_links = self._extract_search_results(doc)
            page_links = self._filter_links_by_result_titles(doc, page_links, variation)
            for href in page_links:
                absolute_url = urljoin(self.base_url, href)
                if absolute_url not in seen_urls:
                    links.append(absolute_url)
                    seen_urls.add(absolute_url)

        return links

    def _normalize_search_result_url(self, href: str) -> str:
        from urllib.parse import urljoin
        if not href:
            return ''
        absolute = urljoin(self.base_url, href)
        absolute = absolute.split('#', 1)[0]
        return absolute.rstrip('/').lower()

    def _collect_search_result_titles(self, doc: BeautifulSoup) -> Dict[str, str]:
        """Coleta títulos exibidos nos cards de busca para validar query sem olhar sinopse."""
        title_by_url: Dict[str, str] = {}
        article_selectors = [
            'article.post',
            'article',
            '.post',
            '.item',
            '.result',
        ]
        link_selectors = [
            'h1.entry-title a',
            'h2.entry-title a',
            'h3.entry-title a',
            'header.entry-header a',
            'h1 a',
            'h2 a',
            'h3 a',
        ]

        for article_sel in article_selectors:
            for article in doc.select(article_sel):
                link_elem = None
                for link_sel in link_selectors:
                    link_elem = article.select_one(link_sel)
                    if link_elem:
                        break
                if not link_elem:
                    continue
                href = (link_elem.get('href') or '').strip()
                title_text = link_elem.get_text(strip=True)
                normalized = self._normalize_search_result_url(href)
                if normalized and title_text:
                    title_by_url[normalized] = title_text

        return title_by_url

    def _filter_links_by_result_titles(self, doc: BeautifulSoup, links: List[str], query: str) -> List[str]:
        """Filtra links de busca usando só o título do card de resultado."""
        from utils.text.query import check_query_match

        if not links or not query or not query.strip():
            return links

        title_by_url = self._collect_search_result_titles(doc)
        if not title_by_url:
            return links

        filtered: List[str] = []
        for href in links:
            normalized = self._normalize_search_result_url(href)
            title_text = title_by_url.get(normalized)
            # Se não achou título para o link, mantém para evitar falso negativo agressivo.
            if not title_text:
                filtered.append(href)
                continue
            if check_query_match(query, title_text, '', ''):
                filtered.append(href)

        return filtered
    
    def _extract_search_results(self, doc: BeautifulSoup) -> List[str]:
        return []
    
    def _should_skip_page_by_query(
        self,
        page_title: str = '',
        original_title: str = '',
        title_translated: str = '',
        link: str = '',
    ) -> bool:
        """Ignora a página durante busca quando títulos não batem com a query ativa."""
        query = self._active_search_query or ''
        if not query.strip():
            return False

        from utils.text.query import check_query_match

        if check_query_match(
            query,
            page_title or '',
            original_title or '',
            title_translated or '',
        ):
            return False

        from utils.concurrency.scraper_helpers import mark_page_skipped_by_query
        mark_page_skipped_by_query()
        return True

    def _filter_search_links_by_query_year(self, query: str, links: List[str]) -> List[str]:
        """Filtro de ano só por link (slug), centralizado para todos os scrapers."""
        from app.config import Config
        from utils.text.query import extract_query_year, filter_urls_by_query_year

        links_before = len(links)
        filtered = filter_urls_by_query_year(
            query,
            links,
            tolerance=Config.QUERY_YEAR_LINK_TOLERANCE,
        )
        scraper_name = getattr(self, 'DISPLAY_NAME', '') or getattr(self, 'SCRAPER_TYPE', 'UNKNOWN')
        if links_before != len(filtered):
            query_year = extract_query_year(query)
            tol = Config.QUERY_YEAR_LINK_TOLERANCE
            logger.debug(
                f"[{scraper_name}] Filtro por ano no link ({query_year} ±{tol}): "
                f"{links_before} → {len(filtered)} páginas"
            )
        return filtered

    def _filter_search_links_by_query_season(self, query: str, links: List[str]) -> List[str]:
        """Filtro de temporada só por link (slug), antes de abrir páginas."""
        from utils.text.query import extract_query_season, filter_urls_by_query_season

        links_before = len(links)
        filtered = filter_urls_by_query_season(query, links)
        scraper_name = getattr(self, 'DISPLAY_NAME', '') or getattr(self, 'SCRAPER_TYPE', 'UNKNOWN')
        if links_before != len(filtered):
            season = extract_query_season(query)
            logger.debug(
                f"[{scraper_name}] Filtro por temporada no link (S{season}): "
                f"{links_before} → {len(filtered)} páginas"
            )
        return filtered

    def _default_search(
        self,
        query: str,
        filter_func: Optional[Callable[[Dict], bool]] = None,
        skip_trackers: bool = False,
        skip_metadata: bool = False,
    ) -> List[Dict]:
        from utils.concurrency.scraper_helpers import normalize_query_for_flaresolverr
        query = normalize_query_for_flaresolverr(query, self.use_flaresolverr)
        self._active_search_query = query.strip() if query else ''
        try:
            links = self._search_variations(query)
            links = self._filter_search_links_by_query_year(query, links)
            links = self._filter_search_links_by_query_season(query, links)

            scraper_name = getattr(self, 'DISPLAY_NAME', '') or getattr(self, 'SCRAPER_TYPE', 'UNKNOWN')
            if not links:
                logger.debug(f"[{scraper_name}] Nenhuma página encontrada para a query: '{query}'")

            from utils.concurrency.scraper_helpers import process_links_parallel
            all_torrents = process_links_parallel(
                links,
                self._get_torrents_from_page,
                None,
                scraper_name=getattr(self, 'DISPLAY_NAME', '') or getattr(self, 'SCRAPER_TYPE', None),
                use_flaresolverr=self.use_flaresolverr,
            )

            return self.enrich_torrents(
                all_torrents,
                filter_func=filter_func,
                skip_trackers=skip_trackers,
                skip_metadata=skip_metadata,
            )
        finally:
            self._active_search_query = ''
    
    @abstractmethod
    def get_page(self, page: str = '1', max_items: Optional[int] = None, is_test: bool = False) -> List[Dict]:
        pass
    
    @abstractmethod
    def _get_torrents_from_page(self, link: str) -> List[Dict]:
        pass

    def _log_structure_miss(self, url: str, what: str) -> None:
        """Loga possível mudança de estrutura do site: página carregou mas um seletor crítico falhou.

        Primeira ocorrência por seletor sai como WARNING (visível em produção);
        repetições saem como DEBUG para não inundar o log.
        """
        scraper_name = self.DISPLAY_NAME or self.SCRAPER_TYPE or self.__class__.__name__
        if not hasattr(self, '_structure_miss_counts'):
            self._structure_miss_counts = {}
        self._structure_miss_counts[what] = self._structure_miss_counts.get(what, 0) + 1
        log = logger.warning if self._structure_miss_counts[what] == 1 else logger.debug
        log(
            f"[{scraper_name}] Estrutura inesperada: '{what}' não encontrado em "
            f"{url[:80]} (possível mudança no layout do site)"
        )

    def _resolve_link(self, href: str) -> Optional[str]:
        """Resolve automaticamente qualquer link (magnet direto ou protegido)"""
        if not href:
            return None

        href = html.unescape(href.strip())
        
        if href.startswith('magnet:'):
            href = href.replace('&amp;', '&').replace('&#038;', '&')
            return html.unescape(href)
        
        try:
            from utils.parsing.link_resolver import is_protected_link, resolve_protected_link
            if is_protected_link(href):
                resolved = resolve_protected_link(href, self.session, self.base_url, redis=self.redis)
                return resolved
        except Exception as e:
            logger.debug(f"Link resolver error: {type(e).__name__}")
        
        return None
    
    def enrich_torrents(self, torrents: List[Dict], skip_metadata: bool = False, skip_trackers: bool = False, filter_func: Optional[Callable[[Dict], bool]] = None) -> List[Dict]:
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

