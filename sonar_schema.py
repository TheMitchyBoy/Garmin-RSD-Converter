#!/usr/bin/env python3
"""
Shared CSV schema, row parsing, and streaming statistics for sonar data.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Canonical CSV columns produced by sonar_converter_streaming.py
CSV_COLUMNS = (
    'frame_number',
    'offset',
    'latitude',
    'longitude',
    'depth_m',
    'water_temp_c',
    'sonar_frequency_khz',
    'sonar_intensity_avg',
    'sonar_intensity_max',
    'sonar_intensity_count',
)

HEURISTIC_DISCLAIMER = (
    'Sonar intensity signatures are classified heuristically and do not constitute '
    'biological identification or scientific fisheries survey data.'
)

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

__version__ = '1.1.0'


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once for CLI and standalone scripts."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=LOG_FORMAT)


def parse_float(value: Any) -> Optional[float]:
    """Parse a CSV field to float, returning None for empty or invalid values."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> Optional[int]:
    """Parse a CSV field to int, returning None for empty or invalid values."""
    parsed = parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def is_valid_gps(lat: Optional[float], lon: Optional[float]) -> bool:
    """Return True when latitude/longitude look like real coordinates."""
    if lat is None or lon is None:
        return False
    if lat == 0 and lon == 0:
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


@dataclass
class SonarReading:
    """Normalized sonar CSV row."""

    latitude: float
    longitude: float
    depth_m: Optional[float] = None
    water_temp_c: Optional[float] = None
    sonar_frequency_khz: Optional[float] = None
    sonar_intensity_avg: Optional[float] = None
    sonar_intensity_max: Optional[float] = None
    sonar_intensity_count: Optional[int] = None
    frame_number: Optional[int] = None
    offset: Optional[int] = None
    raw: Optional[Dict[str, str]] = None

    @property
    def elevation_m(self) -> Optional[float]:
        """Surface elevation for KML/GPX (negative depth below surface)."""
        if self.depth_m is None:
            return None
        return -self.depth_m

    @property
    def beam_count(self) -> int:
        """Beam/sample count; accepts legacy beam_count column via raw row."""
        if self.sonar_intensity_count is not None:
            return self.sonar_intensity_count
        if self.raw:
            legacy = parse_int(self.raw.get('beam_count'))
            if legacy is not None:
                return legacy
        return 0


def parse_sonar_row(row: Dict[str, str]) -> Optional[SonarReading]:
    """Parse a CSV DictReader row into a SonarReading, or None if GPS is invalid."""
    lat = parse_float(row.get('latitude'))
    lon = parse_float(row.get('longitude'))
    if not is_valid_gps(lat, lon):
        return None

    return SonarReading(
        latitude=lat,
        longitude=lon,
        depth_m=parse_float(row.get('depth_m')),
        water_temp_c=parse_float(row.get('water_temp_c')),
        sonar_frequency_khz=parse_float(row.get('sonar_frequency_khz')),
        sonar_intensity_avg=parse_float(row.get('sonar_intensity_avg')),
        sonar_intensity_max=parse_float(row.get('sonar_intensity_max')),
        sonar_intensity_count=parse_int(row.get('sonar_intensity_count')),
        frame_number=parse_int(row.get('frame_number')),
        offset=parse_int(row.get('offset')),
        raw=row,
    )


class StreamingNumericStats:
    """Single-pass min/max/mean/count with reservoir-sampled approximate median."""

    def __init__(self, reservoir_size: int = 10_000, seed: int = 42):
        self.count = 0
        self.total = 0.0
        self.min_val: Optional[float] = None
        self.max_val: Optional[float] = None
        self._reservoir: list[float] = []
        self._reservoir_size = reservoir_size
        self._rng = random.Random(seed)

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.min_val = value if self.min_val is None else min(self.min_val, value)
        self.max_val = value if self.max_val is None else max(self.max_val, value)

        if len(self._reservoir) < self._reservoir_size:
            self._reservoir.append(value)
        else:
            idx = self._rng.randrange(self.count)
            if idx < self._reservoir_size:
                self._reservoir[idx] = value

    @property
    def mean(self) -> Optional[float]:
        return self.total / self.count if self.count else None

    def median(self) -> Optional[float]:
        if not self._reservoir:
            return None
        sorted_vals = sorted(self._reservoir)
        mid = len(sorted_vals) // 2
        if len(sorted_vals) % 2:
            return sorted_vals[mid]
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
