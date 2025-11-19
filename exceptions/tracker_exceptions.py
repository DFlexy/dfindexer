"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""


# Exceção base para erros de tracker
class TrackerError(Exception):
    pass


# Erro de conexão com tracker
class TrackerConnectionError(TrackerError):
    def __init__(self, tracker_url: str, reason: str = ""):
        self.tracker_url = tracker_url
        self.reason = reason
        message = f"Erro ao conectar ao tracker: {tracker_url}"
        if reason:
            message += f" - {reason}"
        super().__init__(message)


# Timeout ao conectar ao tracker
class TrackerTimeoutError(TrackerError):
    def __init__(self, tracker_url: str, operation: str = ""):
        self.tracker_url = tracker_url
        self.operation = operation
        message = f"Timeout ao conectar ao tracker: {tracker_url}"
        if operation:
            message += f" (operação: {operation})"
        super().__init__(message)


# Tracker inválido
class InvalidTrackerError(TrackerError):
    def __init__(self, tracker_url: str, reason: str = ""):
        self.tracker_url = tracker_url
        self.reason = reason
        message = f"Tracker inválido: {tracker_url}"
        if reason:
            message += f" - {reason}"
        super().__init__(message)

