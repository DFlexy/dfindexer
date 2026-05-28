# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

"""Scraper HTTP/HTTPS para trackers BitTorrent (BEP-48 / protocolo clássico)"""

import logging
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse, quote

import requests

from utils.http.proxy import get_proxy_dict

logger = logging.getLogger(__name__)

def _announce_to_scrape_url(announce_url: str) -> Optional[str]:
    """Converte URL de announce em URL de scrape (troca último segmento announce por scrape)."""
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
    """Decodifica resposta bencode do scrape (apenas o que precisamos)"""
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
    """Scrape de trackers HTTP/HTTPS (GET /scrape?info_hash=...). Usa proxy quando configurado."""

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
        """Faz scrape HTTP no tracker"""
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
