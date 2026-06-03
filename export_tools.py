#!/usr/bin/env python3
"""
Shared map and point-cloud export helpers.

Central dispatcher for ``--maps`` on convert/batch commands. Keeps export logic
in one place so sonar_cli.py and batch_processor.py stay thin.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from analysis_tools import MapGenerator
from geotiff_export import GeoTiffWriter
from las_export import LasExporter


def generate_map_exports(csv_file: Path, map_formats: Sequence[str]) -> List[Path]:
    """Generate requested export formats from a sonar CSV file."""
    csv_file = Path(csv_file)
    all_formats = {'ply', 'geojson', 'kml', 'gpx', 'geotiff', 'tif', 'las', 'laz'}
    formats = all_formats if 'all' in map_formats else set(map_formats)
    outputs: List[Path] = []

    for fmt in formats:
        if fmt == 'ply':
            outputs.append(MapGenerator.create_ply(csv_file))
        elif fmt == 'geojson':
            outputs.append(MapGenerator.create_geojson(csv_file))
        elif fmt == 'kml':
            outputs.append(MapGenerator.create_kml(csv_file))
        elif fmt == 'gpx':
            outputs.append(MapGenerator.create_gpx(csv_file))
        elif fmt in ('geotiff', 'tif'):
            outputs.append(GeoTiffWriter.create_depth_geotiff(csv_file))
        elif fmt == 'las':
            outputs.append(LasExporter.create_las(csv_file, compress=False))
        elif fmt == 'laz':
            outputs.append(LasExporter.create_las(csv_file, compress=True))

    return outputs
