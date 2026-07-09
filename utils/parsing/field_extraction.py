# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

"""Extração de campos rotulados (Título Original, Título Traduzido, etc.) de HTML.

Suporta variações de marcação usadas pelos sites brasileiros de torrent:
  <b>Título Original:</b> Valor
  <b>Título Original</b>: Valor
  <strong>Título Traduzido</strong>: Valor
  Título Traduzido: Valor  (texto puro)
"""
import html
import re
from typing import List

_RE_LABELED_FIELD_VARIANTS = (
    r'(?i)(?:<b>|<strong>)\s*{label}\s*(?:</b>|</strong>)\s*:\s*([^<\n\r]+)',
    r'(?i)(?:<b>|<strong>)\s*{label}\s*:\s*(?:</b>|</strong>)\s*([^<\n\r]+)',
    r'(?i){label}\s*:\s*([^<\n\r]+)',
)


def extract_labeled_value(html_content: str, labels: List[str]) -> str:
    """Extrai o valor de um campo rotulado do HTML.

    `labels`: lista de rótulos candidatos (ex.: ['Título Original', 'Titulo Original']).
    Retorna string vazia se nenhum rótulo for encontrado.
    """
    for label in labels:
        for variant in _RE_LABELED_FIELD_VARIANTS:
            pattern = variant.replace('{label}', re.escape(label))
            match = re.search(pattern, html_content)
            if match:
                value = match.group(1).strip()
                value = re.sub(r'<[^>]+>', '', value)
                return html.unescape(value).strip()
    return ''


def extract_labeled_value_from_text(
    text: str, labels: List[str], stop_words: List[str]
) -> str:
    """Fallback em texto puro: split no rótulo e trunca no primeiro stop_word."""
    for label in labels:
        for variant in (f'{label}:', f'{label} :'):
            if variant not in text:
                continue
            title_part = text.split(variant, 1)[1].strip()
            for stop_word in stop_words:
                if stop_word in title_part:
                    title_part = title_part[:title_part.index(stop_word)]
                    break
            lines = title_part.split('\n')
            if lines:
                return lines[0].strip()
    return ''
