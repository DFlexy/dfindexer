"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import re
from datetime import datetime
from typing import Optional


# Extrai data de uma string usando padrões comuns
def parse_date_from_string(date_str: str) -> Optional[datetime]:
    patterns = [
        (r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),
        (r'\d{2}-\d{2}-\d{4}', '%d-%m-%Y'),
        (r'\d{2}/\d{2}/\d{4}', '%d/%m/%Y'),
        (r'\d{1,2},? [A-Za-z]+', '%d, %B'),  # 4, October
        (r'[A-Za-z]+ \d{1,2},? \d{4}', '%B %d, %Y'),  # October 4, 2020
    ]
    
    for pattern, fmt in patterns:
        match = re.search(pattern, date_str)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    
    return None

