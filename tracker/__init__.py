"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

"""
Serviços relacionados a trackers BitTorrent (scrape de peers).
"""

from cache.redis_client import get_redis_client
from app.config import Config
from .service import TrackerService

_tracker_service = TrackerService(
    redis_client=get_redis_client(),
    scrape_timeout=Config.TRACKER_SCRAPE_TIMEOUT,
    scrape_retries=Config.TRACKER_SCRAPE_RETRIES,
    max_trackers=Config.TRACKER_SCRAPE_MAX_TRACKERS,
    cache_ttl=Config.TRACKER_CACHE_TTL,
)


def get_tracker_service() -> TrackerService:
    """Retorna instância singleton do serviço de trackers."""
    return _tracker_service


