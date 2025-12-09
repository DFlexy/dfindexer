"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from utils.logging.logger import setup_logging
from utils.logging.decorators import (
    format_error,
    format_link_preview,
    log_magnet_error,
    log_on_error,
    ScraperLogContext
)

__all__ = [
    'setup_logging',
    'format_error',
    'format_link_preview',
    'log_magnet_error',
    'log_on_error',
    'ScraperLogContext'
]

