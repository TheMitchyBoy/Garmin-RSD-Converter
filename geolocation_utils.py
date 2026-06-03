#!/usr/bin/env python3
"""
Utilities for decoding and sanitizing sonar geolocation coordinates.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple


DEGREES_1E7_SCALE = 10_000_000.0
MAX_TRACK_JUMP_KM = 50.0


def is_valid_wgs84(lat: float, lon: float) -> bool:
    """Return True when lat/lon are valid WGS84 coordinates."""
    return (
        -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
        and not (abs(lat) < 1e-12 and abs(lon) < 1e-12)
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in kilometers."""
    earth_radius_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


def decode_raw_degrees(raw_lat: int, raw_lon: int) -> Optional[Tuple[float, float]]:
    """
    Decode signed integer GPS values stored as degrees * 1e7.
    """
    lat = raw_lat / DEGREES_1E7_SCALE
    lon = raw_lon / DEGREES_1E7_SCALE
    if not is_valid_wgs84(lat, lon):
        return None
    return lat, lon


class CoordinateSanitizer:
    """
    Stateful GPS filter that removes implausible jumps between frames.
    """

    def __init__(self, max_jump_km: float = MAX_TRACK_JUMP_KM):
        self.max_jump_km = max_jump_km
        self._last_valid: Optional[Tuple[float, float]] = None

    def sanitize(self, lat: float, lon: float) -> Optional[Tuple[float, float]]:
        """Return sanitized coordinate, or None if the point is an outlier."""
        if not is_valid_wgs84(lat, lon):
            return None

        current = (lat, lon)
        if self._last_valid is None:
            self._last_valid = current
            return current

        jump_km = haversine_km(self._last_valid[0], self._last_valid[1], lat, lon)
        if jump_km > self.max_jump_km:
            return None

        self._last_valid = current
        return current
