"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from typing import List
from urllib.parse import quote

from utils.text_processing import STOP_WORDS


def generate_search_variations(query: str, include_stop_words_removal: bool = True) -> List[str]:
    """
    Gera variações de uma query para busca, removendo stop words e usando primeira palavra.
    
    Args:
        query: Query original
        include_stop_words_removal: Se True, inclui variação sem stop words
        
    Returns:
        Lista de variações da query (incluindo a original)
    """
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


def build_search_url(base_url: str, search_path: str, query: str) -> str:
    """
    Constrói URL de busca formatada.
    
    Args:
        base_url: URL base do site
        search_path: Caminho de busca (ex: "?s=" ou "index.php?s=")
        query: Query de busca
        
    Returns:
        URL completa de busca
    """
    query_encoded = quote(query)
    return f"{base_url}{search_path}{query_encoded}"

