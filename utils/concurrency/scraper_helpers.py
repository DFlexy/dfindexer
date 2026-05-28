# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
from typing import List, Optional, TypeVar, Callable, Dict
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.text.constants import STOP_WORDS

logger = logging.getLogger(__name__)

T = TypeVar('T')

DEFAULT_MAX_ITEMS_FOR_TEST: int = 0

# Configurações de paralelização
DEFAULT_MAX_WORKERS = 16
DEFAULT_PAGE_TIMEOUT = 30

def format_page_index(current: int) -> str:
    return f"{current:02d}"

def format_page_progress(current: int, total: int) -> str:
    return f"{format_page_index(current)}/{format_page_index(total)}"

def generate_search_variations(query: str, include_stop_words_removal: bool = True) -> List[str]:
    variations = [query]
    
    if include_stop_words_removal:
        words = [w for w in query.split() if w.lower() not in STOP_WORDS]
        if words and ' '.join(words) != query:
            variations.append(' '.join(words))
    
    query_words = query.split()
    if len(query_words) > 1:
        first_word = query_words[0].lower()
        if first_word not in STOP_WORDS:
            variations.append(query_words[0])
    
    return variations

def normalize_query_for_flaresolverr(query: str, use_flaresolverr: bool) -> str:
    if use_flaresolverr and ':' in query:
        return query.replace(':', ' ')
    return query

def build_search_url(base_url: str, search_path: str, query: str) -> str:
    query_encoded = quote(query)
    return f"{base_url}{search_path}{query_encoded}"

def get_effective_max_items(max_items: Optional[int], default_max: int = DEFAULT_MAX_ITEMS_FOR_TEST) -> int:
    if max_items is not None:
        return max_items
    return default_max

def limit_list(items: List[T], max_items: int) -> List[T]:
    if max_items > 0:
        return items[:max_items]
    return items

def should_stop_processing(current_count: int, max_items: Optional[int]) -> bool:
    if max_items is None or max_items == 0:
        return False
    return current_count >= max_items

def build_page_url(base_url: str, page_pattern: str, page: str) -> str:
    if page == '1':
        return base_url
    return f"{base_url}{page_pattern.format(page)}"

def process_links_parallel(
    links: List[str],
    process_func: Callable[[str], List[Dict]],
    effective_max: Optional[int],
    max_workers: Optional[int] = None,
    timeout: int = DEFAULT_PAGE_TIMEOUT,
    scraper_name: Optional[str] = None,
    use_flaresolverr: bool = False
) -> List[Dict]:
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    
    if len(links) != len(unique_links):
        duplicates_count = len(links) - len(unique_links)
        logger.debug(f"Removidas {duplicates_count} duplicatas de links")
    
    links = unique_links
    
    if not links:
        return []
    
    original_order = list(links)
    total_links = len(original_order)
    
    scraper_prefix = f"[{scraper_name}] " if scraper_name else ""
    
    results_by_index: Dict[int, List[Dict]] = {}
    
    if use_flaresolverr:
        logger.debug(f"{scraper_prefix}Processando {total_links} links SEQUENCIALMENTE (FlareSolverr ativo)")
        for idx, link in enumerate(original_order):
            logger.debug(f"{scraper_prefix}[{format_page_index(idx + 1)}] {link}")
            try:
                torrents = process_func(link)
                results_by_index[idx] = torrents
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
                logger.warning(f"{scraper_prefix}Page error [{format_page_index(idx + 1)}]: {error_type} - {error_msg}")
                results_by_index[idx] = []
    else:
        if max_workers is None:
            try:
                from app.config import Config
                max_workers = Config.SCRAPER_MAX_WORKERS if hasattr(Config, 'SCRAPER_MAX_WORKERS') else DEFAULT_MAX_WORKERS
            except Exception:
                max_workers = DEFAULT_MAX_WORKERS
        
        logger.debug(f"{scraper_prefix}Processando {total_links} links em PARALELO")
        for idx, link in enumerate(original_order):
            logger.debug(f"{scraper_prefix}[{format_page_index(idx + 1)}] {link}")
        
        link_to_index = {link: idx for idx, link in enumerate(original_order)}
        actual_max_workers = min(max(1, total_links), max_workers)
        
        with ThreadPoolExecutor(max_workers=actual_max_workers) as executor:
            future_to_link = {
                executor.submit(process_func, link): link
                for link in original_order
            }
            
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
                    logger.warning(
                        f"{scraper_prefix}Page error [{format_page_index(original_index + 1)}]: "
                        f"{error_type} - {error_msg} (link: {link_preview}...)"
                    )
                    results_by_index[original_index] = []
    
    all_torrents = []
    for idx in range(total_links):
        if idx in results_by_index:
            torrents = results_by_index[idx]
            for t in torrents:
                t['_original_order'] = idx
            all_torrents.extend(torrents)
    
    logger.info(f"{scraper_prefix}Processamento completo: {len(all_torrents)} torrents de {total_links} links. Páginas processadas na ordem:")
    for idx in range(total_links):
        if idx in results_by_index:
            link = original_order[idx]
            torrents_count = len(results_by_index[idx])
            logger.info(
                f"{scraper_prefix}Página processada [{format_page_progress(idx + 1, total_links)}]: "
                f"{link} - {torrents_count} magnets encontrados"
            )
    
    return all_torrents

def process_links_sequential(
    links: List[str],
    process_func: Callable[[str], List[Dict]],
    effective_max: Optional[int]
) -> List[Dict]:
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    
    if len(links) != len(unique_links):
        duplicates_count = len(links) - len(unique_links)
    
    links = unique_links
    all_torrents = []
    
    for link in links:
        torrents = process_func(link)
        all_torrents.extend(torrents)
        logger.info(f"Página processada: {link} - {len(torrents)} magnets encontrados")
        
        if should_stop_processing(len(all_torrents), effective_max):
            break
    
    return all_torrents

