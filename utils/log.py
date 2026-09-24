# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CustomFormatter(logging.Formatter):
    def format(self, record):
        fmt = '%(asctime)s %(levelname)s - %(message)s'

        formatter = logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)


def _get_log_level_from_numeric(level: int) -> int:
    level_map = {
        0: logging.DEBUG,
        1: logging.INFO,
        2: logging.WARNING,
        3: logging.ERROR
    }
    return level_map.get(level, logging.INFO)


def print_support_banner(log_format: str = 'console') -> None:
    if log_format != 'console':
        return
    _ensure_utf8_output()
    lines = [
        '',
        '======================================================================',
        '                 💖 Apoie este projeto',
        '======================================================================',
        '',
        '  Este projeto e 100% independente e open-source.',
        '  💜 Seu apoio mantem o desenvolvimento ativo.',
        '',
        '  >> APOIAR ESTE PROJETO:',
        '  https://donate.stripe.com/3cI3cvehCfd18bxbPoco000',
        '',
        '======================================================================',
        '',
    ]
    for line in lines:
        print(line, file=sys.stdout)
    sys.stdout.flush()


def _ensure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding='utf-8', errors='replace')
        except (ValueError, OSError):
            pass


def setup_logging(log_level: int, log_format: str = 'console'):
    _ensure_utf8_output()
    python_log_level = _get_log_level_from_numeric(log_level)

    if log_format == 'json':
        formatter = logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        formatter = CustomFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(python_log_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(python_log_level)
    root_logger.handlers = []
    root_logger.addHandler(handler)

    tracker_logger = logging.getLogger('tracker.list_provider')
    tracker_logger.handlers = []
    tracker_logger.setLevel(python_log_level)

    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.ERROR)

    logging.getLogger('asyncio').setLevel(logging.WARNING)

    if log_level >= 2:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)


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


__all__ = [
    'setup_logging',
    'print_support_banner',
    'format_error',
    'format_link_preview',
    'ScraperLogContext',
]
