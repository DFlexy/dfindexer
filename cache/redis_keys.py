# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import hashlib
from typing import Optional

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