# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from app.config import Config

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest()

def html_long_key(url: str) -> str:
    return f"html:long:{url_hash(url)}"

def html_short_key(url: str) -> str:
    return f"html:short:{url_hash(url)}"

def html_failure_key(url: str) -> str:
    return f"html:failure:{url_hash(url)}"

def metadata_key(info_hash: str) -> str:
    return f"metadata:data:{info_hash.lower()}"

def metadata_failure_key(info_hash: str) -> str:
    return f"metadata:failure:{info_hash.lower()}"

def metadata_failure503_key(info_hash: str) -> str:
    return f"metadata:failure503:{info_hash.lower()}"

def tracker_key(info_hash: str) -> str:
    return f"tracker:data:{info_hash.lower()}"

def tracker_list_key() -> str:
    return "tracker:list:"

def imdb_key(info_hash: str) -> str:
    return f"imdb:hash:{info_hash.lower()}"

def imdb_title_key(base_title: str) -> str:
    import hashlib
    normalized = base_title.lower().strip()
    normalized = ' '.join(normalized.split())
    title_hash = hashlib.md5(normalized.encode('utf-8')).hexdigest()
    return f"imdb:title:{title_hash}"

def release_title_key(info_hash: str) -> str:
    return f"release:title:{info_hash.lower()}"

def torrent_cross_data_key(info_hash: str) -> str:

    return f"cross:torrent:{info_hash.lower()}"

def protlink_key(url: str) -> str:
    return f"link:protected:{url_hash(url)}"

def circuit_metadata_key() -> str:
    return "circuit:metadata"

def circuit_tracker_key() -> str:
    return "circuit:tracker"

def flaresolverr_session_key(base_url: str) -> str:
    return f"flaresolverr:session:{base_url}"

def flaresolverr_created_key(base_url: str) -> str:
    return f"flaresolverr:created:{base_url}"

def flaresolverr_failure_key(url: str) -> str:
    return f"flaresolverr:failure:{url_hash(url)}"

def flaresolverr_session_creation_failure_key(base_url: str) -> str:
    return f"flaresolverr:session_creation_failure:{base_url}"

if TYPE_CHECKING:
    import redis
else:
    try:
        import redis
    except ImportError:
        redis = None

logger = logging.getLogger(__name__)

_redis_client: Optional['redis.Redis'] = None if redis is None else None
_last_warning_log = 0.0
_WARNING_LOG_COOLDOWN = 60

def init_redis():
    global _redis_client, _last_warning_log

    if redis is None:
        _redis_client = None
        return

    if not Config.REDIS_HOST or Config.REDIS_HOST.strip() == '':
        _redis_client = None
        return

    try:
        _redis_client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            db=Config.REDIS_DB,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2
        )
        _redis_client.ping()
        _last_warning_log = 0.0
    except Exception as e:
        _redis_client = None
        pass

def get_redis_client() -> Optional['redis.Redis']:
    if redis is None:
        return None

    if _redis_client is None:
        try:
            init_redis()
        except Exception:
            pass
    return _redis_client

class HTTPLocalCache:

    def __init__(self, ttl: Optional[int] = None, max_size: int = 200):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.ttl = ttl if ttl is not None else (Config.LOCAL_CACHE_TTL if hasattr(Config, 'LOCAL_CACHE_TTL') else 30)
        self.max_size = max_size
        self.enabled = Config.LOCAL_CACHE_ENABLED if hasattr(Config, 'LOCAL_CACHE_ENABLED') else True
        self._last_cleanup = time.time()
        self._cleanup_interval = 30

    def get(self, key: str) -> Optional[bytes]:
        if not self.enabled:
            return None

        with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]
            now = time.time()

            if now > entry['expires_at']:
                del self._cache[key]
                return None

            entry['hits'] += 1
            entry['last_access'] = now
            return entry['value']

    def set(self, key: str, value: bytes) -> None:
        if not self.enabled:
            return

        with self._lock:
            now = time.time()

            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired(now)
                self._last_cleanup = now

            if len(self._cache) >= self.max_size:
                self._cleanup_expired(now)
                if len(self._cache) >= self.max_size:
                    self._evict_oldest()

            self._cache[key] = {
                'value': value,
                'expires_at': now + self.ttl,
                'created_at': now,
                'last_access': now,
                'hits': 0
            }

    def _cleanup_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._cache.items()
            if now > entry['expires_at']
        ]
        for key in expired_keys:
            del self._cache[key]

    def _evict_oldest(self) -> None:
        if not self._cache:
            return

        to_remove = max(1, len(self._cache) // 4)
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k]['last_access']
        )
        for key in sorted_keys[:to_remove]:
            del self._cache[key]

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total_hits = sum(entry['hits'] for entry in self._cache.values())
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'total_hits': total_hits,
                'ttl': self.ttl,
                'enabled': self.enabled
            }

_http_cache = None
_http_cache_lock = threading.Lock()

def get_http_cache() -> HTTPLocalCache:
    global _http_cache

    if _http_cache is None:
        with _http_cache_lock:
            if _http_cache is None:
                _http_cache = HTTPLocalCache()

    return _http_cache

_request_cache = threading.local()

class MetadataCache:
    def __init__(self):
        self.redis = get_redis_client()

    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        info_hash_lower = info_hash.lower()

        if self.redis:
            try:
                key = metadata_key(info_hash_lower)
                data_str = self.redis.get(key)
                if data_str:
                    data = json.loads(data_str.decode('utf-8'))
                    return data
            except json.JSONDecodeError as e:
                logger.warning(f"[MetadataCache] Erro ao decodificar JSON: {info_hash_lower[:16]}... (chave: {key}) - {e}")
                return None
            except Exception as e:
                logger.debug(f"[MetadataCache] Erro ao ler Redis: {type(e).__name__} - {info_hash_lower[:16]}... - {e}")
                return None

        if not self.redis:
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.store = {}

            return _request_cache.store.get(info_hash_lower)

        return None

    def set(self, info_hash: str, metadata: Dict[str, Any]) -> None:
        info_hash_lower = info_hash.lower()

        if self.redis:
            try:
                key = metadata_key(info_hash_lower)
                exists = self.redis.exists(key)
                metadata_json = json.dumps(metadata, separators=(',', ':'))
                self.redis.setex(key, Config.METADATA_CACHE_TTL, metadata_json)
                return
            except Exception as e:
                logger.debug(f"[MetadataCache] Erro ao salvar Redis: {type(e).__name__} - {info_hash_lower[:16]}...")
                return

        if not self.redis:
            if not hasattr(_request_cache, 'metadata_cache'):
                _request_cache.store = {}

            _request_cache.store[info_hash_lower] = metadata

    def set_failure(self, info_hash: str, ttl: int = 60) -> None:
        info_hash_lower = info_hash.lower()

        if self.redis:
            try:
                if ttl == 300:
                    key = metadata_failure503_key(info_hash_lower)
                else:
                    key = metadata_failure_key(info_hash_lower)
                self.redis.setex(key, ttl, str(int(time.time())))
                return
            except Exception:
                return

        if not self.redis:
            if not hasattr(_request_cache, 'metadata_failure_cache'):
                _request_cache.metadata_failure_cache = {}

            expire_at = time.time() + ttl
            _request_cache.metadata_failure_cache[info_hash_lower] = expire_at

    def is_failure_cached(self, info_hash: str) -> bool:
        info_hash_lower = info_hash.lower()

        if self.redis:
            try:
                failure503_key = metadata_failure503_key(info_hash_lower)
                if self.redis.exists(failure503_key):
                    return True

                failure_key = metadata_failure_key(info_hash_lower)
                if self.redis.exists(failure_key):
                    return True
            except Exception:
                return False

        if not self.redis:
            if not hasattr(_request_cache, 'metadata_failure_cache'):
                return False

            expire_at = _request_cache.metadata_failure_cache.get(info_hash_lower)
            if expire_at and time.time() < expire_at:
                return True
            elif expire_at:
                del _request_cache.metadata_failure_cache[info_hash_lower]

        return False

class TrackerCache:
    def __init__(self):
        self.redis = get_redis_client()

    def get(self, info_hash: str) -> Optional[Dict[str, Any]]:
        info_hash_lower = info_hash.lower()

        if self.redis:
            try:
                key = tracker_key(info_hash_lower)
                peers_str = self.redis.hget(key, 'peers')
                if peers_str:
                    data = json.loads(peers_str.decode('utf-8'))
                    return data
            except Exception as e:
                logger.debug(f"[TrackerCache] Erro ao buscar cache Redis: {type(e).__name__}")
                return None

        if not self.redis:
            if not hasattr(_request_cache, 'tracker_cache'):
                _request_cache.store = {}

            cached = _request_cache.store.get(info_hash_lower)
            return cached

        return None

    def set(self, info_hash: str, tracker_data: Dict[str, Any]) -> None:
        info_hash_lower = info_hash.lower()

        if self.redis:
            try:
                key = tracker_key(info_hash_lower)
                self.redis.hset(key, 'peers', json.dumps(tracker_data, separators=(',', ':')))
                self.redis.hset(key, 'last_scrape', str(int(time.time())))
                self.redis.hset(key, 'created', str(int(time.time())))
                self.redis.expire(key, Config.TRACKER_CACHE_TTL)
                return
            except Exception as e:
                logger.debug(f"[TrackerCache] Erro ao salvar cache Redis: {type(e).__name__}")
                return

        if not self.redis:
            if not hasattr(_request_cache, 'tracker_cache'):
                _request_cache.store = {}

            _request_cache.store[info_hash_lower] = tracker_data
