"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""


# Exceção base para erros de scraper
class ScraperError(Exception):
    pass


# Scraper não encontrado
class ScraperNotFoundError(ScraperError):
    def __init__(self, scraper_type: str, available: list):
        self.scraper_type = scraper_type
        self.available = available
        super().__init__(f"Scraper '{scraper_type}' não encontrado. Disponíveis: {available}")


# Erro de configuração do scraper
class ScraperConfigurationError(ScraperError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


# Erro ao fazer requisição no scraper
class ScraperRequestError(ScraperError):
    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"Erro ao fazer requisição para {url}: {reason}")

