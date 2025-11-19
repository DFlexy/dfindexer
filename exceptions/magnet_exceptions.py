"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""


# Exceção base para erros de magnet
class MagnetError(Exception):
    pass


# Link magnet inválido
class InvalidMagnetLinkError(MagnetError):
    def __init__(self, magnet_link: str, reason: str = ""):
        self.magnet_link = magnet_link
        self.reason = reason
        message = f"Link magnet inválido: {magnet_link}"
        if reason:
            message += f" - {reason}"
        super().__init__(message)


# Info hash inválido
class InvalidInfoHashError(MagnetError):
    def __init__(self, info_hash: str, reason: str = ""):
        self.info_hash = info_hash
        self.reason = reason
        message = f"Info hash inválido: {info_hash}"
        if reason:
            message += f" - {reason}"
        super().__init__(message)

