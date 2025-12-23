"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

# Módulo para parsing e processamento de links magnet
from .parser import MagnetParser
from .metadata import get_torrent_size, fetch_metadata_from_itorrents

__all__ = ["MagnetParser", "get_torrent_size", "fetch_metadata_from_itorrents"]
