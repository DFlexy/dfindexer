"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from utils.parsing.magnet_utils import process_trackers, extract_trackers_from_magnet

__all__ = ['process_trackers', 'extract_trackers_from_magnet']

from utils.parsing.date_parser import parse_date_from_string
from utils.parsing.html_extraction import (
    extract_date_from_page,
    extract_imdb_from_page,
    extract_magnet_links,
    extract_text_from_element,
    extract_original_title_from_text
)
from utils.parsing.link_resolver import resolve_protected_link, is_protected_link, decode_ad_link
from utils.parsing.magnet_utils import process_trackers, extract_trackers_from_magnet

__all__ = [
    'parse_date_from_string',
    'extract_date_from_page',
    'extract_imdb_from_page',
    'extract_magnet_links',
    'extract_text_from_element',
    'extract_original_title_from_text',
    'resolve_protected_link',
    'is_protected_link',
    'decode_ad_link',
    'process_trackers',
    'extract_trackers_from_magnet',
]

