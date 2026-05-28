# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

from api.services.indexer_common import get_scraper_info, validate_scraper_type

class IndexerService:

    get_scraper_info = staticmethod(get_scraper_info)
    validate_scraper_type = staticmethod(validate_scraper_type)
