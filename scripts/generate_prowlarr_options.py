#!/usr/bin/env python3
"""Imprime o bloco `options` do scraper_type para colar no prowlarr.yml."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.prowlarr_config import PROWLARR_SCRAPER_OPTIONS  # noqa: E402

def main() -> None:
    for slug, label in PROWLARR_SCRAPER_OPTIONS.items():
        print(f"      {slug}: {label}")

if __name__ == "__main__":
    main()
