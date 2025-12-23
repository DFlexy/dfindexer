# Ferramentas utilitárias para descoberta e criação dinâmica de scrapers

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Dict, Optional, Type

from .base import BaseScraper

_SCRAPER_REGISTRY: Dict[str, Type[BaseScraper]] = {}
_SCRAPER_METADATA: Dict[str, Dict[str, Any]] = {}


def _normalize_scraper_type(scraper_type: str) -> str:
    return scraper_type.strip().lower().replace('-', '_')


# Carrega dinamicamente todas as classes que herdam de BaseScraper
def _discover_scrapers() -> None:
    if _SCRAPER_REGISTRY:
        return

    package_path = Path(__file__).parent
    package_name = __name__

    for module_info in pkgutil.iter_modules([str(package_path)]):
        module_name = module_info.name

        if module_name.startswith('_') or module_name in {'base', '__init__'}:
            continue

        module = importlib.import_module(f"{package_name}.{module_name}")

        for attribute_name in dir(module):
            attribute = getattr(module, attribute_name)

            if (
                isinstance(attribute, type)
                and issubclass(attribute, BaseScraper)
                and attribute is not BaseScraper
            ):
                scraper_type = getattr(attribute, "SCRAPER_TYPE", module_name)
                normalized_type = _normalize_scraper_type(scraper_type)

                default_url = getattr(attribute, "DEFAULT_BASE_URL", "")
                display_name = getattr(attribute, "DISPLAY_NAME", "") or attribute.__name__
                doc = (attribute.__doc__ or "").strip()

                _SCRAPER_REGISTRY[normalized_type] = attribute
                _SCRAPER_METADATA[normalized_type] = {
                    "type": normalized_type,
                    "class_name": attribute.__name__,
                    "module": module.__name__,
                    "default_url": default_url,
                    "doc": doc,
                    "display_name": display_name,
                }


# Normaliza o nome do scraper para comparações
def normalize_scraper_type(scraper_type: str) -> str:
    return _normalize_scraper_type(scraper_type)


# Retorna metadados dos scrapers disponíveis
def available_scraper_types() -> Dict[str, Dict[str, Any]]:
    _discover_scrapers()
    return {scraper_type: dict(metadata) for scraper_type, metadata in _SCRAPER_METADATA.items()}


# Retorna a URL padrão associada a um scraper
def get_scraper_default_url(scraper_type: str) -> Optional[str]:
    _discover_scrapers()
    normalized = _normalize_scraper_type(scraper_type)
    metadata = _SCRAPER_METADATA.get(normalized)
    if not metadata:
        return None
    default_url = metadata.get("default_url")
    if isinstance(default_url, str) and default_url:
        return default_url
    return None


# Cria uma instância do scraper solicitado
def create_scraper(scraper_type: str, base_url: Optional[str] = None, use_flaresolverr: bool = False) -> BaseScraper:
    _discover_scrapers()
    normalized = _normalize_scraper_type(scraper_type)
    scraper_class = _SCRAPER_REGISTRY.get(normalized)
    if not scraper_class:
        available = ", ".join(sorted(_SCRAPER_REGISTRY.keys())) or "nenhum"
        raise ValueError(f"Scraper '{scraper_type}' não encontrado. Disponíveis: {available}")
    return scraper_class(base_url=base_url, use_flaresolverr=use_flaresolverr)


__all__ = [
    "BaseScraper",
    "available_scraper_types",
    "create_scraper",
    "get_scraper_default_url",
    "normalize_scraper_type",
]
