# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import re
from typing import List

def find_year_from_text(text: str, title: str) -> str:
    year_match = re.search(r'(?:Lançamento|Year):\s*.*?(\d{4})', text)
    if year_match:
        return year_match.group(1)
    
    year_match = re.search(r'\((\d{4})\)', title)
    if year_match:
        return year_match.group(1)
    
    return ''

def find_sizes_from_text(text: str) -> List[str]:
    sizes = re.findall(r'(\d+[\.,]?\d+)\s*(GB|MB)', text)
    return [f"{size[0]} {size[1]}" for size in sizes]

def format_bytes(size: int) -> str:
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    value = float(size)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"

