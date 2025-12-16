"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import sys


# Formatter customizado que remove o nome do módulo de todos os logs
class CustomFormatter(logging.Formatter):
    def format(self, record):
        # Remove o nome do módulo de todos os níveis de log
        fmt = '%(asctime)s %(levelname)s - %(message)s'
        
        formatter = logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)


# Converte nível numérico para nível do logging do Python
def _get_log_level_from_numeric(level: int) -> int:
    level_map = {
        0: logging.DEBUG,
        1: logging.INFO,
        2: logging.WARNING,
        3: logging.ERROR
    }
    return level_map.get(level, logging.INFO)


# Configura o sistema de logging
def setup_logging(log_level: int, log_format: str = 'console'):
    # Converte nível numérico para nível do logging
    python_log_level = _get_log_level_from_numeric(log_level)
    
    # Configura formato
    if log_format == 'json':
        # Formato JSON estruturado
        formatter = logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        # Formato console padrão com formatter customizado
        formatter = CustomFormatter()
    
    # Configura handler para stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(python_log_level)
    
    # Configura root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(python_log_level)
    root_logger.handlers = []  # Remove handlers existentes
    root_logger.addHandler(handler)
    
    tracker_logger = logging.getLogger('tracker.list_provider')
    tracker_logger.handlers = []
    tracker_logger.setLevel(python_log_level)
    
    # Silencia loggers de bibliotecas externas para reduzir verbosidade
    # urllib3 e requests geram muitos logs de conexões HTTPS que não são úteis
    # urllib3.connectionpool em WARNING ainda mostra retries - silencia completamente
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.ERROR)
    
    # Silencia asyncio para reduzir verbosidade (logs de selector não são úteis)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    # Silencia werkzeug apenas se nível for alto (para não perder logs importantes do Flask)
    if log_level >= 2:  # warn ou error
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

