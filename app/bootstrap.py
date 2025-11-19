"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from flask import Flask
from app.config import Config
from api.routes import register_routes
from cache.redis_client import init_redis
from scraper import available_scraper_types

logger = logging.getLogger(__name__)


# Bootstrap da aplicação - inicialização e configuração
class Bootstrap:
    @staticmethod
    def initialize_redis() -> None:
        """Inicializa Redis (opcional - não falha se não disponível)"""
        try:
            init_redis()
        except Exception:
            pass  # Redis é opcional
    
    @staticmethod
    def create_app() -> Flask:
        """Cria e configura aplicação Flask"""
        app = Flask(__name__)
        
        # Inicializa Redis
        Bootstrap.initialize_redis()
        
        # Registra rotas
        register_routes(app)
        
        logger.info(f"Servidor iniciado na porta {Config.PORT}")
        logger.info(f"Scrapers disponíveis: {list(available_scraper_types().keys())}")
        
        return app

