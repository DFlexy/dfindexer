# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict

@dataclass
class Torrent:
    title_processed: str
    magnet: str
    info_hash: str
    date: str = ''
    size: str = ''
    seeds: int = 0
    leechers: int = 0
    original_title: str = ''
    year: str = ''
    imdb: str = ''
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        return {k: v for k, v in result.items() if v or k in ['seeds', 'leechers']}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Torrent':
        return cls(
            title_processed=data.get('title_processed', ''),
            magnet=data.get('magnet', ''),
            info_hash=data.get('info_hash', ''),
            date=data.get('date', ''),
            size=data.get('size', ''),
            seeds=data.get('seeds', 0),
            leechers=data.get('leechers', 0),
            original_title=data.get('original_title', ''),
            year=data.get('year', ''),
            imdb=data.get('imdb', '')
        )

