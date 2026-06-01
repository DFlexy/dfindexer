# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

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
