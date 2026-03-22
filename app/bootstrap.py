"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
from flask import Flask
from app.config import Config
from api.routes import register_routes
from cache.redis_client import init_redis
from scraper import available_scraper_types

logger = logging.getLogger(__name__)


class Bootstrap:
    @staticmethod
    def initialize_redis() -> None:
        """Inicializa Redis (opcional - não falha se não disponível)"""
        try:
            init_redis()
        except Exception:
            pass
    
    @staticmethod
    def create_app() -> Flask:
        """Cria e configura aplicação Flask"""
        import os
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'api', 'templates')
        app = Flask(__name__, template_folder=template_dir)
        
        Bootstrap.initialize_redis()
        register_routes(app)
        
        # Mostra status do Redis e FlareSolverr no início
        from cache.redis_client import get_redis_client
        redis_client = get_redis_client()
        if redis_client:
            try:
                redis_client.ping()
                logger.info("[[ Redis Conectado ]]")
            except Exception:
                logger.warning("[[ Redis Não Conectado ]]")
        else:
            if Config.REDIS_HOST and Config.REDIS_HOST.strip():
                logger.warning("[[ Redis Não Conectado ]]")
            else:
                logger.warning("[[ Redis Não Conectado ]] - REDIS_HOST não configurado")
        
        if Config.FLARESOLVERR_ADDRESS:
            try:
                import requests
                from utils.http.proxy import get_proxy_dict, is_proxy_local
                _proxy = get_proxy_dict() if not is_proxy_local() else None
                test_response = requests.get(f"{Config.FLARESOLVERR_ADDRESS.rstrip('/')}/v1", timeout=2, proxies=_proxy)
                if test_response.status_code in (200, 404, 405):
                    logger.info("[[ FlareSolverr Conectado ]]")
                else:
                    logger.warning(f"[[ FlareSolverr Não Conectado ]] - Status {test_response.status_code}")
            except requests.exceptions.ConnectionError:
                logger.warning("[[ FlareSolverr Não Conectado ]] - Connection refused")
            except requests.exceptions.Timeout:
                logger.warning("[[ FlareSolverr Não Conectado ]] - Connection timeout")
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e).split('\n')[0][:100] if str(e) else str(e)
                logger.warning(f"[[ FlareSolverr Não Conectado ]] - {error_type}: {error_msg}")
        else:
            logger.warning("[[ FlareSolverr Não Conectado ]] - FLARESOLVERR_ADDRESS não configurado")
        
        logger.info(f"Servidor iniciado na porta {Config.PORT}")
        logger.info(f"Scrapers disponíveis: {list(available_scraper_types().keys())}")
        
        return app

