"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from utils.text.constants import STOP_WORDS, RELEASE_CLEAN_REGEX
from utils.text.cleaning import remove_accents, clean_title
from utils.text.storage import get_metadata_name
from utils.text.title_builder import prepare_release_title, create_standardized_title
from utils.text.utils import find_year_from_text, find_sizes_from_text, format_bytes
from utils.text.query import check_query_match
from utils.text.cross_data import (
    get_cross_data_from_redis,
    save_cross_data_to_redis,
    get_field_from_cross_data
)

# Importa de utils.parsing.audio_extraction para manter compatibilidade
from utils.parsing.audio_extraction import detect_audio_from_html, add_audio_tag_if_needed

__all__ = [
    'STOP_WORDS',
    'RELEASE_CLEAN_REGEX',
    'remove_accents',
    'clean_title',
    'get_metadata_name',
    'prepare_release_title',
    'create_standardized_title',
    'find_year_from_text',
    'find_sizes_from_text',
    'format_bytes',
    'detect_audio_from_html',
    'add_audio_tag_if_needed',
    'check_query_match',
    'get_cross_data_from_redis',
    'save_cross_data_to_redis',
    'get_field_from_cross_data',
]

