"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

import os
import random
import socket
import struct
import threading
from typing import Tuple

PROTOCOL_ID = 0x41727101980
ACTION_CONNECT = 0
ACTION_SCRAPE = 2


def _generate_transaction_id() -> int:
    return random.randint(0, 0xFFFFFFFF)


class UDPScraper:
    """Cliente simples para operação SCRAPE (BEP-0015) via UDP."""

    def __init__(self, timeout: float = 0.5, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        # Inicializa semente randômica por processo
        random.seed(int.from_bytes(os.urandom(8), "big"))

    def scrape(self, tracker_url: str, info_hash: bytes) -> Tuple[int, int]:
        host, port = self._parse_tracker(tracker_url)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            sock.bind(("", 0))
            connection_id = self._connect(sock, host, port)
            return self._scrape(sock, host, port, connection_id, info_hash)

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


