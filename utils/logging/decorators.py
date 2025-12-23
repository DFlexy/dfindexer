"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import functools
import logging
from contextlib import contextmanager
from typing import Any, Callable, Optional, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar('T')


def format_error(e: Exception, max_msg_len: int = 100) -> str:
    # Formata erro de forma padronizada: 'ErrorType - mensagem truncada'
    error_type = type(e).__name__
    error_msg = str(e).split('\n')[0][:max_msg_len] if str(e) else ''
    return f"{error_type} - {error_msg}"


def format_link_preview(link: Any, max_len: int = 50) -> str:
    # Formata preview de link para logs: 'link[:50]...'
    link_str = str(link) if link else 'N/A'
    if link_str == 'N/A':
        return 'N/A'
    preview = link_str[:max_len]
    return f"{preview}..." if len(link_str) > max_len else link_str


@contextmanager
def log_magnet_error(magnet_link: Any, scraper_logger: Optional[logging.Logger] = None):
    # Context manager para tratamento padronizado de erros de magnet
    log = scraper_logger or logger
    try:
        yield
    except Exception as e:
        link_preview = format_link_preview(magnet_link)
        log.error(f"Magnet error: {format_error(e)} (link: {link_preview})")
        raise  # Re-levanta para manter comportamento de continue no loop


def log_on_error(
    error_prefix: str = "Error",
    include_link: bool = False,
    link_arg_name: str = "link",
    reraise: bool = True,
    default_return: Any = None
) -> Callable:
    # Decorator para logging padronizado de erros em funções
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Obtém logger do self se disponível (métodos de classe)
            log = logger
            if args and hasattr(args[0], '__class__'):
                module_name = args[0].__class__.__module__
                log = logging.getLogger(module_name)
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = format_error(e)
                
                if include_link:
                    # Tenta obter o link dos kwargs ou args
                    link = kwargs.get(link_arg_name)
                    if link is None:
                        # Tenta obter da posição do argumento
                        import inspect
                        sig = inspect.signature(func)
                        params = list(sig.parameters.keys())
                        if link_arg_name in params:
                            idx = params.index(link_arg_name)
                            if idx < len(args):
                                link = args[idx]
                    
                    link_preview = format_link_preview(link)
                    log.error(f"{error_prefix}: {error_msg} (link: {link_preview})")
                else:
                    log.error(f"{error_prefix}: {error_msg}")
                
                if reraise:
                    raise
                return default_return
        return wrapper
    return decorator


class ScraperLogContext:
    # Classe helper para contexto de logging em scrapers
    # Centraliza prefixos e formatação de logs
    
    def __init__(self, scraper_name: str, scraper_logger: Optional[logging.Logger] = None):
        self.name = scraper_name
        self.logger = scraper_logger or logging.getLogger(__name__)
        self._prefix = f"[{scraper_name}]"
    
    def info(self, message: str, *args):
        # Log info com prefixo do scraper
        formatted = message.format(*args) if args else message
        self.logger.info(f"{self._prefix} {formatted}")
    
    def warning(self, message: str, *args):
        # Log warning com prefixo do scraper
        formatted = message.format(*args) if args else message
        self.logger.warning(f"{self._prefix} {formatted}")
    
    def error(self, message: str, *args):
        # Log error com prefixo do scraper
        formatted = message.format(*args) if args else message
        self.logger.error(f"{self._prefix} {formatted}")
    
    def debug(self, message: str, *args):
        # Log debug com prefixo do scraper
        formatted = message.format(*args) if args else message
        self.logger.debug(f"{self._prefix} {formatted}")
    
    def error_magnet(self, magnet_link: Any, exception: Exception):
        # Log de erro de magnet padronizado
        link_preview = format_link_preview(magnet_link)
        self.logger.error(f"Magnet error: {format_error(exception)} (link: {link_preview})")
    
    def error_document(self, url: Any, exception: Exception):
        # Log de erro de documento padronizado
        url_preview = format_link_preview(url)
        self.logger.error(f"Document error: {format_error(exception)} (url: {url_preview})")
    
    def log_links_found(self, total: int, limit: Optional[int] = None):
        # Log padronizado de links encontrados
        if limit and limit > 0:
            self.info(f"Encontrados {total} links na página, limitando para {limit}")
        else:
            self.info(f"Encontrados {total} links na página (sem limite)")
