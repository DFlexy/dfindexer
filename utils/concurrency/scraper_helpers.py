"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Optional, TypeVar, Callable, Dict
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.text.text_processing import STOP_WORDS

logger = logging.getLogger(__name__)

# Tipo genérico para listas
T = TypeVar('T')

# Limite padrão de itens para testes do Prowlarr (0 = ilimitado)
DEFAULT_MAX_ITEMS_FOR_TEST: int = 0

# Configurações de paralelização
DEFAULT_MAX_WORKERS = 4  # Máximo de workers simultâneos para processamento paralelo
DEFAULT_PAGE_TIMEOUT = 30  # Timeout em segundos por página


# Gera variações de uma query para busca, removendo stop words e usando primeira palavra
def generate_search_variations(query: str, include_stop_words_removal: bool = True) -> List[str]:
    variations = [query]
    
    # Remove stop words
    if include_stop_words_removal:
        words = [w for w in query.split() if w.lower() not in STOP_WORDS]
        if words and ' '.join(words) != query:
            variations.append(' '.join(words))
    
    # Primeira palavra (se não for stop word)
    query_words = query.split()
    if len(query_words) > 1:
        first_word = query_words[0].lower()
        if first_word not in STOP_WORDS:
            variations.append(query_words[0])
    
    return variations


# Normaliza query quando FlareSolverr está habilitado - substitui dois pontos por espaço para evitar problemas com URLs codificadas (%3A)
def normalize_query_for_flaresolverr(query: str, use_flaresolverr: bool) -> str:
    if use_flaresolverr and ':' in query:
        return query.replace(':', ' ')
    return query


# Constrói URL de busca formatada
def build_search_url(base_url: str, search_path: str, query: str) -> str:
    query_encoded = quote(query)
    return f"{base_url}{search_path}{query_encoded}"


# Retorna o limite efetivo de itens a processar
def get_effective_max_items(max_items: Optional[int], default_max: int = DEFAULT_MAX_ITEMS_FOR_TEST) -> int:
    if max_items is not None:
        return max_items
    return default_max  # 0 = ilimitado


# Limita uma lista de itens se houver um limite definido
def limit_list(items: List[T], max_items: int) -> List[T]:
    if max_items > 0:
        return items[:max_items]
    return items


# Verifica se deve parar o processamento baseado no limite
def should_stop_processing(current_count: int, max_items: Optional[int]) -> bool:
    if max_items is None or max_items == 0:
        return False
    return current_count >= max_items


# Constrói URL da página baseado no padrão
def build_page_url(base_url: str, page_pattern: str, page: str) -> str:
    if page == '1':
        return base_url
    return f"{base_url}{page_pattern.format(page)}"


# Processa links em paralelo ou sequencialmente dependendo da quantidade
def process_links_parallel(
    links: List[str],
    process_func: Callable[[str], List[Dict]],
    effective_max: Optional[int],
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: int = DEFAULT_PAGE_TIMEOUT
) -> List[Dict]:
    all_torrents = []
    
    if len(links) > 1:
        # Paraleliza quando há múltiplas páginas
        max_workers = min(max_workers, len(links))
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_link = {
                executor.submit(process_func, link): link
                for link in links
            }
            
            for future in as_completed(future_to_link):
                link = future_to_link[future]
                try:
                    torrents = future.result(timeout=timeout)
                    all_torrents.extend(torrents)
                    logger.info(f"Página processada: {link} - {len(torrents)} magnets encontrados")
                    # Para quando tiver resultados suficientes (se houver limite)
                    if should_stop_processing(len(all_torrents), effective_max):
                        # Cancela tarefas pendentes
                        for f in future_to_link:
                            f.cancel()
                        break
                except Exception as e:
                    logger.warning(f"Erro ao processar página {link}: {e}")
    else:
        # Processa sequencialmente se houver apenas 1 link
        for link in links:
            torrents = process_func(link)
            all_torrents.extend(torrents)
            logger.info(f"Página processada: {link} - {len(torrents)} magnets encontrados")
            if should_stop_processing(len(all_torrents), effective_max):
                break
    
    return all_torrents


# Processa links sequencialmente mantendo a ordem original - sempre loga o processamento de cada página
def process_links_sequential(
    links: List[str],
    process_func: Callable[[str], List[Dict]],
    effective_max: Optional[int]
) -> List[Dict]:
    all_torrents = []
    
    for link in links:
        torrents = process_func(link)
        all_torrents.extend(torrents)
        logger.info(f"Página processada: {link} - {len(torrents)} magnets encontrados")
        
        # Para quando tiver resultados suficientes (se houver limite)
        if should_stop_processing(len(all_torrents), effective_max):
            break
    
    return all_torrents

