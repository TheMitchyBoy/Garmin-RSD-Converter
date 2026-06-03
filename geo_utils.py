#!/usr/bin/env python3
"""
Geospatial helpers for decoding Garmin sonar coordinates.
"""

from typing import Optional, Tuple


WGS84_MAX_LATITUDE = 90.0
WGS84_MAX_LONGITUDE = 180.0

# Garmin ecosystems commonly store coordinates in either:
# 1) integer degrees * 1e7, or
# 2) signed semicircles (2^31 semicircles == 180 degrees).
GARMIN_DEGREES_SCALE = 10_000_000.0
GARMIN_SEMICIRCLE_TO_DEGREES = 180.0 / (2 ** 31)


def decode_garmin_coordinate(raw_value: int, *, is_latitude: bool) -> Optional[float]:
    """
    Decode a raw Garmin coordinate into decimal degrees.

    Returns None when the value cannot be interpreted as a valid WGS84 coordinate.
    """
    limit = WGS84_MAX_LATITUDE if is_latitude else WGS84_MAX_LONGITUDE

    degree_scaled = raw_value / GARMIN_DEGREES_SCALE
    if -limit <= degree_scaled <= limit:
        return degree_scaled

    semicircle_scaled = raw_value * GARMIN_SEMICIRCLE_TO_DEGREES
    if -limit <= semicircle_scaled <= limit:
        return semicircle_scaled

    return None


def decode_garmin_coordinate_pair(lat_raw: int, lon_raw: int) -> Tuple[Optional[float], Optional[float]]:
    """Decode latitude/longitude pair; both must be valid to be returned."""
    lat = decode_garmin_coordinate(lat_raw, is_latitude=True)
    lon = decode_garmin_coordinate(lon_raw, is_latitude=False)
    if lat is None or lon is None:
        return None, None
    return lat, lon


def is_valid_wgs84(lat: float, lon: float) -> bool:
    """Return True when coordinates are inside valid WGS84 bounds."""
    return (
        -WGS84_MAX_LATITUDE <= lat <= WGS84_MAX_LATITUDE
        and -WGS84_MAX_LONGITUDE <= lon <= WGS84_MAX_LONGITUDE
    )
