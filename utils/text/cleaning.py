"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import html
import re
from utils.text.constants import (
    RELEASE_CLEAN_REGEX,
    REGEX_MULTIPLE_SPACES,
    REGEX_MULTIPLE_DOTS,
    REGEX_LEADING_TRAILING_DOTS,
    REGEX_SPACE_AROUND_DOTS,
    REGEX_HTML_TAGS,
    REGEX_TITULO_TRADUZIDO_START,
    REGEX_TITULO_TRADUZIDO_MIDDLE,
    REGEX_ORDINAL_ENTITIES,
    REGEX_TEMPORADA_ORDINAL,
    REGEX_TEMPORADA_ORDINAL_ALT,
    REGEX_SEASON_EPISODE,
    REGEX_TEMPORADA_WORD,
    REGEX_TORRENT_WORD,
    REGEX_COMPLETA_NUMBER,
    REGEX_COMPLETA_WORD,
    REGEX_COMPLETA_STANDALONE,
    REGEX_AUDIO_WORDS,
    REGEX_SITE_WORDS,
)


# Remove acentos e cedilha de caracteres latinos e normaliza caracteres turcos
def remove_accents(text: str) -> str:
    replacements = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N',
        # Caracteres turcos
        'İ': 'I',  # I maiúsculo com ponto → I maiúsculo normal
        'ı': 'i',  # i minúsculo sem ponto → i minúsculo normal
        'ş': 's', 'Ş': 'S',
        'ğ': 'g', 'Ğ': 'G',
        'ü': 'u', 'Ü': 'U',
        'ö': 'o', 'Ö': 'O'
    }
    return ''.join(replacements.get(c, c) for c in text)


# Remove tags de sites, múltiplos espaços/pontos e normaliza o título
def clean_title(title: str) -> str:
    cleaned = RELEASE_CLEAN_REGEX.sub('', title)
    cleaned = REGEX_MULTIPLE_SPACES.sub(' ', cleaned)
    cleaned = REGEX_MULTIPLE_DOTS.sub('.', cleaned)
    cleaned = REGEX_LEADING_TRAILING_DOTS.sub('', cleaned)
    cleaned = REGEX_SPACE_AROUND_DOTS.sub('.', cleaned)
    return cleaned.strip()


def clean_title_translated_processed(title_translated_processed: str) -> str:
    # Limpa o título traduzido removendo tags HTML, temporadas, anos e textos extras
    if not title_translated_processed:
        return ''
    
    # Converte para string se não for
    title_translated_processed = str(title_translated_processed)
    
    # Remove todas as tags HTML (incluindo <strong>, <em>, <b>, <br />, <span>, <h1>, <title>, etc.)
    # Faz múltiplas passadas para garantir remoção completa
    while REGEX_HTML_TAGS.search(title_translated_processed):
        title_translated_processed = REGEX_HTML_TAGS.sub('', title_translated_processed)
    
    # Remove entidades HTML (como &ordf;, &nbsp;, &amp;, etc.)
    title_translated_processed = html.unescape(title_translated_processed)
    
    # Remove "Título Traduzido:" se ainda estiver presente (pode estar em diferentes formatos)
    title_translated_processed = REGEX_TITULO_TRADUZIDO_START.sub('', title_translated_processed)
    title_translated_processed = REGEX_TITULO_TRADUZIDO_MIDDLE.sub('', title_translated_processed)
    
    # Remove entidades HTML específicas de temporada (&ordf;, &ordm;, etc.) ANTES de remover temporada
    title_translated_processed = REGEX_ORDINAL_ENTITIES.sub('', title_translated_processed)
    title_translated_processed = html.unescape(title_translated_processed)  # Decodifica novamente após remover entidades
    
    # Remove informações de temporada (Sxx, Temporada, etc.) - múltiplos formatos
    # Remove padrões como "1ª Temporada", "2ª Temporada", "3ª Temporada", etc.
    title_translated_processed = REGEX_TEMPORADA_ORDINAL.sub('', title_translated_processed)
    title_translated_processed = REGEX_TEMPORADA_ORDINAL_ALT.sub('', title_translated_processed)
    title_translated_processed = REGEX_SEASON_EPISODE.sub('', title_translated_processed)
    title_translated_processed = REGEX_TEMPORADA_WORD.sub('', title_translated_processed)
    
    # Remove "Torrent" após temporada (ex: "2ª Temporada Torrent")
    title_translated_processed = REGEX_TORRENT_WORD.sub('', title_translated_processed)
    
    # Remove "Completa" ou "Completo" do título base
    # NOTA: "Completo/Completa" só faz sentido em séries (temporadas completas), não em filmes
    # Em filmes, apenas remove do título base. Em séries, será tratado como temporada completa depois
    # Remove quando está colada a número: "2Completa" -> "2" (será tratado como temporada completa se houver temporada)
    title_translated_processed = REGEX_COMPLETA_NUMBER.sub(r'\1', title_translated_processed)
    # Remove quando está colada ao título: "FatehCompleto" -> "Fateh" (filme, apenas remove)
    title_translated_processed = REGEX_COMPLETA_WORD.sub(r'\1', title_translated_processed)
    # Remove quando está separada: "Completa" ou "Completo" (standalone)
    title_translated_processed = REGEX_COMPLETA_STANDALONE.sub('', title_translated_processed)
    
    # Remove palavras relacionadas a áudio/legenda que serão substituídas por tags [Brazilian], [Eng], [Leg]
    # Remove DUBLADO, DUBLADO, NACIONAL, PORTUGUES (será substituído por [Brazilian])
    title_translated_processed = REGEX_AUDIO_WORDS.sub('', title_translated_processed)
    # Remove LEGENDADO, LEGENDA, LEG (será substituído por [Leg])
    title_translated_processed = re.sub(r'(?i)\b(?:Legendado|LEGENDADO|Legenda|LEGENDA|Leg|LEG)\b', '', title_translated_processed)
    # Remove DUAL (será substituído por [Brazilian] e [Eng])
    title_translated_processed = re.sub(r'(?i)\b(?:Dual|DUAL)\b', '', title_translated_processed)
    
    # Remove palavras comuns de sites que não fazem parte do título
    # Remove "Download", "Assistir", "Online", "Torrent" (já removido acima, mas garante)
    title_translated_processed = REGEX_SITE_WORDS.sub('', title_translated_processed)
    
    # Remove anos entre parênteses (ex: (2015-2025), (2025))
    title_translated_processed = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*', '', title_translated_processed)
    # Remove anos soltos no final (ex: "2025")
    title_translated_processed = re.sub(r'\s+(19|20)\d{2}\s*$', '', title_translated_processed)
    
    # Remove textos extras de sites (padrões genéricos)
    # Remove padrões como "2025 — Site Torrent – Baixe Filmes e Séries"
    title_translated_processed = re.sub(r'(?i)\s*—\s*[^—]+Torrent\s*–\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*—\s*[^—]+$', '', title_translated_processed)  # Remove "— Site Torrent – Baixe..."
    title_translated_processed = re.sub(r'(?i)\s*–\s*[^–]+$', '', title_translated_processed)  # Remove "– Baixe Filmes..."
    title_translated_processed = re.sub(r'(?i)\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*', '', title_translated_processed)
    
    # Remove campos que podem ter sido concatenados incorretamente
    # Remove "Titulo Original:" e tudo depois (com ou sem acento, com ou sem espaço antes)
    title_translated_processed = re.sub(r'(?i).*?T[íi]tulo\s+Original:.*$', '', title_translated_processed)
    # Remove "IMDb:" e tudo depois
    title_translated_processed = re.sub(r'(?i).*?IMDb:.*$', '', title_translated_processed)
    # Remove "Lançamento" e tudo depois
    title_translated_processed = re.sub(r'(?i).*?Lançamento.*$', '', title_translated_processed)
    
    # Remove palavras duplicadas consecutivas (ex: "FatehFateh" -> "Fateh", "Fateh Fateh" -> "Fateh")
    # Remove duplicações coladas (sem espaço)
    title_translated_processed = re.sub(r'([A-Za-z]+)\1+', r'\1', title_translated_processed, flags=re.IGNORECASE)
    # Remove duplicações com espaço (case-insensitive)
    words = title_translated_processed.split()
    if len(words) > 1:
        deduplicated_words = []
        prev_word_lower = None
        for word in words:
            word_lower = word.lower()
            if word_lower != prev_word_lower:
                deduplicated_words.append(word)
                prev_word_lower = word_lower
        title_translated_processed = ' '.join(deduplicated_words)
    
    # Remove caracteres especiais do final
    title_translated_processed = title_translated_processed.rstrip(' .,:;—–-')
    
    # Normaliza espaços
    title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
    
    return title_translated_processed

