"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from flask import Flask, render_template, make_response
from api.handlers import index_handler, indexer_handler


def register_routes(app: Flask):
    app.add_url_rule('/', 'index', index_handler, methods=['GET'])
    app.add_url_rule('/indexer', 'indexer', lambda: indexer_handler(None), methods=['GET'])
    app.add_url_rule('/indexers/<site_name>', 'indexer_by_site', indexer_handler, methods=['GET'])
    app.add_url_rule('/api', 'search_page', search_page_handler, methods=['GET'])


def search_page_handler():
    """Handler para a página de busca web"""
    response = make_response(render_template('search.html'))
    # Headers para evitar cache do navegador
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

