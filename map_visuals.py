#!/usr/bin/env python3
"""
Shared color ramps and geometry helpers for seabed and fish mapping visuals.
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Fish size categories -> display color and label
FISH_SIZE_LEGEND: Dict[str, Dict[str, str]] = {
    "small": {"color": "#f59e0b", "label": "Small"},
    "medium": {"color": "#f97316", "label": "Medium"},
    "large": {"color": "#dc2626", "label": "Large"},
    "school": {"color": "#7f1d1d", "label": "School / high intensity"},
}

# Species options for training labels (value, display label)
FISH_SPECIES_OPTIONS: List[Tuple[str, str]] = [
    ("unknown", "Unknown"),
    ("salmon", "Salmon"),
    ("chinook_salmon", "Chinook salmon"),
    ("coho_salmon", "Coho salmon"),
    ("rockfish", "Rockfish"),
    ("pacific_cod", "Pacific cod"),
    ("halibut", "Halibut"),
    ("lingcod", "Lingcod"),
    ("pollock", "Pollock"),
    ("sablefish", "Sablefish (black cod)"),
    ("herring", "Herring"),
    ("flounder", "Flounder / sole"),
    ("skate", "Skate"),
    ("crab", "Crab"),
    ("dogfish", "Dogfish / shark"),
    ("school", "School (mixed species)"),
    ("bait", "Bait / clutter / debris"),
    ("other", "Other"),
]


def fish_species_select_html(*, default: str = "unknown") -> str:
    """Build <option> elements for the species labeling dropdown."""
    lines = []
    for value, label in FISH_SPECIES_OPTIONS:
        selected = ' selected' if value == default else ''
        lines.append(f'<option value="{value}"{selected}>{label}</option>')
    return "\n            ".join(lines)


def bathymetry_color(depth_m: float, min_depth: float, max_depth: float) -> str:
    """
    Map depth to a bathymetric ramp: shallow (light cyan) -> deep (dark navy).
    """
    if max_depth <= min_depth:
        t = 0.5
    else:
        t = (depth_m - min_depth) / (max_depth - min_depth)
    t = max(0.0, min(1.0, t))

    # Shallow: #a5f3fc (cyan-200) -> Deep: #0c1e3d (navy)
    stops = [
        (0.0, (165, 243, 252)),
        (0.35, (56, 189, 248)),
        (0.65, (29, 78, 216)),
        (1.0, (12, 30, 61)),
    ]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            span = t1 - t0 if t1 > t0 else 1.0
            local = (t - t0) / span
            r = int(c0[0] + (c1[0] - c0[0]) * local)
            g = int(c0[1] + (c1[1] - c0[1]) * local)
            b = int(c0[2] + (c1[2] - c0[2]) * local)
            return f"#{r:02x}{g:02x}{b:02x}"
    r, g, b = stops[-1][1]
    return f"#{r:02x}{g:02x}{b:02x}"


def intensity_color(intensity: float, min_val: float, max_val: float) -> str:
    """Sonar intensity ramp for fish/structure activity (cool -> hot)."""
    if max_val <= min_val:
        t = 0.5
    else:
        t = (intensity - min_val) / (max_val - min_val)
    t = max(0.0, min(1.0, t))

    if t < 0.33:
        r = 0
        g = int(255 * (t / 0.33))
        b = int(255 * (1 - t / 0.33))
    elif t < 0.66:
        r = int(255 * ((t - 0.33) / 0.33))
        g = 255
        b = 0
    else:
        r = 255
        g = int(255 * (1 - (t - 0.66) / 0.34))
        b = 0
    return f"#{r:02x}{g:02x}{b:02x}"


def grid_cell_polygon(lon: float, lat: float, grid_size: float) -> List[List[float]]:
    """Return a closed GeoJSON polygon ring for a square grid cell."""
    half = grid_size / 2.0
    return [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]


def grid_key(lon: float, lat: float, grid_size: float) -> Tuple[int, int]:
    return (int(lon / grid_size), int(lat / grid_size))


def grid_center(key: Tuple[int, int], grid_size: float) -> Tuple[float, float]:
    grid_x, grid_y = key
    lat = (grid_y + 0.5) * grid_size
    lon = (grid_x + 0.5) * grid_size
    return lat, lon


def fish_marker_radius(size_category: str, confidence: float = 0.5) -> float:
    """Pixel radius for fish markers by size and confidence."""
    base = {
        "small": 5,
        "medium": 7,
        "large": 9,
        "school": 12,
    }.get(size_category, 6)
    return base + min(max(confidence, 0.0), 1.0) * 4


def load_geojson_features(path: Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def depth_legend_stops(min_depth: float, max_depth: float, steps: int = 5) -> List[Dict[str, Any]]:
    """Build legend entries for a depth color ramp."""
    if steps < 2:
        steps = 2
    entries = []
    for i in range(steps):
        t = i / (steps - 1)
        depth = min_depth + t * (max_depth - min_depth)
        entries.append({
            "depth_m": round(depth, 1),
            "color": bathymetry_color(depth, min_depth, max_depth),
        })
    return entries


def bounds_from_features(features: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Compute lat/lon bounds from point or polygon features."""
    lats: List[float] = []
    lons: List[float] = []

    for feature in features:
        geom = feature.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])

        if gtype == "Point" and len(coords) >= 2:
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))
        elif gtype == "Polygon" and coords:
            for ring in coords:
                for pt in ring:
                    if len(pt) >= 2:
                        lons.append(float(pt[0]))
                        lats.append(float(pt[1]))

    if not lats:
        return None
    return {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lon": min(lons),
        "max_lon": max(lons),
    }


def haversine_span_meters(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> float:
    """Approximate diagonal span of bounds in meters."""
    lat_mid = math.radians((min_lat + max_lat) / 2)
    dlat = (max_lat - min_lat) * 111132.0
    dlon = (max_lon - min_lon) * (111412.84 * math.cos(lat_mid))
    return math.sqrt(dlat * dlat + dlon * dlon)
