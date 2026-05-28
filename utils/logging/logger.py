# Copyright (c) 2025 DFlexy · https://github.com/DFlexy

import logging
import sys

class CustomFormatter(logging.Formatter):
    def format(self, record):
        fmt = '%(asctime)s %(levelname)s - %(message)s'
        
        formatter = logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)

def _get_log_level_from_numeric(level: int) -> int:
    level_map = {
        0: logging.DEBUG,
        1: logging.INFO,
        2: logging.WARNING,
        3: logging.ERROR
    }
    return level_map.get(level, logging.INFO)

def print_support_banner(log_format: str = 'console') -> None:
    """Exibe mensagem de apoio ao projeto no console (uma vez por inicialização)."""
    if log_format != 'console':
        return
    lines = [
        '',
        '======================================================================',
        '                 💖 Apoie este projeto',
        '======================================================================',
        '',
        '  Este projeto e 100% independente e open-source.',
        '  💜 Seu apoio mantem o desenvolvimento ativo.',
        '',
        '  >> APOIAR ESTE PROJETO:',
        '  https://donate.stripe.com/3cI3cvehCfd18bxbPoco000',
        '',
        '======================================================================',
        '',
    ]
    for line in lines:
        print(line, file=sys.stdout)
    sys.stdout.flush()

def setup_logging(log_level: int, log_format: str = 'console'):
    python_log_level = _get_log_level_from_numeric(log_level)
    
    if log_format == 'json':
        formatter = logging.Formatter(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        formatter = CustomFormatter()
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(python_log_level)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(python_log_level)
    root_logger.handlers = []
    root_logger.addHandler(handler)
    
    tracker_logger = logging.getLogger('tracker.list_provider')
    tracker_logger.handlers = []
    tracker_logger.setLevel(python_log_level)
    
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('urllib3.connectionpool').setLevel(logging.ERROR)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.ERROR)
    
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    if log_level >= 2:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

