# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import json
import logging
import os
import random
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlparse, urlunparse

import requests

from app.config import Config
from cache.store import circuit_tracker_key, get_redis_client, tracker_key, tracker_list_key
from utils.http import get_proxy_dict

PROTOCOL_ID = 0x41727101980
ACTION_CONNECT = 0
ACTION_SCRAPE = 2

def _generate_transaction_id() -> int:
    return random.randint(0, 0xFFFFFFFF)

def _create_udp_socket(host: str, port: int) -> socket.socket:
    try:
        from app.config import Config
        from utils.http import get_proxy_url

        proxy_url = get_proxy_url()
        if proxy_url and proxy_url.startswith(('socks5://', 'socks5h://')):
            try:
                import socks
                proxy_type = Config.PROXY_TYPE.lower().strip()
                proxy_host = Config.PROXY_HOST.strip()
                proxy_port = int(Config.PROXY_PORT.strip())
                proxy_user = Config.PROXY_USER.strip() if Config.PROXY_USER else None
                proxy_pass = Config.PROXY_PASS.strip() if Config.PROXY_PASS else None

                sock = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)

                sock.set_proxy(socks.SOCKS5, proxy_host, proxy_port,
                             username=proxy_user, password=proxy_pass)

                return sock
            except ImportError:
                pass
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Erro ao configurar proxy SOCKS5 para UDP: {e}")
                pass
    except Exception:
        pass

    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

class UDPScraper:
    def __init__(self, timeout: float = 0.5, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        random.seed(int.from_bytes(os.urandom(8), "big"))

    def scrape(self, tracker_url: str, info_hash: bytes) -> Tuple[int, int]:
        host, port = self._parse_tracker(tracker_url)
        sock = _create_udp_socket(host, port)
        try:
            sock.settimeout(self.timeout)
            sock.bind(("", 0))
            connection_id = self._connect(sock, host, port)
            return self._scrape(sock, host, port, connection_id, info_hash)
        finally:
            sock.close()

    def _parse_tracker(self, tracker_url: str) -> Tuple[str, int]:
        stripped = tracker_url.strip()
        if not stripped.lower().startswith("udp://"):
            raise ValueError("Somente trackers UDP são suportados.")
        without_scheme = stripped[6:]
        if "/" in without_scheme:
            without_scheme = without_scheme.split("/", 1)[0]
        if ":" in without_scheme:
            host, port_str = without_scheme.split(":", 1)
            port = int(port_str)
        else:
            host = without_scheme
            port = 80
        if not host:
            raise ValueError("Host inválido para tracker UDP.")
        return host, port

    def _connect(self, sock: socket.socket, host: str, port: int) -> int:
        tid = _generate_transaction_id()
        packet = struct.pack(">QLL", PROTOCOL_ID, ACTION_CONNECT, tid)
        for attempt in range(self.retries + 1):
            sock.sendto(packet, (host, port))
            try:
                data, _ = sock.recvfrom(16)
            except socket.timeout:
                if attempt >= self.retries:
                    raise TimeoutError("Timeout esperando resposta CONNECT.")
                continue
            if len(data) != 16:
                raise RuntimeError("Resposta CONNECT inválida.")
            action, resp_tid, connection_id = struct.unpack(">LLQ", data)
            if action != ACTION_CONNECT:
                raise RuntimeError("Ação CONNECT inválida.")
            if resp_tid != tid:
                raise RuntimeError("Transaction ID CONNECT divergente.")
            return connection_id
        raise TimeoutError("Falha ao conectar ao tracker UDP.")

    def _scrape(
        self, sock: socket.socket, host: str, port: int, connection_id: int, info_hash: bytes
    ) -> Tuple[int, int]:
        if len(info_hash) != 20:
            raise ValueError("info_hash deve possuir 20 bytes.")
        tid = _generate_transaction_id()
        header = struct.pack(">QLL", connection_id, ACTION_SCRAPE, tid)
        packet = header + info_hash
        expected_length = 8 + 12
        for attempt in range(self.retries + 1):
            sock.sendto(packet, (host, port))
            try:
                data, _ = sock.recvfrom(expected_length)
            except socket.timeout:
                if attempt >= self.retries:
                    raise TimeoutError("Timeout esperando resposta SCRAPE.")
                continue
            if len(data) < expected_length:
                if attempt >= self.retries:
                    raise RuntimeError("Resposta SCRAPE incompleta.")
                continue
            action, resp_tid = struct.unpack(">LL", data[:8])
            if resp_tid != tid:
                raise RuntimeError("Transaction ID SCRAPE divergente.")
            if action != ACTION_SCRAPE:
                raise RuntimeError("Ação SCRAPE inválida.")
            seeders, completed, leechers = struct.unpack(">LLL", data[8:20])
            return leechers, seeders
        raise TimeoutError("Falha ao obter dados SCRAPE do tracker.")

logger = logging.getLogger(__name__)

def _announce_to_scrape_url(announce_url: str) -> Optional[str]:
    if not announce_url or not announce_url.strip():
        return None
    url = announce_url.strip()
    lower = url.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return None
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/announce"
        if path.endswith("/announce"):
            new_path = path[:-9] + "scrape"
        elif "/announce" in path:
            new_path = path.replace("/announce", "/scrape")
        else:
            new_path = (path + "/scrape") if path == "/" else path + "/scrape"
        return urlunparse((parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return None

def _decode_bencode_scrape(data: bytes) -> Optional[dict]:
    if not data or not data.startswith(b"d"):
        return None

    def decode_int(s: bytes, i: int):
        if i >= len(s) or s[i:i + 1] != b"i":
            return None, i
        i += 1
        end = s.find(b"e", i)
        if end == -1:
            return None, i
        try:
            n = int(s[i:end])
            return n, end + 1
        except ValueError:
            return None, i

    def decode_string(s: bytes, i: int):
        if i >= len(s):
            return None, i
        colon = s.find(b":", i)
        if colon == -1:
            return None, i
        try:
            length = int(s[i:colon])
        except ValueError:
            return None, i
        start = colon + 1
        end = start + length
        if end > len(s):
            return None, i
        return s[start:end], end

    def decode_dict(s: bytes, i: int):
        if i >= len(s) or s[i:i + 1] != b"d":
            return None, i
        i += 1
        out = {}
        while i < len(s) and s[i:i + 1] != b"e":
            key, i = decode_string(s, i)
            if key is None:
                return None, i
            if s[i:i + 1] == b"d":
                val, i = decode_dict(s, i)
            elif s[i:i + 1] == b"i":
                val, i = decode_int(s, i)
            else:
                val, i = decode_string(s, i)
            if val is None:
                return None, i
            out[key] = val
        if i < len(s):
            i += 1
        return out, i

    try:
        decoded, _ = decode_dict(data, 0)
        return decoded
    except Exception:
        return None

class HTTPScraper:

    def __init__(self, timeout: float = 4.0):
        self.timeout = timeout
        self._session = requests.Session()
        proxy = get_proxy_dict()
        if proxy:
            self._session.proxies.update(proxy)
        self._session.headers.update({
            "User-Agent": "DFIndexer/1.0 (Tracker Scrape)",
            "Accept": "*/*",
        })

    def scrape(self, tracker_url: str, info_hash: bytes) -> Optional[Tuple[int, int]]:
        if len(info_hash) != 20:
            return None
        scrape_url = _announce_to_scrape_url(tracker_url)
        if not scrape_url:
            return None
        try:
            info_hash_encoded = quote(info_hash, safe="")
            url_with_params = f"{scrape_url}?info_hash={info_hash_encoded}"
            resp = self._session.get(url_with_params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.content
            decoded = _decode_bencode_scrape(data)
            if not decoded:
                return None
            if b"failure reason" in decoded or "failure reason" in decoded:
                return None
            files = decoded.get(b"files") or decoded.get("files")
            if not isinstance(files, dict):
                return None
            file_info = files.get(info_hash)
            if not file_info and isinstance(files, dict) and files:
                first_key = next(iter(files))
                if isinstance(first_key, str) and len(info_hash) == 20:
                    file_info = files.get(info_hash.decode("latin-1"))
            if not isinstance(file_info, dict):
                return None
            complete = file_info.get(b"complete") or file_info.get("complete") or 0
            incomplete = file_info.get(b"incomplete") or file_info.get("incomplete") or 0
            return (int(incomplete), int(complete))
        except requests.exceptions.RequestException:
            return None
        except Exception as e:
            logger.debug("HTTP scrape %s: %s", tracker_url[:50], e)
            return None

_request_cache = threading.local()

_logged_sources = {}
_logged_sources_lock = threading.Lock()
_LOG_COOLDOWN = 60



_CIRCUIT_BREAKER_KEY = circuit_tracker_key()
_CIRCUIT_BREAKER_TIMEOUT_THRESHOLD = 3
_CIRCUIT_BREAKER_DISABLE_DURATION = 60

_TRACKER_SOURCES = [
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all_http.txt",
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_all_https.txt",
]

def _is_circuit_breaker_open() -> bool:
    redis = get_redis_client()

    if redis:
        try:
            disabled_until_str = redis.hget(_CIRCUIT_BREAKER_KEY, 'disabled')
            if disabled_until_str:
                disabled_until_float = float(disabled_until_str)
                now = time.time()
                if now < disabled_until_float:
                    return True
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'disabled')
        except Exception:
            pass

    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0
        }

    if _request_cache.circuit_breaker['disabled']:
        logger.debug("Circuit breaker: tracker desabilitado (query atual)")

    return _request_cache.circuit_breaker['disabled']

def _record_timeout():
    redis = get_redis_client()

    if redis:
        try:
            timeout_count = redis.hincrby(_CIRCUIT_BREAKER_KEY, 'timeouts', 1)
            redis.expire(_CIRCUIT_BREAKER_KEY, 60)


            if timeout_count >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
                disabled_until = time.time() + _CIRCUIT_BREAKER_DISABLE_DURATION
                redis.hset(_CIRCUIT_BREAKER_KEY, 'disabled', str(disabled_until))
                redis.expire(_CIRCUIT_BREAKER_KEY, _CIRCUIT_BREAKER_DISABLE_DURATION)
                logger.warning(
                    f"Circuit breaker aberto: {timeout_count} timeouts consecutivos. "
                    f"Tracker desabilitado por {_CIRCUIT_BREAKER_DISABLE_DURATION}s"
                )
                redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
            return
        except Exception as e:
            logger.debug("Timeout register error")

    if not hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker = {
            'disabled': False,
            'timeout_count': 0
        }

    _request_cache.circuit_breaker['timeout_count'] += 1


    if _request_cache.circuit_breaker['timeout_count'] >= _CIRCUIT_BREAKER_TIMEOUT_THRESHOLD:
        _request_cache.circuit_breaker['disabled'] = True
        logger.debug(f"Circuit breaker: {_request_cache.circuit_breaker['timeout_count']} timeouts (query atual)")

def _record_success():
    redis = get_redis_client()

    if redis:
        try:
            redis.hdel(_CIRCUIT_BREAKER_KEY, 'timeouts')
        except Exception:
            pass

    if hasattr(_request_cache, 'circuit_breaker'):
        _request_cache.circuit_breaker['timeout_count'] = 0
        _request_cache.circuit_breaker['disabled'] = False

def _normalize_tracker(url: str) -> Optional[str]:
    url = (url or "").strip()
    if not url:
        return None

    lowered = url.lower()
    if not lowered.startswith(("udp://", "http://", "https://")):
        return None

    url = url.replace("/anunciar", "/announce")
    url = url.replace("/anunc", "/announce")

    return url

class TrackerListProvider:

    def __init__(self, redis_client=None):
        self.redis = redis_client or get_redis_client()
        self._lock = threading.Lock()
        self._memory_cache: List[str] = []
        self._memory_cache_expire_at = 0.0

    def get_trackers(self) -> List[str]:
        trackers = self._get_cached_trackers()
        if trackers:
            return trackers

        if _is_circuit_breaker_open():
            logger.debug("Circuit breaker: pulando trackers remotos")
            if not self.redis and self._memory_cache:
                logger.debug("Usando cache em memória expirado como fallback (Redis desativado)")
                return list(self._memory_cache)
            return []

        trackers = self._fetch_remote_trackers()
        if trackers:
            self._cache_trackers(trackers)
            return trackers

        if not self.redis and self._memory_cache:
            logger.debug("Falha ao buscar trackers remotos - usando cache em memória como fallback (Redis desativado)")
            return list(self._memory_cache)

        logger.error("Falha ao obter lista dinâmica de trackers.")
        return []

    def _get_cached_trackers(self) -> Optional[List[str]]:
        if self.redis:
            try:
                cache_key = tracker_list_key()
                cached = self.redis.get(cache_key)
                if not cached:
                    return None
                trackers = json.loads(cached.decode("utf-8"))
                if not trackers:
                    return None
                trackers_list = list(trackers)
                return trackers_list
            except Exception as exc:
                _log_redis_error("recuperar trackers do cache", exc)
                return None

        if not self.redis:
            now = time.time()
            if now < self._memory_cache_expire_at and self._memory_cache:
                return list(self._memory_cache)

        return None

    def _fetch_remote_trackers(self) -> Optional[List[str]]:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        from utils.http import get_proxy_dict

        session = requests.Session()
        session.headers.update({"User-Agent": "DFIndexer/1.0"})

        retry_strategy = Retry(
            total=1,
            backoff_factor=0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            connect=0,
            read=0,
            redirect=0,
            status=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        proxy_dict = get_proxy_dict()
        if proxy_dict:
            session.proxies.update(proxy_dict)

        for source in _TRACKER_SOURCES:
            try:
                resp = session.get(source, timeout=(5, 15))
                resp.raise_for_status()
                trackers = [
                    tracker
                    for tracker in (line.strip() for line in resp.text.splitlines())
                    if tracker and _normalize_tracker(tracker)
                ]
                if trackers:
                    now = time.time()
                    should_log = False
                    with _logged_sources_lock:
                        last_logged = _logged_sources.get(source, 0)
                        if now - last_logged >= _LOG_COOLDOWN:
                            _logged_sources[source] = now
                            should_log = True
                            if len(_logged_sources) > 10:
                                oldest_key = min(_logged_sources.items(), key=lambda x: x[1])[0]
                                _logged_sources.pop(oldest_key, None)

                    _record_success()
                    return trackers
            except requests.exceptions.Timeout:
                _record_timeout()
                logger.debug("Timeout: %s", source)
            except requests.exceptions.ReadTimeout:
                _record_timeout()
                logger.debug("Read timeout: %s", source)
            except requests.exceptions.ConnectionError as exc:
                error_msg = str(exc)
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(source)
                    host = parsed.netloc or parsed.path.split('/')[0] if parsed.path else source
                except Exception:
                    host = source.split('/')[2] if '/' in source and len(source.split('/')) > 2 else source

                if "Failed to resolve" in error_msg or "No address associated" in error_msg:
                    logger.debug("DNS error: %s (host: %s)", source, host)
                elif "Connection refused" in error_msg:
                    logger.debug("Connection refused: %s (host: %s)", source, host)
                else:
                    short_msg = error_msg.split('(')[0].strip() if '(' in error_msg else error_msg[:100]
                    logger.debug("Connection error: %s - %s", source, short_msg[:50])
            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if hasattr(exc, 'response') and exc.response else 'unknown'
                logger.debug("HTTP %s: %s", status_code, source)
            except Exception as exc:
                error_type = type(exc).__name__
                error_msg = str(exc).split('\n')[0]
                logger.debug("Error: %s (%s) - %s", source, error_type, error_msg[:50])
        return None

    def _cache_trackers(self, trackers: List[str]) -> None:
        if self.redis:
            try:
                cache_key = tracker_list_key()
                encoded = json.dumps(trackers, separators=(',', ':')).encode("utf-8")
                self.redis.setex(
                    cache_key, 24 * 3600, encoded
                )
                return
            except Exception as exc:
                _log_redis_error("gravar lista de trackers", exc)
                return

        if not self.redis:
            with self._lock:
                self._memory_cache = list(trackers)
                self._memory_cache_expire_at = time.time() + 24 * 3600

def _is_redis_connection_error(error: Exception) -> bool:
    error_str = str(error).lower()
    connection_errors = [
        "connection refused",
        "error 111",
        "error 111 connecting",
        "cannot connect",
        "no connection",
        "connection error",
        "connection timeout",
        "name or service not known",
    ]
    return any(err in error_str for err in connection_errors)

def _log_redis_error(operation: str, error: Exception) -> None:
    if _is_redis_connection_error(error):
        logger.debug(f"Redis fallback: {operation}")
    else:
        logger.debug(f"Redis error: {operation}")

def _sanitize_tracker(url: str) -> Optional[str]:
    if not url:
        return None
    normalized = url.strip()
    if not normalized:
        return None
    for token in ("/anunciar", "/Anunciar", "/ANUNCIAR", "/anunc", "/Anunc", "/ANUNC"):
        if token in normalized:
            normalized = normalized.replace(token, "/announce")
    return normalized

def _stable_unique(values: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output

def _filter_udp(trackers: Iterable[str]) -> List[str]:
    return [
        tracker
        for tracker in trackers
        if tracker and tracker.lower().startswith("udp://")
    ]

def _filter_http(trackers: Iterable[str]) -> List[str]:
    return [
        tracker
        for tracker in trackers
        if tracker and (tracker.lower().startswith("http://") or tracker.lower().startswith("https://"))
    ]

class TrackerService:

    def __init__(
        self,
        redis_client=None,
        scrape_timeout: float = 0.5,
        scrape_retries: int = 2,
        max_trackers: int = 0,
        cache_ttl: int = 24 * 3600,
    ):
        self.redis = redis_client or get_redis_client()
        self.cache_ttl = cache_ttl
        max_workers = Config.TRACKER_MAX_WORKERS if hasattr(Config, 'TRACKER_MAX_WORKERS') else 20
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._udp_scraper = UDPScraper(timeout=scrape_timeout, retries=scrape_retries)
        self._http_scraper = HTTPScraper(timeout=4.0)
        self._list_provider = TrackerListProvider(redis_client=self.redis)
        self.max_trackers = max_trackers

    def get_peers(self, info_hash: str, trackers: Iterable[str]) -> Tuple[int, int]:
        result = self.get_peers_bulk({info_hash: list(trackers)})
        return result.get(info_hash, (0, 0))

    def get_peers_bulk(
        self, infohash_trackers: Dict[str, List[str]]
    ) -> Dict[str, Tuple[int, int]]:
        results: Dict[str, Tuple[int, int]] = {}
        todo: Dict[str, List[str]] = {}

        for info_hash, trackers in infohash_trackers.items():
            if not info_hash:
                continue
            cached = self._get_cached(info_hash)
            if cached is not None:
                results[info_hash] = cached
            else:
                todo[info_hash] = trackers

        if not todo:
            return results

        dynamic_trackers = self._list_provider.get_trackers()

        futures = {
            self._executor.submit(
                self._scrape_info_hash,
                info_hash,
                trackers,
                dynamic_trackers,
            ): info_hash
            for info_hash, trackers in todo.items()
        }

        _PEER_BATCH_TIMEOUT = 60
        _seen = set()
        try:
            for future in as_completed(futures, timeout=_PEER_BATCH_TIMEOUT):
                info_hash = futures[future]
                _seen.add(info_hash)
                try:
                    peers = future.result(timeout=5)
                    if peers is not None:
                        results[info_hash] = peers
                        self._store_cache(info_hash, peers)
                    else:
                        results[info_hash] = (0, 0)
                except Exception as exc:
                    logger.warning("Falha ao obter peers para %s: %s", info_hash, exc)
                    results[info_hash] = (0, 0)
        except Exception as e:
            remaining = [h for h in todo if h not in _seen]
            if remaining:
                logger.debug("Tracker batch: timeout/erro após %ds, %d pendentes recebem (0,0)", _PEER_BATCH_TIMEOUT, len(remaining))
            for info_hash in remaining:
                results[info_hash] = (0, 0)

        return results

    def _scrape_info_hash(
        self,
        info_hash: str,
        trackers: Optional[Iterable[str]],
        dynamic_trackers: Optional[List[str]] = None,
    ) -> Optional[Tuple[int, int]]:
        info_hash = info_hash.lower()
        try:
            info_hash_bytes = bytes.fromhex(info_hash)
        except ValueError:
            logger.debug("Invalid info_hash: %s", info_hash[:16])
            return None

        provided_trackers = [
            tracker
            for tracker in (_sanitize_tracker(t) for t in (trackers or []))
            if tracker
        ]
        if dynamic_trackers is None:
            dynamic_trackers = self._list_provider.get_trackers()

        combined_trackers = _stable_unique(provided_trackers + (dynamic_trackers or []))
        http_trackers = _filter_http(combined_trackers)
        udp_trackers = _filter_udp(combined_trackers)

        if self.max_trackers > 0:
            half = max(1, self.max_trackers // 2)
            http_trackers = http_trackers[:half]
            udp_trackers = udp_trackers[:half]

        best: Optional[Tuple[int, int]] = None
        zero_count = 0
        _MAX_ZERO_RESPONSES = 2

        for tracker in http_trackers:
            try:
                peers = self._scrape_single_http_tracker(tracker, info_hash_bytes)
                if peers is not None:
                    leechers, seeders = peers
                    if seeders or leechers:
                        return leechers, seeders
                    if best is None:
                        best = (leechers, seeders)
                    zero_count += 1
                    if zero_count >= _MAX_ZERO_RESPONSES:
                        break
            except Exception:
                pass

        if zero_count >= _MAX_ZERO_RESPONSES and best is not None:
            return best

        for tracker in udp_trackers:
            try:
                peers = self._scrape_single_tracker(
                    tracker, info_hash_bytes, info_hash
                )
                if peers is not None:
                    leechers, seeders = peers
                    if seeders or leechers:
                        return leechers, seeders
                    if best is None:
                        best = (leechers, seeders)
                    zero_count += 1
                    if zero_count >= _MAX_ZERO_RESPONSES:
                        break
            except Exception as exc:
                error_msg = str(exc)
                is_dns_error = (
                    "Temporary failure in name resolution" in error_msg
                    or "[Errno -3]" in error_msg
                    or "[Errno -2]" in error_msg
                    or "[Errno -5]" in error_msg
                    or "No address associated with hostname" in error_msg
                    or "name or service not known" in error_msg.lower()
                    or "Name or service not known" in error_msg
                )
                is_timeout_error = (
                    "Timeout" in error_msg
                    or "timeout" in error_msg.lower()
                    or isinstance(exc, TimeoutError)
                )

                if is_dns_error:
                    logger.debug("Tracker %s: DNS error", tracker)
                elif is_timeout_error:
                    logger.debug("Tracker %s: timeout", tracker)
                else:
                    error_type = type(exc).__name__
                    short_msg = error_msg.split('\n')[0][:50]
                    logger.debug("Tracker %s: %s - %s", tracker, error_type, short_msg)

        if best is not None:
            return best
        return None

    def _scrape_single_http_tracker(
        self, tracker: str, info_hash_bytes: bytes
    ) -> Optional[Tuple[int, int]]:
        try:
            return self._http_scraper.scrape(tracker, info_hash_bytes)
        except Exception:
            return None

    def _scrape_single_tracker(
        self, tracker: str, info_hash_bytes: bytes, info_hash: str
    ) -> Optional[Tuple[int, int]]:
        try:
            leechers, seeders = self._udp_scraper.scrape(tracker, info_hash_bytes)
            return leechers, seeders
        except Exception:
            return None

    def _cache_key(self, info_hash: str) -> str:
        return tracker_key(info_hash)

    def _get_cached(self, info_hash: str) -> Optional[Tuple[int, int]]:
        try:
            from cache.store import TrackerCache
            tracker_cache = TrackerCache()
            cached_data = tracker_cache.get(info_hash)
            if cached_data:
                return int(cached_data.get("leech", 0)), int(cached_data.get("seed", 0))
        except Exception:
            pass

        return None

    def _store_cache(self, info_hash: str, peers: Tuple[int, int]) -> None:
        try:
            from cache.store import TrackerCache
            tracker_cache = TrackerCache()
            tracker_data = {"leech": peers[0], "seed": peers[1]}
            tracker_cache.set(info_hash, tracker_data)
        except Exception:
            pass
