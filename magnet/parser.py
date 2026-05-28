# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
import hashlib
import base64
from urllib.parse import urlparse, parse_qs, unquote
from typing import Dict, List, Optional

class MagnetParser:
    @staticmethod
    def parse(uri: str) -> Dict:
        parsed = urlparse(uri)
        if parsed.scheme != 'magnet':
            raise ValueError(f"Esquema inválido: {parsed.scheme}")
        
        match = re.search(r'xt=urn:btih:([^&]+)', parsed.query, re.IGNORECASE)
        if match:
            info_hash_raw = match.group(1)
            if '%' in info_hash_raw:
                def replace_percent(match):
                    hex_chars = match.group(1)
                    if all(c in '0123456789abcdefABCDEF' for c in hex_chars):
                        return hex_chars
                    return ''
                
                info_hash_cleaned = re.sub(r'%([0-9A-Fa-f]{2})', replace_percent, info_hash_raw)
                if len(info_hash_cleaned) in [32, 40]:
                    info_hash_encoded = info_hash_cleaned
                else:
                    info_hash_decoded = unquote(info_hash_raw)
                    if len(info_hash_decoded) in [32, 40]:
                        info_hash_encoded = info_hash_decoded
                    elif len(info_hash_raw) in [32, 40]:
                        info_hash_encoded = info_hash_raw
                    else:
                        info_hash_encoded = info_hash_cleaned
            else:
                info_hash_encoded = info_hash_raw
        else:
            query = parse_qs(parsed.query)
            xt = query.get('xt', [])
            if not xt:
                raise ValueError("Parâmetro xt não encontrado")
            xt_value = xt[0]
            if not xt_value.startswith('urn:btih:'):
                raise ValueError("Formato de xt inválido")
            info_hash_encoded = unquote(xt_value[9:])
        
        info_hash_bytes = MagnetParser._decode_infohash(info_hash_encoded)
        
        query = parse_qs(parsed.query)
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
        
        result = {
            'info_hash': info_hash_hex,
            'display_name': display_name,
            'trackers': trackers,
            'params': params
        }
        return result
    
    @staticmethod
    def _decode_infohash(encoded: str) -> bytes:
        encoded_clean = ''.join(c for c in encoded if c.isalnum() or c in '+-=')
        
        hex_chars = ''.join(c for c in encoded_clean if c in '0123456789abcdefABCDEF')
        
        if len(hex_chars) == 40:
            try:
                return bytes.fromhex(hex_chars)
            except ValueError:
                pass
        
        if len(hex_chars) > 40:
            try:
                return bytes.fromhex(hex_chars[:40])
            except ValueError:
                pass
        
        if len(encoded_clean) == 40:
            try:
                if all(c in '0123456789abcdefABCDEF' for c in encoded_clean):
                    return bytes.fromhex(encoded_clean)
            except ValueError:
                pass
        
        if len(encoded_clean) == 32:
            try:
                return base64.b32decode(encoded_clean.upper())
            except Exception:
                pass
        
        if len(encoded) == 40:
            try:
                hex_only = ''.join(c for c in encoded if c in '0123456789abcdefABCDEF')
                if len(hex_only) >= 40:
                    return bytes.fromhex(hex_only[:40])
            except ValueError:
                pass
        
        if len(encoded) == 32:
            try:
                return base64.b32decode(encoded.upper())
            except Exception:
                pass
        
        raise ValueError(f"Tamanho de info_hash inválido: {len(encoded_clean)} (original: {len(encoded)})")

