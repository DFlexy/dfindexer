"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re

from utils.text.constants import STOP_WORDS
from utils.text.cleaning import remove_accents


# Confere se o resultado corresponde à busca (ignorando stop words)
def check_query_match(query: str, title: str, original_title_html: str = '', translated_title_html: str = '') -> bool:
    if not query or not query.strip():
        return True  # Query vazia, não filtra
    
    # Normaliza query: remove stop words
    query_lower = query.lower().strip()
    query_words = query_lower.split()
    
    # Remove stop words e palavras muito curtas
    clean_query_words = []
    for word in query_words:
        # Remove caracteres não-alfabéticos e não-numéricos para limpeza básica
        clean_word = re.sub(r'[^a-zA-Z0-9]', '', word)
        # Mantém palavras com pelo menos 1 caractere (aceita letras únicas como "v" em "gen v")
        # e que não sejam stop words
        if len(clean_word) >= 1 and clean_word.lower() not in STOP_WORDS:
            clean_query_words.append(clean_word.lower())
    
    if len(clean_query_words) == 0:
        return True  # Se não tem palavras válidas, retorna True (não filtra)
    
    # Identifica a primeira palavra de título (não numérica ou número com 3+ dígitos)
    first_title_word = None
    for word in clean_query_words:
        if not word.isdigit():
            first_title_word = word
            break
        elif len(word) >= 3:  # Números com 3+ dígitos (ex: 007, 2001) são considerados título
            first_title_word = word
            break
    
    # Combina título + título original + título traduzido para busca
    combined_title = f"{title} {original_title_html} {translated_title_html}".lower()
    # Remove pontos e normaliza espaços
    combined_title = combined_title.replace('.', ' ')
    combined_title = re.sub(r'\s+', ' ', combined_title)
    
    # Remove acentos para comparação
    combined_title = remove_accents(combined_title)
    
    # VALIDAÇÃO DE EPISÓDIO: Se a query contém SxxExx, valida se o título contém o mesmo episódio
    # Extrai padrão SxxExx da query original (antes de normalizar)
    query_episode_match = re.search(r'(?i)s(\d{1,2})e(\d{1,2})', query)
    if query_episode_match:
        query_season = query_episode_match.group(1).zfill(2)
        query_episode_num = int(query_episode_match.group(2))
        
        # Busca padrão SxxExx no título (aceita pontos, espaços, hífens)
        # Suporta formatos: S02E05, S02E05-06, S02E05E06E07, S02E05-E07
        title_season_ep_pattern = rf'(?i)s{query_season}e(\d{{1,2}})(?:[\.\-\sE]|$)'
        title_season_ep_match = re.search(title_season_ep_pattern, title)
        
        if not title_season_ep_match:
            # Não encontrou o padrão SxxExx no título, rejeita
            return False
        
        # Extrai todos os episódios do título
        # Busca padrão completo: S02E05, S02E05-06, S02E05E06E07, S02E05-E07
        # Busca o padrão SxxE seguido de números (suporta pontos, hífens, espaços, E)
        episode_pattern = rf'(?i)s{query_season}e(\d{{1,2}})(?:[\.\-\sE]+(\d{{1,2}}))*'
        episode_match = re.search(episode_pattern, title)
        episodes_in_title = []
        
        if episode_match:
            # Primeiro episódio
            first_ep = int(episode_match.group(1))
            episodes_in_title = [first_ep]
            
            # Extrai todos os números de episódio do match completo
            # Busca todos os números após o primeiro episódio (suporta hífen, ponto, E, espaço)
            match_text = episode_match.group(0)
            # Remove o primeiro episódio do texto para buscar apenas os subsequentes
            first_ep_str = episode_match.group(1)
            remaining_text = match_text[len(f's{query_season}e{first_ep_str}'):]
            episode_numbers = re.findall(r'(\d{1,2})', remaining_text)
            
            for ep_str in episode_numbers:
                try:
                    ep_num = int(ep_str)
                    # Adiciona apenas se for maior que o último (evita duplicatas)
                    if ep_num > episodes_in_title[-1]:
                        episodes_in_title.append(ep_num)
                except (ValueError, TypeError):
                    break
        else:
            # Não encontrou padrão válido, rejeita
            return False
        
        # Valida se o episódio da query corresponde aos episódios do título
        if len(episodes_in_title) == 1:
            # Episódio único: deve corresponder exatamente
            if episodes_in_title[0] != query_episode_num:
                return False
        else:
            # Múltiplos episódios: verifica se o episódio da query está na lista ou no intervalo
            if query_episode_num not in episodes_in_title:
                # Verifica se está em um intervalo (ex: S02E05-E07, query é E06)
                if len(episodes_in_title) >= 2:
                    start_ep = episodes_in_title[0]
                    end_ep = episodes_in_title[-1]
                    if not (start_ep <= query_episode_num <= end_ep):
                        return False
                else:
                    return False
    
    # Conta quantas palavras da query estão presentes no título
    matches = 0
    matched_words = []  # Rastreia quais palavras fizeram match
    first_title_word_matched = False
    
    for query_word in clean_query_words:
        query_word_no_accent = remove_accents(query_word)
        
        # Verifica match como palavra completa usando regex com word boundaries
        pattern = r'\b' + re.escape(query_word_no_accent) + r'\b'
        if re.search(pattern, combined_title, re.IGNORECASE):
            matches += 1
            matched_words.append(query_word)
            if query_word == first_title_word:
                first_title_word_matched = True
            continue
        
        # Se não encontrou como palavra completa, tenta match parcial no início de palavras
        # Isso resolve casos como "Ranma" encontrando "Ranma12" ou "Ranma1/2"
        # Usa lookahead para garantir que é o início de uma palavra (seguido de letra/número)
        partial_pattern = r'\b' + re.escape(query_word_no_accent) + r'(?=[a-zA-Z0-9])'
        if re.search(partial_pattern, combined_title, re.IGNORECASE):
            matches += 1
            matched_words.append(query_word)
            if query_word == first_title_word:
                first_title_word_matched = True
            continue

        # Trata casos de temporada: query "1" deve encontrar "S1"/"S01"
        if query_word_no_accent.isdigit():
            season_patterns = [f"s{query_word_no_accent}", f"s{query_word_no_accent.zfill(2)}"]
            if any(sp in combined_title for sp in season_patterns):
                matches += 1
                matched_words.append(query_word)

         
    # Verifica se o ano corresponde (importante para filmes)
    year_in_query = None
    for word in clean_query_words:
        if word.isdigit() and len(word) == 4 and word.startswith(('19', '20')):
            year_in_query = word
            break
    
    year_in_title = False
    if year_in_query:
        # Verifica ano no título (aceita pontos ou espaços ao redor, já que pontos foram convertidos para espaços)
        year_pattern = r'\b' + re.escape(year_in_query) + r'\b'
        if re.search(year_pattern, combined_title):
            year_in_title = True
    
    # REGRA CRÍTICA: Se existe uma palavra de título na query, ELA DEVE fazer match
    # Isso evita que apenas ano+temporada passem resultados irrelevantes
    # EXCEÇÃO: Para queries de 1 palavra, não exige que seja a primeira palavra (permite match em qualquer lugar)
    if len(clean_query_words) > 1 and first_title_word and not first_title_word_matched:
        return False
    
    # Lógica de correspondência:
    # - 1 palavra: exige que corresponda (não precisa ser primeira palavra)
    # - 2 palavras: exige que ambas correspondam
    # - 3+ palavras: exige que pelo menos 2 correspondam E a primeira palavra de título corresponda (já verificado acima)
    if len(clean_query_words) == 1:
        return matches == 1
    elif len(clean_query_words) == 2:
        return matches == 2
    else:
        # Para 3+ palavras: verifica se há match de pelo menos uma palavra de TÍTULO (não ano, não temporada)
        has_title_match = False
        for word in matched_words:
            # Palavra de título = não é ano (4 dígitos 19xx/20xx) e não é temporada (1-2 dígitos)
            if not word.isdigit():
                has_title_match = True
                break
            elif len(word) >= 3:  # Números com 3+ dígitos (ex: 007, 2001) são considerados título
                has_title_match = True
                break
        
        # Para queries longas (5+ palavras), é mais flexível: prioriza as primeiras palavras
        # Aceita se as primeiras 2-3 palavras fizeram match (mais relevantes) OU se pelo menos 30% fizeram match
        total_words = len(clean_query_words)
        if total_words >= 5:
            # Verifica se as primeiras palavras importantes (não numéricas) fizeram match
            # Pega as primeiras 4 palavras (ou menos se a query for menor)
            first_words_to_check = clean_query_words[:min(4, total_words)]
            first_words_matches = sum(1 for w in first_words_to_check if w in matched_words)
            
            # Aceita se pelo menos 2 das primeiras palavras fizeram match
            # OU se pelo menos 30% do total fizeram match
            min_matches_percent = max(2, int(total_words * 0.3))
            if first_words_matches >= 2 or matches >= min_matches_percent:
                # Se o ano corresponde e há matches suficientes E pelo menos 1 é palavra de título, aceita
                if year_in_title and has_title_match:
                    return True
                # Caso contrário, exige pelo menos 1 palavra de título
                return has_title_match
            
            return False
        
        # Para queries menores (3-4 palavras): mantém lógica original
        # Se o ano corresponde e há pelo menos 2 matches E pelo menos 1 é palavra de título, aceita
        if year_in_title and matches >= 2 and has_title_match:
            return True
        # Caso contrário, exige pelo menos 2 correspondências E pelo menos 1 palavra de título
        return matches >= 2 and has_title_match

