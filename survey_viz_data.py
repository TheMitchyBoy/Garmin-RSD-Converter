#!/usr/bin/env python3
"""Survey track, echogram, and training-label helpers for the web dashboard."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ~330 m cells at mid-latitudes (finer than legacy 0.01° ≈ 1.1 km)
DEFAULT_DASHBOARD_GRID_SIZE = 0.003
MAX_ECHOGRAM_PINGS = 3000


def load_csv_track_geojson(csv_file: Path) -> Dict[str, Any]:
    """Build a GeoJSON FeatureCollection with a survey LineString track."""
    csv_file = Path(csv_file)
    coordinates: List[List[float]] = []
    pings: List[Dict[str, Any]] = []

    with open(csv_file, newline='', encoding='utf-8', errors='replace') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                lat = float(row.get('latitude', '') or 0)
                lon = float(row.get('longitude', '') or 0)
            except (TypeError, ValueError):
                continue
            if lat == 0 and lon == 0:
                continue
            coordinates.append([lon, lat])
            pings.append({
                'frame': int(float(row.get('frame_number', 0) or 0)),
                'time_s': _opt_float(row.get('time_s')),
                'lat': lat,
                'lon': lon,
                'depth_m': _opt_float(row.get('depth_m')),
                'intensity': _opt_float(row.get('sonar_intensity_avg')),
            })

    pings.sort(key=lambda p: (p['frame'], p.get('time_s') or 0))
    if pings:
        coordinates = [[p['lon'], p['lat']] for p in pings]

    features: List[Dict[str, Any]] = []
    if len(coordinates) >= 2:
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'properties': {'name': 'Survey route', 'layer': 'track'},
        })

    return {'type': 'FeatureCollection', 'features': features, 'pings': pings}


def build_echogram_pings(csv_file: Path, max_pings: int = MAX_ECHOGRAM_PINGS) -> List[Dict[str, Any]]:
    """Downsampled ping series for client-side sonar strip rendering."""
    payload = load_csv_track_geojson(csv_file)
    pings: List[Dict[str, Any]] = payload.get('pings', [])
    if len(pings) <= max_pings:
        return pings
    step = len(pings) / max_pings
    sampled = [pings[int(i * step)] for i in range(max_pings)]
    return sampled


def _opt_float(value: Any) -> Optional[float]:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_training_labels_template(output_path: Path, survey_name: str, csv_name: str) -> Path:
    """Write an empty training-labels JSON next to the dashboard."""
    payload = {
        'survey': survey_name,
        'source_csv': csv_name,
        'labels': [],
    }
    output_path = Path(output_path)
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
    return output_path
