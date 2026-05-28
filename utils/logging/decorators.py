# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import functools
import logging
from contextlib import contextmanager
from typing import Any, Callable, Optional, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar('T')

def format_error(e: Exception, max_msg_len: int = 100) -> str:
    error_type = type(e).__name__
    error_msg = str(e).split('\n')[0][:max_msg_len] if str(e) else ''
    return f"{error_type} - {error_msg}"

def format_link_preview(link: Any, max_len: int = 50) -> str:
    link_str = str(link) if link else 'N/A'
    if link_str == 'N/A':
        return 'N/A'
    preview = link_str[:max_len]
    return f"{preview}..." if len(link_str) > max_len else link_str

@contextmanager
def log_magnet_error(magnet_link: Any, scraper_logger: Optional[logging.Logger] = None):
    log = scraper_logger or logger
    try:
        yield
    except Exception as e:
        link_preview = format_link_preview(magnet_link)
        log.error(f"Magnet error: {format_error(e)} (link: {link_preview})")
        raise

def log_on_error(
    error_prefix: str = "Error",
    include_link: bool = False,
    link_arg_name: str = "link",
    reraise: bool = True,
    default_return: Any = None
) -> Callable:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            log = logger
            if args and hasattr(args[0], '__class__'):
                module_name = args[0].__class__.__module__
                log = logging.getLogger(module_name)
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = format_error(e)
                
                if include_link:
                    link = kwargs.get(link_arg_name)
                    if link is None:
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
    
    def __init__(self, scraper_name: str, scraper_logger: Optional[logging.Logger] = None):
        self.name = scraper_name
        self.logger = scraper_logger or logging.getLogger(__name__)
        self._prefix = f"[{scraper_name}]"
    
    def info(self, message: str, *args):
        formatted = message.format(*args) if args else message
        self.logger.info(f"{self._prefix} {formatted}")
    
    def warning(self, message: str, *args):
        formatted = message.format(*args) if args else message
        self.logger.warning(f"{self._prefix} {formatted}")
    
    def error(self, message: str, *args):
        formatted = message.format(*args) if args else message
        self.logger.error(f"{self._prefix} {formatted}")
    
    def debug(self, message: str, *args):
        formatted = message.format(*args) if args else message
        self.logger.debug(f"{self._prefix} {formatted}")
    
    def error_magnet(self, magnet_link: Any, exception: Exception):
        link_preview = format_link_preview(magnet_link)
        self.logger.error(f"Magnet error: {format_error(exception)} (link: {link_preview})")
    
    def error_document(self, url: Any, exception: Exception):
        url_preview = format_link_preview(url)
        self.logger.error(f"Document error: {format_error(exception)} (url: {url_preview})")
    
    def log_links_found(self, total: int, limit: Optional[int] = None):
        if limit and limit > 0:
            self.info(f"Encontrados {total} links na página, limitando para {limit}")
        else:
            self.info(f"Encontrados {total} links na página (sem limite)")
