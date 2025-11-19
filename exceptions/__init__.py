"""Copyright (c) 2025 DFlexy"""
"""https://github.com/DFlexy"""

from exceptions.scraper_exceptions import (
    ScraperNotFoundError,
    ScraperConfigurationError,
    ScraperRequestError
)
from exceptions.magnet_exceptions import (
    InvalidMagnetLinkError,
    InvalidInfoHashError
)
from exceptions.tracker_exceptions import (
    TrackerConnectionError,
    TrackerTimeoutError,
    InvalidTrackerError
)

__all__ = [
    'ScraperNotFoundError',
    'ScraperConfigurationError',
    'ScraperRequestError',
    'InvalidMagnetLinkError',
    'InvalidInfoHashError',
    'TrackerConnectionError',
    'TrackerTimeoutError',
    'InvalidTrackerError',
]

