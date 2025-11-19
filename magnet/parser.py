"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
import hashlib
import base64
from urllib.parse import urlparse, parse_qs, unquote
from typing import Dict, List, Optional


# Parser para links magnet
class MagnetParser:
    @staticmethod
    # Parse de URI magnet - retorna Dict com info_hash, display_name, trackers, params
    def parse(uri: str) -> Dict:
        parsed = urlparse(uri)
        if parsed.scheme != 'magnet':
            raise ValueError(f"Esquema inválido: {parsed.scheme}")
        
        query = parse_qs(parsed.query)
        
        # Extrai info_hash
        xt = query.get('xt', [])
        if not xt:
            raise ValueError("Parâmetro xt não encontrado")
        
        xt_value = xt[0]
        if not xt_value.startswith('urn:btih:'):
            raise ValueError("Formato de xt inválido")
        
        info_hash_encoded = xt_value[9:]
        
        info_hash_bytes = MagnetParser._decode_infohash(info_hash_encoded)
        info_hash_hex = info_hash_bytes.hex()
        
        display_name = ''
        if 'dn' in query:
            display_name = unquote(query['dn'][0])
        
        trackers = []
        if 'tr' in query:
            trackers = [unquote(tr) for tr in query['tr']]
        
        params = {}
        for key, values in query.items():
            if key not in ['xt', 'dn', 'tr']:
                params[key] = unquote(values[0]) if values else ''
        
        return {
            'info_hash': info_hash_hex,
            'display_name': display_name,
            'trackers': trackers,
            'params': params
        }
    
    @staticmethod
    # Decodifica info_hash (hex ou base32)
    def _decode_infohash(encoded: str) -> bytes:
        if len(encoded) == 40:
            try:
                return bytes.fromhex(encoded)
            except ValueError:
                raise ValueError("InfoHash hex inválido")
        elif len(encoded) == 32:
            try:
                return base64.b32decode(encoded.upper())
            except Exception:
                raise ValueError("InfoHash base32 inválido")
        else:
            raise ValueError(f"Tamanho de info_hash inválido: {len(encoded)}")

