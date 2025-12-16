"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def get_cross_data_from_redis(info_hash: str) -> Optional[Dict[str, Any]]:
    """
    Busca dados cruzados no Redis por info_hash.
    Retorna um dicionário com os campos disponíveis ou None se não encontrado.
    Campos: title_original_html, magnet_processed, title_translated_html, imdb, missing_dn, origem_audio_tag, tracker_seed, tracker_leech, size
    """
    if not info_hash or len(info_hash) != 40:
        return None
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import torrent_cross_data_key
        
        redis = get_redis_client()
        if not redis:
            return None
        
        key = torrent_cross_data_key(info_hash)
        # Busca todos os campos do hash
        data = redis.hgetall(key)
        if not data:
            return None
        
        # Converte bytes para strings
        result = {}
        for field, value in data.items():
            field_str = field.decode('utf-8')
            value_str = value.decode('utf-8')
            
            # Converte tipos específicos
            if field_str == 'missing_dn':
                result[field_str] = value_str.lower() == 'true'
            elif field_str in ('tracker_seed', 'tracker_leech'):
                # Converte para inteiro
                try:
                    result[field_str] = int(value_str) if value_str and value_str != 'N/A' else 0
                except (ValueError, TypeError):
                    result[field_str] = 0
            else:
                result[field_str] = value_str if value_str and value_str != 'N/A' else None
        
        if result:
            return result
    except Exception:
        pass
    
    return None


def save_cross_data_to_redis(info_hash: str, data: Dict[str, Any]) -> None:
    """
    Salva dados cruzados no Redis por info_hash.
    Campos aceitos: title_original_html, magnet_processed, title_translated_html, imdb, missing_dn, origem_audio_tag, tracker_seed, tracker_leech, size
    """
    if not info_hash or len(info_hash) != 40:
        return
    
    if not data:
        return
    
    try:
        from cache.redis_client import get_redis_client
        from cache.redis_keys import torrent_cross_data_key
        
        redis = get_redis_client()
        if not redis:
            return
        
        key = torrent_cross_data_key(info_hash)
        
        # Campos permitidos
        allowed_fields = [
            'title_original_html',
            'magnet_processed',
            'title_translated_html',
            'imdb',
            'missing_dn',
            'origem_audio_tag',
            'tracker_seed',
            'tracker_leech',
            'size'
        ]
        
        # Prepara dados para salvar (apenas campos válidos e não vazios)
        to_save = {}
        for field in allowed_fields:
            value = data.get(field)
            # Para campos de tracker, aceita 0 também (para evitar consultas futuras)
            if field in ('tracker_seed', 'tracker_leech'):
                if value is not None and value != '' and value != 'N/A':
                    # Aceita int (incluindo 0) ou string que representa número
                    if isinstance(value, int):
                        to_save[field] = str(value)  # Salva mesmo se for 0
                    elif isinstance(value, str) and value.strip().isdigit():
                        to_save[field] = value.strip()  # Salva string numérica
            elif value is not None and value != '' and value != 'N/A':
                # Converte boolean para string
                if isinstance(value, bool):
                    to_save[field] = 'true' if value else 'false'
                # Converte inteiros para string
                elif isinstance(value, int):
                    to_save[field] = str(value)
                else:
                    value_str = str(value).strip()
                    if value_str and len(value_str) >= 1:  # Aceita valores com pelo menos 1 caractere
                        to_save[field] = value_str
        
        if not to_save:
            return
        
        # Salva no hash Redis
        redis.hset(key, mapping=to_save)
        
        # Define TTL: se contém dados de tracker, usa TTL menor (24h), senão usa 7 dias
        has_tracker_data = 'tracker_seed' in to_save or 'tracker_leech' in to_save
        
        # Verifica se a chave já existe e qual TTL atual
        current_ttl = redis.ttl(key)
        
        if has_tracker_data:
            # TTL de 24h para dados de tracker (mudam frequentemente)
            # Se já existe e tem TTL maior, reduz para 24h
            if current_ttl == -1 or current_ttl > 24 * 3600:
                redis.expire(key, 24 * 3600)
        else:
            # TTL de 30 dias para outros campos (mais estáveis)
            # Só define se a chave não existe ou está expirando em menos de 30 dias
            if current_ttl == -1 or current_ttl < 30 * 24 * 3600:
                redis.expire(key, 30 * 24 * 3600)
    except Exception:
        pass


def get_field_from_cross_data(info_hash: str, field: str) -> Optional[str]:
    """
    Busca um campo específico dos dados cruzados no Redis.
    Retorna o valor do campo ou None se não encontrado.
    """
    cross_data = get_cross_data_from_redis(info_hash)
    if cross_data:
        value = cross_data.get(field)
        if value and value != 'N/A':
            return str(value) if not isinstance(value, bool) else ('true' if value else 'false')
    return None

