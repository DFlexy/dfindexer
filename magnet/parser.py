"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

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
        
        # IMPORTANTE: Extrai info_hash diretamente da query string original ANTES de parse_qs
        # Isso evita problemas com parse_qs decodificando caracteres inválidos (ex: %94)
        # O %94 não é um caractere válido em hex, então pode ser um erro no magnet link
        # Mas vamos tentar extrair corretamente mesmo assim
        match = re.search(r'xt=urn:btih:([^&]+)', parsed.query, re.IGNORECASE)
        if match:
            # Extrai o hash da query string original
            info_hash_raw = match.group(1)
            # Tenta corrigir hash malformado: trata %XX como dois caracteres hex se válido
            # Se o hash tem %94 ou outros códigos, tenta decodificar %XX como dois caracteres hex
            if '%' in info_hash_raw:
                # Substitui %XX por XX (dois caracteres hex) se XX for válido em hex
                # Ex: ed657c100%9487fcf -> ed657c1009487fcf (substitui %94 por 94)
                def replace_percent(match):
                    hex_chars = match.group(1)
                    # Verifica se ambos os caracteres são hex válidos
                    if all(c in '0123456789abcdefABCDEF' for c in hex_chars):
                        return hex_chars  # Substitui %XX por XX
                    return ''  # Remove se não for válido
                
                info_hash_cleaned = re.sub(r'%([0-9A-Fa-f]{2})', replace_percent, info_hash_raw)
                # Se após limpeza o tamanho está correto, usa ele
                if len(info_hash_cleaned) in [32, 40]:
                    info_hash_encoded = info_hash_cleaned
                else:
                    # Tenta decodificar normalmente
                    info_hash_decoded = unquote(info_hash_raw)
                    if len(info_hash_decoded) in [32, 40]:
                        info_hash_encoded = info_hash_decoded
                    elif len(info_hash_raw) in [32, 40]:
                        # O valor original tem tamanho correto, usa ele
                        info_hash_encoded = info_hash_raw
                    else:
                        # Usa o limpo mesmo que não tenha tamanho correto (será tratado no _decode_infohash)
                        info_hash_encoded = info_hash_cleaned
            else:
                # Sem %, usa diretamente
                info_hash_encoded = info_hash_raw
        else:
            # Fallback: usa parse_qs (pode ter problemas com caracteres inválidos)
            query = parse_qs(parsed.query)
            xt = query.get('xt', [])
            if not xt:
                raise ValueError("Parâmetro xt não encontrado")
            xt_value = xt[0]
            if not xt_value.startswith('urn:btih:'):
                raise ValueError("Formato de xt inválido")
            info_hash_encoded = unquote(xt_value[9:])
        
        # Processa o info_hash extraído
        info_hash_bytes = MagnetParser._decode_infohash(info_hash_encoded)
        
        # Agora usa parse_qs para extrair outros parâmetros (dn, tr, etc.)
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
        # Remove caracteres não-ASCII ou inválidos que podem ter sido introduzidos por URL decoding incorreto
        # Mantém apenas caracteres hexadecimais válidos (0-9, a-f, A-F) ou base32 válidos
        encoded_clean = ''.join(c for c in encoded if c.isalnum() or c in '+-=')
        
        # Extrai apenas caracteres hex válidos
        hex_chars = ''.join(c for c in encoded_clean if c in '0123456789abcdefABCDEF')
        
        # Se tem exatamente 40 caracteres hex, usa eles
        if len(hex_chars) == 40:
            try:
                return bytes.fromhex(hex_chars)
            except ValueError:
                pass
        
        # Se tem mais de 40 caracteres hex, tenta pegar os primeiros 40
        if len(hex_chars) > 40:
            try:
                return bytes.fromhex(hex_chars[:40])
            except ValueError:
                pass
        
        # Se tem exatamente 40 caracteres após limpeza completa
        if len(encoded_clean) == 40:
            try:
                if all(c in '0123456789abcdefABCDEF' for c in encoded_clean):
                    return bytes.fromhex(encoded_clean)
            except ValueError:
                pass
        
        # Se tem exatamente 32 caracteres, tenta base32
        if len(encoded_clean) == 32:
            try:
                return base64.b32decode(encoded_clean.upper())
            except Exception:
                pass
        
        # Se o original tem tamanho correto, tenta usar ele
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

