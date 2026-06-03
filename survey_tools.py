#!/usr/bin/env python3
"""
Survey merge, comparison, and track quality scoring utilities.

These modules operate on normalized project CSV (post-PINGVerter), not raw RSD:

- ``merge_csv_files`` — concatenate multiple survey CSVs (same header required)
- ``compare_surveys`` — grid-subtract bathymetry (survey B minus A) as GeoJSON
- ``compute_track_quality`` — 0–100 score for GPS/data completeness before mapping
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from heatmap_generator import HeatmapGenerator
from map_visuals import grid_cell_polygon, grid_key, haversine_span_meters


def merge_csv_files(
    csv_files: List[Path],
    output_file: Optional[Path] = None,
) -> Path:
    """Merge multiple sonar CSV files into one sorted by frame number."""
    if not csv_files:
        raise ValueError("At least one CSV file is required")

    csv_files = [Path(p) for p in csv_files]
    for path in csv_files:
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")

    if output_file is None:
        output_file = csv_files[0].with_name(
            f"{csv_files[0].stem}_merged_{len(csv_files)}files.csv"
        )
    else:
        output_file = Path(output_file)

    fieldnames: Optional[List[str]] = None
    rows: List[dict] = []

    for path in csv_files:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if fieldnames is None:
                fieldnames = list(reader.fieldnames or [])
            elif list(reader.fieldnames or []) != fieldnames:
                raise ValueError(f"CSV header mismatch: {path}")
            rows.extend(reader)

    if not fieldnames:
        raise ValueError("No CSV headers found")

    def sort_key(row: dict) -> Tuple[int, int]:
        try:
            return (int(row.get("frame_number") or 0), int(row.get("offset") or 0))
        except (ValueError, TypeError):
            return (0, 0)

    rows.sort(key=sort_key)

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_file


def compare_surveys(
    csv_a: Path,
    csv_b: Path,
    grid_size: float = 0.01,
    output_file: Optional[Path] = None,
) -> Path:
    """
    Compare bathymetry between two surveys on a shared grid.
    Outputs GeoJSON polygons with depth delta (B - A) in meters.
    """
    csv_a = Path(csv_a)
    csv_b = Path(csv_b)
    if output_file is None:
        output_file = csv_a.with_name(
            f"{csv_a.stem}_vs_{csv_b.stem}_depth_diff.geojson"
        )
    else:
        output_file = Path(output_file)

    grid_a, _ = HeatmapGenerator.build_depth_grid(csv_a, grid_size)
    grid_b, _ = HeatmapGenerator.build_depth_grid(csv_b, grid_size)
    all_keys = set(grid_a) | set(grid_b)

    deltas = []
    for key in all_keys:
        da = grid_a.get(key)
        db = grid_b.get(key)
        if da is not None and db is not None:
            deltas.append(db - da)

    features = []
    for key in sorted(all_keys):
        da = grid_a.get(key)
        db = grid_b.get(key)
        if da is None or db is None:
            continue

        delta = db - da
        grid_x, grid_y = key
        lon = (grid_x + 0.5) * grid_size
        lat = (grid_y + 0.5) * grid_size

        if deltas:
            min_d = min(deltas)
            max_d = max(deltas)
            span = max(abs(min_d), abs(max_d), 0.01)
            t = (delta + span) / (2 * span)
        else:
            t = 0.5
        t = max(0.0, min(1.0, t))
        # Blue = deeper after survey B, red = shallower
        r = int(255 * t)
        b = int(255 * (1 - t))
        color = f"#{r:02x}40{b:02x}"

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [grid_cell_polygon(lon, lat, grid_size)],
            },
            "properties": {
                "layer": "depth_diff",
                "depth_a_m": round(da, 2),
                "depth_b_m": round(db, 2),
                "depth_delta_m": round(delta, 2),
                "color": color,
                "fill_opacity": 0.75,
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "properties": {
            "comparison_type": "bathymetry_delta",
            "survey_a": str(csv_a),
            "survey_b": str(csv_b),
            "grid_size_deg": grid_size,
            "cells_compared": len(features),
        },
        "features": features,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2)

    return output_file


def compute_track_quality(csv_file: Path) -> Dict:
    """
    Score GPS track quality and data completeness (0-100 overall).
    """
    csv_file = Path(csv_file)
    total = 0
    gps_valid = 0
    depth_valid = 0
    intensity_valid = 0
    temp_valid = 0

    lats: List[float] = []
    lons: List[float] = []
    frame_gaps: List[int] = []
    prev_frame: Optional[int] = None
    speeds_m_s: List[float] = []

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            try:
                lat = float(row.get("latitude") or 0)
                lon = float(row.get("longitude") or 0)
                has_gps = not (lat == 0 and lon == 0) and -90 <= lat <= 90 and -180 <= lon <= 180
            except (ValueError, TypeError):
                has_gps = False
                lat = lon = 0.0

            if has_gps:
                gps_valid += 1
                if lats:
                    dist = _haversine_m(lats[-1], lons[-1], lat, lon)
                    speeds_m_s.append(dist)
                lats.append(lat)
                lons.append(lon)

            try:
                depth = float(row.get("depth_m") or 0)
                if depth > 0:
                    depth_valid += 1
            except (ValueError, TypeError):
                pass

            try:
                intensity = float(row.get("sonar_intensity_avg") or 0)
                if intensity > 0:
                    intensity_valid += 1
            except (ValueError, TypeError):
                pass

            try:
                temp = float(row.get("water_temp_c") or 0)
                if temp != 0:
                    temp_valid += 1
            except (ValueError, TypeError):
                pass

            try:
                frame = int(row.get("frame_number") or 0)
                if prev_frame is not None and frame > prev_frame + 1:
                    frame_gaps.append(frame - prev_frame - 1)
                prev_frame = frame
            except (ValueError, TypeError):
                pass

    if total == 0:
        return {
            "overall_score": 0,
            "grade": "F",
            "total_frames": 0,
            "warnings": ["Empty CSV file"],
        }

    gps_pct = gps_valid / total * 100
    depth_pct = depth_valid / total * 100
    intensity_pct = intensity_valid / total * 100
    temp_pct = temp_valid / total * 100

    completeness = (gps_pct * 0.4 + depth_pct * 0.35 + intensity_pct * 0.25)

    # Penalize large gaps in frame_number (may indicate dropped pings or bad merge)
    continuity = 100.0
    if frame_gaps:
        avg_gap = sum(frame_gaps) / len(frame_gaps)
        continuity = max(0.0, 100.0 - min(avg_gap * 2, 50))

    speed_score = 100.0
    speed_outliers = 0
    if speeds_m_s:
        mean_speed = sum(speeds_m_s) / len(speeds_m_s)
        for s in speeds_m_s:
            # Flag jumps >5× mean and >500 m between consecutive GPS points
            if mean_speed > 0 and s > mean_speed * 5 and s > 500:
                speed_outliers += 1
        if speeds_m_s:
            outlier_pct = speed_outliers / len(speeds_m_s) * 100
            speed_score = max(0.0, 100.0 - outlier_pct * 3)

    coverage_score = 100.0
    if len(lats) >= 2:
        span = haversine_span_meters(min(lats), max(lats), min(lons), max(lons))
        if span < 10:
            coverage_score = 40.0
        elif span < 100:
            coverage_score = 70.0

    overall = (
        completeness * 0.45
        + continuity * 0.20
        + speed_score * 0.15
        + coverage_score * 0.20
    )
    overall = round(min(100.0, max(0.0, overall)), 1)

    warnings: List[str] = []
    if gps_pct < 50:
        warnings.append(f"Low GPS coverage ({gps_pct:.0f}%)")
    if depth_pct < 50:
        warnings.append(f"Low depth data ({depth_pct:.0f}%)")
    if speed_outliers > 0:
        warnings.append(f"{speed_outliers} GPS speed outlier(s) detected")
    if frame_gaps and max(frame_gaps) > 10:
        warnings.append(f"Large frame gap ({max(frame_gaps)} frames)")

    grade = _score_to_grade(overall)

    return {
        "overall_score": overall,
        "grade": grade,
        "total_frames": total,
        "gps_coverage_pct": round(gps_pct, 1),
        "depth_coverage_pct": round(depth_pct, 1),
        "intensity_coverage_pct": round(intensity_pct, 1),
        "temperature_coverage_pct": round(temp_pct, 1),
        "continuity_score": round(continuity, 1),
        "speed_score": round(speed_score, 1),
        "spatial_coverage_score": round(coverage_score, 1),
        "gps_points": len(lats),
        "frame_gaps": len(frame_gaps),
        "speed_outliers": speed_outliers,
        "warnings": warnings,
    }


def format_quality_report(quality: Dict) -> str:
    """Format track quality metrics for CLI output."""
    lines = [
        "",
        "=== Track Quality Score ===",
        f"Overall: {quality['overall_score']}/100 ({quality['grade']})",
        f"Total frames: {quality['total_frames']:,}",
        "",
        "Field coverage:",
        f"  GPS:        {quality.get('gps_coverage_pct', 0):.1f}%",
        f"  Depth:      {quality.get('depth_coverage_pct', 0):.1f}%",
        f"  Intensity:  {quality.get('intensity_coverage_pct', 0):.1f}%",
        f"  Temperature:{quality.get('temperature_coverage_pct', 0):.1f}%",
        "",
        "Quality factors:",
        f"  Continuity:  {quality.get('continuity_score', 0):.1f}/100",
        f"  Speed:       {quality.get('speed_score', 0):.1f}/100",
        f"  Spatial:     {quality.get('spatial_coverage_score', 0):.1f}/100",
    ]
    if quality.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in quality["warnings"]:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
