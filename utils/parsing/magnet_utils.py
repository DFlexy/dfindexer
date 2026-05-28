# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

from typing import List, Dict
from urllib.parse import unquote
from magnet.parser import MagnetParser

def process_trackers(magnet_data: Dict) -> List[str]:
    trackers = []
    raw_trackers = magnet_data.get('trackers', [])
    
    for tracker in raw_trackers:
        tracker = tracker.replace('&#038;', '&').replace('&amp;', '&')
        
        try:
            tracker = unquote(tracker)
        except Exception:
            pass
        
        tracker_clean = tracker.strip()
        if tracker_clean:
            trackers.append(tracker_clean)
    
    return trackers

def extract_trackers_from_magnet(magnet_link: str) -> List[str]:
    try:
        magnet_data = MagnetParser.parse(magnet_link)
        return process_trackers(magnet_data)
    except Exception:
        return []

