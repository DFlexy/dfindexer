"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from typing import List, Dict
from urllib.parse import unquote
from magnet.parser import MagnetParser


# Processa trackers de magnet_data, limpando caracteres especiais e decodificando URLs
def process_trackers(magnet_data: Dict) -> List[str]:
    """
    Processa trackers de magnet_data, limpando caracteres especiais e decodificando URLs.
    
    Args:
        magnet_data: Dicionário retornado por MagnetParser.parse()
    
    Returns:
        Lista de trackers processados e limpos
    """
    trackers = []
    raw_trackers = magnet_data.get('trackers', [])
    
    for tracker in raw_trackers:
        # Remove entidades HTML codificadas
        tracker = tracker.replace('&#038;', '&').replace('&amp;', '&')
        
        # Decodifica URL
        try:
            tracker = unquote(tracker)
        except Exception:
            pass
        
        # Remove espaços extras e adiciona à lista
        tracker_clean = tracker.strip()
        if tracker_clean:
            trackers.append(tracker_clean)
    
    return trackers


# Extrai e processa trackers de um magnet_link
def extract_trackers_from_magnet(magnet_link: str) -> List[str]:
    """
    Extrai e processa trackers de um magnet_link.
    
    Args:
        magnet_link: String com o link magnet
    
    Returns:
        Lista de trackers processados e limpos, ou lista vazia em caso de erro
    """
    try:
        magnet_data = MagnetParser.parse(magnet_link)
        return process_trackers(magnet_data)
    except Exception:
        return []

