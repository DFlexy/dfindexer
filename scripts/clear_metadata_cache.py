#!/usr/bin/env python3
"""Script para limpar cache de metadata e circuit breaker do Redis"""

import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cache.redis_client import get_redis_client

def clear_metadata_cache():
    """Limpa cache de metadata, falhas e circuit breaker"""
    redis = get_redis_client()
    
    if not redis:
        print("Redis não está disponível. Nada para limpar.")
        return
    
    try:
        # Limpa circuit breaker
        circuit_breaker_key = "metadata:circuit_breaker"
        if redis.exists(circuit_breaker_key):
            redis.delete(circuit_breaker_key)
            print("✓ Circuit breaker limpo")
        else:
            print("- Circuit breaker não estava ativo")
        
        # Limpa contadores do circuit breaker
        timeout_key = f"{circuit_breaker_key}:timeouts"
        error_503_key = f"{circuit_breaker_key}:503s"
        redis.delete(timeout_key)
        redis.delete(error_503_key)
        print("✓ Contadores do circuit breaker limpos")
        
        # Limpa cache de falhas (busca todas as chaves)
        failure_keys = []
        for key in redis.scan_iter(match="metadata:failure*"):
            failure_keys.append(key)
        
        if failure_keys:
            redis.delete(*failure_keys)
            print(f"✓ {len(failure_keys)} entradas de cache de falhas limpas")
        else:
            print("- Nenhuma entrada de cache de falhas encontrada")
        
        # Limpa cache de metadata (opcional - descomente se quiser limpar também)
        # metadata_keys = []
        # for key in redis.scan_iter(match="metadata:*"):
        #     metadata_keys.append(key)
        # if metadata_keys:
        #     redis.delete(*metadata_keys)
        #     print(f"✓ {len(metadata_keys)} entradas de cache de metadata limpas")
        
        print("\nCache limpo com sucesso!")
        
    except Exception as e:
        print(f"Erro ao limpar cache: {e}")
        sys.exit(1)

if __name__ == "__main__":
    clear_metadata_cache()

