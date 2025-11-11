"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import logging
import sys


def _get_log_level_from_numeric(level: int) -> int:
    """
    Converte nível numérico (como no Go) para nível do logging do Python
    
    Args:
        level: Nível numérico (0=debug, 1=info, 2=warn, 3=error)
        
    Returns:
        Nível do logging do Python
    """
    level_map = {
        0: logging.DEBUG,
        1: logging.INFO,
        2: logging.WARNING,
        3: logging.ERROR
    }
    return level_map.get(level, logging.INFO)


def setup_logging(log_level: int, log_format: str = 'console'):
    """
    Configura o sistema de logging
    
    Args:
        log_level: Nível numérico (0=debug, 1=info, 2=warn, 3=error)
        log_format: Formato do log ('console' ou 'json')
    """
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
        # Formato console padrão
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
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
    
    # Silencia loggers de bibliotecas externas se nível for alto
    if log_level >= 2:  # warn ou error
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)

