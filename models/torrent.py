"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict


# Modelo de dados para torrent
@dataclass
class Torrent:
    title: str
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
        """Converte o modelo para dicionário"""
        result = asdict(self)
        # Remove campos vazios opcionais para manter resposta JSON limpa
        return {k: v for k, v in result.items() if v or k in ['seeds', 'leechers']}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Torrent':
        """Cria instância a partir de dicionário"""
        return cls(
            title=data.get('title', ''),
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

