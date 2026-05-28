# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re

STOP_WORDS = [
    'the', 'my', 'a', 'an', 'and', 'of', 'to', 'in', 'for', 'or', 'as',
    'os', 'o', 'e', 'de', 'do', 'da', 'em', 'que', 'temporada', 'season',
    'gli', 'dei', 'del', 'della', 'delle', 'degli', 'dello', 'dall', 'dalla', 'dalle', 'dallo', 'dall\'',
    'los', 'las', 'del', 'de', 'el', 'la',
    'les', 'des', 'du', 'de', 'le', 'la'
]

RELEASE_CLEAN_REGEX = re.compile(
    r'(?i)(COMANDO\.TO|COMANDOTORRENTS|WWW\.BLUDV\.TV|BLUDV|WWW\.COMANDOTORRENTS|'
    r'TORRENTBR|BAIXEFILMES|\[EZTVx\.to\]|\[TGx\]|\[rartv\]|\[YTS\.MX\]|'
    r'TRUFFLE|ETHEL|FLUX|GalaxyRG|TOONSHUB|ERAI\.RAWS|HIDRATORRENTS\.ORG|NETFLIX|'
    r'WWW\.[A-Z0-9.-]+\.[A-Z]{2,}|\[ACESSE[^\]]*\])\s*-?\s*'
)

REGEX_MULTIPLE_SPACES = re.compile(r'\s+')
REGEX_MULTIPLE_DOTS = re.compile(r'\.{2,}')
REGEX_LEADING_TRAILING_DOTS = re.compile(r'^\.|\.$')
REGEX_SPACE_AROUND_DOTS = re.compile(r'\s*\.\s*')
REGEX_HTML_TAGS = re.compile(r'<[^>]+>')
REGEX_TITULO_TRADUZIDO_START = re.compile(r'(?i)^\s*T[íi]tulo\s+Traduzido\s*:?\s*')
REGEX_TITULO_TRADUZIDO_MIDDLE = re.compile(r'(?i)\s*T[íi]tulo\s+Traduzido\s*:?\s*')
REGEX_ORDINAL_ENTITIES = re.compile(r'&ord[fm];', re.IGNORECASE)
REGEX_TEMPORADA_ORDINAL = re.compile(r'(?i)\s*[0-9]+[ªº]\s*Temporada\s*')
REGEX_TEMPORADA_ORDINAL_ALT = re.compile(r'(?i)\s*[0-9]+[aªº]\s*Temporada\s*')
REGEX_SEASON_EPISODE = re.compile(r'(?i)\s*S\d{1,2}(?:E\d{1,2})?\s*')
REGEX_TEMPORADA_WORD = re.compile(r'(?i)\s*Temporada\s*')
REGEX_TORRENT_WORD = re.compile(r'(?i)\s*Torrent\s*')
REGEX_COMPLETA_NUMBER = re.compile(r'(\d+)\s*Complet[ao]\b', re.IGNORECASE)
REGEX_COMPLETA_WORD = re.compile(r'([A-Za-z]+)Complet[ao]\b', re.IGNORECASE)
REGEX_COMPLETA_STANDALONE = re.compile(r'\bComplet[ao]\b', re.IGNORECASE)
REGEX_AUDIO_WORDS = re.compile(r'(?i)\b(?:Dublado|DUBLADO|Nacional|NACIONAL|Portugues|PORTUGUES|Português|PORTUGUÊS)\b')
REGEX_SITE_WORDS = re.compile(r'(?i)\b(?:Download|DOWNLOAD|Assistir|ASSISTIR|Online|ONLINE|ou|OU|e|E)\b')
REGEX_DUPLICATE_WORDS = re.compile(r'\b(\w+)\s+\1\b', re.IGNORECASE)
REGEX_YEAR_PARENTHESES = re.compile(r'\s*\(((?:19|20)\d{2}(?:-\d{2})?)\)\s*')
REGEX_YEAR_END = re.compile(r'\s+(19|20)\d{2}\s*$')
REGEX_YEAR_IN_TITLE = re.compile(r'(19|20)\d{2}')
REGEX_SEASON_EPISODE_PATTERN = re.compile(r'(?i)S(\d{1,2})E(\d{1,2})')
REGEX_SEASON_ONLY_PATTERN = re.compile(r'(?i)S(\d{1,2})(?![E\d])')
REGEX_BRACKETS_CONTENT = re.compile(r'\[.*?\]')
REGEX_PARENTHESES_CONTENT = re.compile(r'\s*\([^)]*\)\s*')
REGEX_NON_LATIN_CHARS = re.compile(
    r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u0400-\u04ff\u0e00-\u0e7f'
    r'\u0900-\u09ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0c00-\u0c7f\u0b80-\u0bff'
    r'\u0c80-\u0cff\u0d00-\u0d7f\u0a80-\u0aff\u0b00-\u0b7f]'
)

