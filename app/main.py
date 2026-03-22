"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from app.config import Config
from app.bootstrap import Bootstrap
from utils.logging.logger import setup_logging
from waitress import serve

setup_logging(Config.LOG_LEVEL, Config.LOG_FORMAT)

logger = logging.getLogger(__name__)


def create_app():
    return Bootstrap.create_app()


if __name__ == '__main__':
    app = create_app()
    serve(
        app,
        host='0.0.0.0',
        port=Config.PORT,
        threads=12,
        channel_timeout=300,
        recv_bytes=65536,
    )

