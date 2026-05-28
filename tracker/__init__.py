# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

"""
Serviços relacionados a trackers BitTorrent (scrape de peers).
"""

from cache.redis_client import get_redis_client
from .service import TrackerService

_tracker_service = TrackerService(
    redis_client=get_redis_client(),
    scrape_timeout=1.5,
    scrape_retries=3,
    max_trackers=10,
    cache_ttl=24 * 3600,
)

def get_tracker_service() -> TrackerService:
    return _tracker_service

