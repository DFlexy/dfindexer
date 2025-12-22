"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import os
import random
import socket
import struct
import threading
from typing import Tuple, Optional

PROTOCOL_ID = 0x41727101980
ACTION_CONNECT = 0
ACTION_SCRAPE = 2


def _generate_transaction_id() -> int:
    return random.randint(0, 0xFFFFFFFF)


def _create_udp_socket(host: str, port: int) -> socket.socket:
    """
    Cria socket UDP, usando proxy SOCKS5 se configurado.
    
    Nota: O suporte UDP via SOCKS5 pode ter limitações dependendo da implementação
    do PySocks e do servidor proxy. Com socks5h, o DNS deve ser resolvido no servidor
    proxy, mas isso depende do suporte completo do proxy para UDP.
    
    Args:
        host: Host do destino (deve ser string, não IP resolvido, para socks5h funcionar)
        port: Porta do destino
        
    Returns:
        Socket UDP configurado (com ou sem proxy)
    """
    try:
        from app.config import Config
        from utils.http.proxy import get_proxy_url
        
        # Verifica se proxy está configurado e é SOCKS5
        proxy_url = get_proxy_url()
        if proxy_url and proxy_url.startswith(('socks5://', 'socks5h://')):
            try:
                import socks
                # Extrai informações do proxy
                proxy_type = Config.PROXY_TYPE.lower().strip()
                proxy_host = Config.PROXY_HOST.strip()
                proxy_port = int(Config.PROXY_PORT.strip())
                proxy_user = Config.PROXY_USER.strip() if Config.PROXY_USER else None
                proxy_pass = Config.PROXY_PASS.strip() if Config.PROXY_PASS else None
                
                # Cria socket SOCKS5 para UDP
                # Nota: PySocks suporta UDP via SOCKS5, mas o suporte pode variar
                sock = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)
                
                # Configura tipo de proxy
                # Com socks5h, o DNS deve ser resolvido no servidor proxy
                # O host deve ser passado como string (não IP) para isso funcionar
                sock.set_proxy(socks.SOCKS5, proxy_host, proxy_port,
                             username=proxy_user, password=proxy_pass)
                
                # Para socks5h, precisamos garantir que o DNS seja resolvido no proxy
                # Isso é feito passando o hostname como string (não IP) para sendto/recvfrom
                return sock
            except ImportError:
                # PySocks não instalado, usa socket normal
                pass
            except Exception as e:
                # Erro ao configurar proxy, usa socket normal
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Erro ao configurar proxy SOCKS5 para UDP: {e}")
                pass
    except Exception:
        # Erro ao importar Config ou get_proxy_url, usa socket normal
        pass
    
    # Fallback: socket UDP normal (sem proxy)
    # Nota: Isso significa que requisições UDP não passarão pelo proxy
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# Cliente simples para operação SCRAPE (BEP-0015) via UDP
class UDPScraper:
    def __init__(self, timeout: float = 0.5, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        # Inicializa semente randômica por processo
        random.seed(int.from_bytes(os.urandom(8), "big"))

    def scrape(self, tracker_url: str, info_hash: bytes) -> Tuple[int, int]:
        host, port = self._parse_tracker(tracker_url)
        # Cria socket UDP (com proxy SOCKS5 se configurado)
        sock = _create_udp_socket(host, port)
        try:
            sock.settimeout(self.timeout)
            sock.bind(("", 0))
            connection_id = self._connect(sock, host, port)
            return self._scrape(sock, host, port, connection_id, info_hash)
        finally:
            sock.close()

    def _parse_tracker(self, tracker_url: str) -> Tuple[str, int]:
        stripped = tracker_url.strip()
        if not stripped.lower().startswith("udp://"):
            raise ValueError("Somente trackers UDP são suportados.")
        without_scheme = stripped[6:]
        if "/" in without_scheme:
            without_scheme = without_scheme.split("/", 1)[0]
        if ":" in without_scheme:
            host, port_str = without_scheme.split(":", 1)
            port = int(port_str)
        else:
            host = without_scheme
            port = 80
        if not host:
            raise ValueError("Host inválido para tracker UDP.")
        return host, port

    def _connect(self, sock: socket.socket, host: str, port: int) -> int:
        tid = _generate_transaction_id()
        packet = struct.pack(">QLL", PROTOCOL_ID, ACTION_CONNECT, tid)
        for attempt in range(self.retries + 1):
            sock.sendto(packet, (host, port))
            try:
                data, _ = sock.recvfrom(16)
            except socket.timeout:
                if attempt >= self.retries:
                    raise TimeoutError("Timeout esperando resposta CONNECT.")
                continue
            if len(data) != 16:
                raise RuntimeError("Resposta CONNECT inválida.")
            action, resp_tid, connection_id = struct.unpack(">LLQ", data)
            if action != ACTION_CONNECT:
                raise RuntimeError("Ação CONNECT inválida.")
            if resp_tid != tid:
                raise RuntimeError("Transaction ID CONNECT divergente.")
            return connection_id
        raise TimeoutError("Falha ao conectar ao tracker UDP.")

    def _scrape(
        self, sock: socket.socket, host: str, port: int, connection_id: int, info_hash: bytes
    ) -> Tuple[int, int]:
        if len(info_hash) != 20:
            raise ValueError("info_hash deve possuir 20 bytes.")
        tid = _generate_transaction_id()
        header = struct.pack(">QLL", connection_id, ACTION_SCRAPE, tid)
        packet = header + info_hash
        expected_length = 8 + 12  # header + (seeders/completed/leechers)
        for attempt in range(self.retries + 1):
            sock.sendto(packet, (host, port))
            try:
                data, _ = sock.recvfrom(expected_length)
            except socket.timeout:
                if attempt >= self.retries:
                    raise TimeoutError("Timeout esperando resposta SCRAPE.")
                continue
            if len(data) < expected_length:
                if attempt >= self.retries:
                    raise RuntimeError("Resposta SCRAPE incompleta.")
                continue
            action, resp_tid = struct.unpack(">LL", data[:8])
            if resp_tid != tid:
                raise RuntimeError("Transaction ID SCRAPE divergente.")
            if action != ACTION_SCRAPE:
                raise RuntimeError("Ação SCRAPE inválida.")
            seeders, completed, leechers = struct.unpack(">LLL", data[8:20])
            return leechers, seeders
        raise TimeoutError("Falha ao obter dados SCRAPE do tracker.")


