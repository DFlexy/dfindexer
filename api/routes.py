"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from flask import Flask
from api.handlers import index_handler, indexer_handler


# Registra todas as rotas da aplicação
def register_routes(app: Flask):
    app.add_url_rule('/', 'index', index_handler, methods=['GET'])
    app.add_url_rule('/indexer', 'indexer', lambda: indexer_handler(None), methods=['GET'])
    app.add_url_rule('/indexers/<site_name>', 'indexer_by_site', indexer_handler, methods=['GET'])

