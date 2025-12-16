"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from typing import List, Optional, TypeVar, Callable, Dict
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.text.constants import STOP_WORDS

logger = logging.getLogger(__name__)

# Tipo genérico para listas
T = TypeVar('T')

# Limite padrão de itens para query vazia (0 = ilimitado)
DEFAULT_MAX_ITEMS_FOR_TEST: int = 0

# Configurações de paralelização
DEFAULT_MAX_WORKERS = 16  # Máximo de workers simultâneos para processamento paralelo (aumentado de 8 para 16)
DEFAULT_PAGE_TIMEOUT = 60  # Timeout em segundos por página (aumentado de 45 para 60)


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


# Processa links em paralelo mantendo a ordem original para máxima performance
def process_links_parallel(
    links: List[str],
    process_func: Callable[[str], List[Dict]],
    effective_max: Optional[int],
    max_workers: Optional[int] = None,
    timeout: int = DEFAULT_PAGE_TIMEOUT,
    scraper_name: Optional[str] = None
) -> List[Dict]:
    # Remove duplicatas mantendo a ordem original
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    
    # Log se houver duplicatas removidas
    if len(links) != len(unique_links):
        duplicates_count = len(links) - len(unique_links)
        logger.debug(f"Removidas {duplicates_count} duplicatas de links")
    
    links = unique_links
    
    # Se não há links, retorna vazio
    if not links:
        return []
    
    # Obtém max_workers da configuração se não fornecido
    if max_workers is None:
        try:
            from app.config import Config
            max_workers = Config.SCRAPER_MAX_WORKERS if hasattr(Config, 'SCRAPER_MAX_WORKERS') else DEFAULT_MAX_WORKERS
        except Exception:
            max_workers = DEFAULT_MAX_WORKERS
    
    # Salva a ordem original dos links (índice -> link)
    original_order = list(links)  # Cópia da lista original na ordem correta
    total_links = len(original_order)
    
    # Prefixo do scraper para logs
    scraper_prefix = f"[{scraper_name}] " if scraper_name else ""
    
    # Log da ordem original dos links (DEBUG) - índices começam do 1
    logger.debug(f"{scraper_prefix}Processando {total_links} links em paralelo. Ordem original:")
    for idx, link in enumerate(original_order):
        link_short = link.split('/')[-2] if '/' in link else link[-50:]
        logger.debug(f"{scraper_prefix}[{idx+1}] {link_short}")
    
    # Cria mapeamento de link -> índice original para manter ordem
    link_to_index = {link: idx for idx, link in enumerate(original_order)}
    
    # Dicionário para armazenar resultados por índice (para reordenar depois)
    results_by_index: Dict[int, List[Dict]] = {}
    
    # SEMPRE paraleliza (mesmo com 1 link) - overhead mínimo, consistência máxima
    # Ajusta workers baseado na quantidade de links (mínimo 1, máximo max_workers)
    actual_max_workers = min(max(1, total_links), max_workers)
    
    with ThreadPoolExecutor(max_workers=actual_max_workers) as executor:
        # Submete todas as tarefas
        future_to_link = {
            executor.submit(process_func, link): link
            for link in original_order
        }
        
        # Processa todos os links (não para por limite de torrents - limite já foi aplicado nos links)
        for future in as_completed(future_to_link):
            link = future_to_link[future]
            original_index = link_to_index[link]
            
            try:
                torrents = future.result(timeout=timeout)
                results_by_index[original_index] = torrents
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
                link_preview = link[:50] if link else 'N/A'
                logger.warning(f"{scraper_prefix}Page error [{original_index+1}]: {error_type} - {error_msg} (link: {link_preview}...)")
                # Armazena lista vazia para manter ordem mesmo em caso de erro
                results_by_index[original_index] = []
    
    # Reordena resultados pela ordem original dos links (garante ordem correta)
    all_torrents = []
    for idx in range(total_links):
        if idx in results_by_index:
            torrents = results_by_index[idx]
            # Marca cada torrent com o índice original para debug
            for t in torrents:
                t['_original_order'] = idx
            all_torrents.extend(torrents)
    
    # Log INFO na ordem correta (após reordenação) - índices começam do 1
    logger.info(f"{scraper_prefix}Processamento completo: {len(all_torrents)} torrents de {total_links} links. Páginas processadas na ordem:")
    for idx in range(total_links):
        if idx in results_by_index:
            link = original_order[idx]
            link_short = link.split('/')[-2] if '/' in link else link[-50:]
            torrents_count = len(results_by_index[idx])
            logger.info(f"{scraper_prefix}Página processada [{idx+1}/{total_links}]: {link_short} - {torrents_count} magnets encontrados")
    
    return all_torrents


# Processa links sequencialmente mantendo a ordem original - sempre loga o processamento de cada página
def process_links_sequential(
    links: List[str],
    process_func: Callable[[str], List[Dict]],
    effective_max: Optional[int]
) -> List[Dict]:
    # Remove duplicatas mantendo a ordem original
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    
    # Log se houver duplicatas removidas
    if len(links) != len(unique_links):
        duplicates_count = len(links) - len(unique_links)
    
    links = unique_links
    all_torrents = []
    
    for link in links:
        torrents = process_func(link)
        all_torrents.extend(torrents)
        logger.info(f"Página processada: {link} - {len(torrents)} magnets encontrados")
        
        # Para quando tiver resultados suficientes (se houver limite)
        if should_stop_processing(len(all_torrents), effective_max):
            break
    
    return all_torrents

