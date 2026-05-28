# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

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
        'İ': 'I',
        'ı': 'i',
        'ş': 's', 'Ş': 'S',
        'ğ': 'g', 'Ğ': 'G',
        'ü': 'u', 'Ü': 'U',
        'ö': 'o', 'Ö': 'O'
    }
    return ''.join(replacements.get(c, c) for c in text)

def clean_title(title: str) -> str:
    cleaned = RELEASE_CLEAN_REGEX.sub('', title)
    cleaned = REGEX_MULTIPLE_SPACES.sub(' ', cleaned)
    cleaned = REGEX_MULTIPLE_DOTS.sub('.', cleaned)
    cleaned = REGEX_LEADING_TRAILING_DOTS.sub('', cleaned)
    cleaned = REGEX_SPACE_AROUND_DOTS.sub('.', cleaned)
    cleaned = re.sub(r'^(MKV|MP4|AVI|MPEG|MOV)\.', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip('.')
    return cleaned.strip()

def clean_title_translated_processed(title_translated_processed: str) -> str:
    if not title_translated_processed:
        return ''
    
    title_translated_processed = str(title_translated_processed)
    
    while REGEX_HTML_TAGS.search(title_translated_processed):
        title_translated_processed = REGEX_HTML_TAGS.sub('', title_translated_processed)
    
    title_translated_processed = html.unescape(title_translated_processed)
    
    title_translated_processed = REGEX_TITULO_TRADUZIDO_START.sub('', title_translated_processed)
    title_translated_processed = REGEX_TITULO_TRADUZIDO_MIDDLE.sub('', title_translated_processed)
    
    title_translated_processed = REGEX_ORDINAL_ENTITIES.sub('', title_translated_processed)
    title_translated_processed = html.unescape(title_translated_processed)
    
    title_translated_processed = REGEX_TEMPORADA_ORDINAL.sub('', title_translated_processed)
    title_translated_processed = REGEX_TEMPORADA_ORDINAL_ALT.sub('', title_translated_processed)
    title_translated_processed = REGEX_SEASON_EPISODE.sub('', title_translated_processed)
    title_translated_processed = REGEX_TEMPORADA_WORD.sub('', title_translated_processed)
    
    title_translated_processed = REGEX_TORRENT_WORD.sub('', title_translated_processed)
    
    title_translated_processed = REGEX_COMPLETA_NUMBER.sub(r'\1', title_translated_processed)
    title_translated_processed = REGEX_COMPLETA_WORD.sub(r'\1', title_translated_processed)
    title_translated_processed = REGEX_COMPLETA_STANDALONE.sub('', title_translated_processed)
    
    title_translated_processed = REGEX_AUDIO_WORDS.sub('', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\b(?:Legendado|LEGENDADO|Legenda|LEGENDA|Leg|LEG)\b', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\b(?:Dual|DUAL)(?![\.\s]?(?:5\.1|2\.0|7\.1))\b', '', title_translated_processed)
    
    title_translated_processed = REGEX_SITE_WORDS.sub('', title_translated_processed)
    
    title_translated_processed = re.sub(r'\s*\([0-9]{4}(?:-[0-9]{4})?\)\s*', '', title_translated_processed)
    title_translated_processed = re.sub(r'\s+(19|20)\d{2}\s*$', '', title_translated_processed)
    
    title_translated_processed = re.sub(r'(?i)\s*—\s*[^—]+Torrent\s*–\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*—\s*[^—]+$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*–\s*[^–]+$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i)\s*Baixe\s+Filmes\s+e\s+S[ée]ries\s*', '', title_translated_processed)
    
    title_translated_processed = re.sub(r'(?i).*?T[íi]tulo\s+Original:.*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i).*?IMDb:.*$', '', title_translated_processed)
    title_translated_processed = re.sub(r'(?i).*?Lançamento.*$', '', title_translated_processed)
    
    title_translated_processed = re.sub(r'([A-Za-z]+)\1+', r'\1', title_translated_processed, flags=re.IGNORECASE)
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
    
    title_translated_processed = title_translated_processed.rstrip(' .,:;—–-')
    
    title_translated_processed = re.sub(r'\s+', ' ', title_translated_processed).strip()
    
    return title_translated_processed

