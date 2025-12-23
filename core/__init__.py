"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

# Módulo core com enrichers, filters e processors
from core.enrichers.torrent_enricher import TorrentEnricher
from core.filters.query_filter import QueryFilter
from core.processors.torrent_processor import TorrentProcessor

__all__ = [
    'TorrentEnricher',
    'QueryFilter',
    'TorrentProcessor',
]

