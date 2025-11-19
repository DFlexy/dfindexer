"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

"""
Serviços relacionados a trackers BitTorrent (scrape de peers).
"""

from cache.redis_client import get_redis_client
from .service import TrackerService

_tracker_service = TrackerService(
    redis_client=get_redis_client(),
    scrape_timeout=0.5,  # Timeout por requisição UDP aos trackers (segundos)
    scrape_retries=2,  # Número de tentativas por tracker
    max_trackers=0,  # Quantidade máxima de trackers consultados por infohash (0 = ilimitado)
    cache_ttl=24 * 3600,  # TTL do cache de seeds/leechers (24 horas)
)


# Retorna instância singleton do serviço de trackers
def get_tracker_service() -> TrackerService:
    return _tracker_service


