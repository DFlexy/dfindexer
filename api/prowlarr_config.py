# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

from typing import Dict, Optional

SCRAPER_NUMBER_MAP: Dict[str, Optional[str]] = {
    "1": "starck",
    "2": "rede",
    "3": "xfilmes",
    "4": "tfilme",
    "5": None,
    "6": "comand",
    "7": "bludv",
    "8": "portal",
}

PROWLARR_SCRAPER_OPTIONS: Dict[str, str] = {
    "starck": "Starck",
    "rede": "Rede",
    "xfilmes": "XFilmes",
    "tfilme": "Tfilme",
    "comand": "Comando",
    "bludv": "Bludv",
    "portal": "Portal",
}

def resolve_legacy_scraper_id(site_name: str) -> Optional[str]:
    """Converte ID numérico legado em slug; None se ID removido; slug inalterado."""
    if site_name not in SCRAPER_NUMBER_MAP:
        return site_name
    return SCRAPER_NUMBER_MAP[site_name]

def is_removed_legacy_id(site_name: str) -> bool:
    return site_name in SCRAPER_NUMBER_MAP and SCRAPER_NUMBER_MAP[site_name] is None
