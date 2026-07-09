import os
import sys

# Garante que o projeto raiz está no path e que os testes rodam sem Redis.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop('REDIS_HOST', None)
os.environ.pop('FLARESOLVERR_ADDRESS', None)
