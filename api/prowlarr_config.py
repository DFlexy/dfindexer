# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

from typing import Dict, Optional

# IDs numéricos legados do Prowlarr (instâncias antigas). Não é lista de scrapers ativos.
# None = indexer removido; slug ausente = tratar site_name como slug atual.
SCRAPER_NUMBER_MAP: Dict[str, Optional[str]] = {
    "1": "starck",
    "2": "rede",
    "3": None,
    "4": "tfilme",
    "5": None,
    "6": "comand",
    "7": "bludv",
    "8": "portal",
}


def get_prowlarr_scraper_options() -> Dict[str, str]:
    """Opções do campo scraper_type no prowlarr.yml — derivadas da pasta scraper/."""
    from scraper import available_scraper_types

    types_info = available_scraper_types()
    return {
        slug: meta.get('display_name') or slug
        for slug, meta in sorted(types_info.items())
    }


def get_prowlarr_default_scraper() -> str:
    options = get_prowlarr_scraper_options()
    if not options:
        return 'starck'
    return next(iter(options))


def resolve_legacy_scraper_id(site_name: str) -> Optional[str]:
    """Converte ID numérico legado em slug; None se ID removido; slug inalterado."""
    if site_name not in SCRAPER_NUMBER_MAP:
        return site_name
    return SCRAPER_NUMBER_MAP[site_name]


def is_removed_legacy_id(site_name: str) -> bool:
    return site_name in SCRAPER_NUMBER_MAP and SCRAPER_NUMBER_MAP[site_name] is None
