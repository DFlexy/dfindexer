#!/usr/bin/env python3
"""Gera o bloco scraper_type do prowlarr.yml a partir da pasta scraper/."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.prowlarr_config import get_prowlarr_default_scraper, get_prowlarr_scraper_options  # noqa: E402


def main() -> None:
    options = get_prowlarr_scraper_options()
    default = get_prowlarr_default_scraper()
    if not options:
        print("# Nenhum scraper encontrado em scraper/", file=sys.stderr)
        sys.exit(1)

    print("  - name: scraper_type")
    print("    type: select")
    print("    label: Scraper")
    print(f"    default: {default}")
    print("    options:")
    for slug, label in options.items():
        print(f"      {slug}: {label}")


if __name__ == "__main__":
    main()
