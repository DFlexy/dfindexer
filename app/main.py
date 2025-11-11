"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from flask import Flask
from app.config import Config
from api.routes import register_routes
from cache.redis_client import init_redis
from scraper import available_scraper_types
from utils.logger import setup_logging
from waitress import serve

# Configura logging com LOG_LEVEL e LOG_FORMAT
setup_logging(Config.LOG_LEVEL, Config.LOG_FORMAT)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Factory function para criar a aplicação Flask"""
    app = Flask(__name__)
    
    # Inicializa Redis (opcional - não falha se não disponível)
    try:
        init_redis()
    except Exception:
        pass
    
    # Registra rotas
    register_routes(app)
    
    logger.info(f"Servidor iniciado na porta {Config.PORT}")
    logger.info(f"Scrapers disponíveis: {list(available_scraper_types().keys())}")
    
    return app


if __name__ == '__main__':
    app = create_app()
    serve(app, host='0.0.0.0', port=Config.PORT)

