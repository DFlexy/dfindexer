# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

from typing import Dict, Optional

from scraper import available_scraper_types, normalize_scraper_type
from api.prowlarr_config import resolve_legacy_scraper_id

def get_scraper_info() -> Dict:
    types_info = available_scraper_types()
    sites_dict = {
        scraper_type: meta.get('default_url')
        for scraper_type, meta in types_info.items()
        if meta.get('default_url')
    }

    return {
        'configured_sites': sites_dict,
        'available_types': list(types_info.keys()),
        'types_info': types_info,
    }

def validate_scraper_type(scraper_type: str) -> tuple[bool, Optional[str]]:
    resolved = resolve_legacy_scraper_id(scraper_type)
    if resolved is None:
        return False, None
    scraper_type = resolved

    types_info = available_scraper_types()
    normalized_type = normalize_scraper_type(scraper_type)

    if normalized_type not in types_info:
        return False, None

    return True, normalized_type
