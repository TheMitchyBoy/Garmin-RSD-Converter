#!/usr/bin/env python3
"""
Heatmap generation for sonar data visualization.
Creates intensity and depth heatmaps for seafloor and fish activity analysis.
"""

import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
from collections import defaultdict

from sonar_schema import parse_sonar_row

logger = logging.getLogger(__name__)


class GridCell:
    """Represents a grid cell in the heatmap"""

    def __init__(self, lat: float, lon: float):
        self.lat = lat
        self.lon = lon
        self.intensities: List[float] = []
        self.depths: List[float] = []
        self.temperatures: List[float] = []
        self.point_count = 0

    def add_reading(self, intensity: float, depth: Optional[float], temp: Optional[float]):
        """Add a sonar reading to this cell"""
        self.intensities.append(intensity)
        if depth is not None:
            self.depths.append(depth)
        if temp is not None:
            self.temperatures.append(temp)
        self.point_count += 1

    def get_stats(self) -> Dict:
        """Calculate statistics for this cell"""
        if not self.intensities:
            return {}

        return {
            'latitude': self.lat,
            'longitude': self.lon,
            'intensity_avg': sum(self.intensities) / len(self.intensities),
            'intensity_max': max(self.intensities),
            'intensity_min': min(self.intensities),
            'intensity_std': self._std(self.intensities),
            'point_count': self.point_count,
            'depth_avg': sum(self.depths) / len(self.depths) if self.depths else None,
            'depth_max': max(self.depths) if self.depths else None,
            'temp_avg': sum(self.temperatures) / len(self.temperatures) if self.temperatures else None,
        }

    @staticmethod
    def _std(values: List[float]) -> float:
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)


class HeatmapGenerator:
    """Generate heatmaps from sonar CSV data"""

    @staticmethod
    def _get_color_hex(value: float, min_val: float, max_val: float) -> str:
        """Get hex color for a value using a blue-green-red gradient"""
        if max_val == min_val:
            normalized = 0.5
        else:
            normalized = (value - min_val) / (max_val - min_val)

        if normalized < 0.33:
            r = 0
            g = int(255 * (normalized / 0.33))
            b = int(255 * (1 - normalized / 0.33))
        elif normalized < 0.66:
            r = int(255 * ((normalized - 0.33) / 0.33))
            g = 255
            b = 0
        else:
            r = 255
            g = int(255 * (1 - (normalized - 0.66) / 0.34))
            b = 0

        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def create_intensity_heatmap(
        csv_file: Path,
        grid_size: float = 0.01,
        output_file: Optional[Path] = None
    ) -> Path:
        """Create a heatmap of sonar intensity readings."""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_intensity_heatmap.geojson")

        logger.info(f"Generating intensity heatmap with grid size {grid_size}°...")

        grid: Dict[Tuple[int, int], GridCell] = {}

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reading = parse_sonar_row(row)
                    if reading is None:
                        continue

                    intensity = reading.sonar_intensity_avg or 0.0
                    grid_x = int(reading.longitude / grid_size)
                    grid_y = int(reading.latitude / grid_size)
                    key = (grid_x, grid_y)

                    if key not in grid:
                        cell_lat = (grid_y + 0.5) * grid_size
                        cell_lon = (grid_x + 0.5) * grid_size
                        grid[key] = GridCell(cell_lat, cell_lon)

                    grid[key].add_reading(intensity, reading.depth_m, reading.water_temp_c)

            features = []
            intensities = [cell.get_stats()['intensity_avg'] for cell in grid.values() if cell.get_stats()]

            if intensities:
                min_intensity = min(intensities)
                max_intensity = max(intensities)

                for cell in grid.values():
                    stats = cell.get_stats()
                    if not stats:
                        continue

                    intensity_avg = stats['intensity_avg']
                    color = HeatmapGenerator._get_color_hex(intensity_avg, min_intensity, max_intensity)

                    feature = {
                        'type': 'Feature',
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [cell.lon, cell.lat]
                        },
                        'properties': {
                            'intensity_avg': round(intensity_avg, 2),
                            'intensity_max': round(stats['intensity_max'], 2),
                            'intensity_min': round(stats['intensity_min'], 2),
                            'point_count': stats['point_count'],
                            'depth_avg': round(stats['depth_avg'], 2) if stats['depth_avg'] else None,
                            'temp_avg': round(stats['temp_avg'], 2) if stats['temp_avg'] else None,
                            'color': color,
                        }
                    }
                    features.append(feature)

            geojson = {'type': 'FeatureCollection', 'features': features}

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)

            logger.info(f"Generated intensity heatmap: {output_file}")
            logger.info(f"  Grid cells: {len(grid)}")
            if intensities:
                logger.info(f"  Intensity range: {min_intensity:.2f} - {max_intensity:.2f}")
            else:
                logger.info("  No valid intensity readings found")

            return output_file

        except Exception as e:
            logger.error(f"Error creating intensity heatmap: {e}")
            raise

    @staticmethod
    def create_depth_heatmap(
        csv_file: Path,
        output_file: Optional[Path] = None
    ) -> Path:
        """Create a heatmap showing bathymetry (depth) data"""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_depth_heatmap.geojson")

        logger.info("Generating depth (bathymetry) heatmap...")

        features = []
        depths = []

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reading = parse_sonar_row(row)
                    if reading is None or reading.depth_m is None:
                        continue

                    depth = reading.depth_m
                    depths.append(depth)

                    feature = {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [reading.longitude, reading.latitude]},
                        'properties': {'depth_m': round(depth, 2)}
                    }
                    features.append(feature)

            if depths:
                min_depth = min(depths)
                max_depth = max(depths)

                for feature in features:
                    depth = feature['properties']['depth_m']
                    color = HeatmapGenerator._get_color_hex(depth, min_depth, max_depth)
                    feature['properties']['color'] = color

            geojson = {'type': 'FeatureCollection', 'features': features}

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)

            logger.info(f"Generated depth heatmap: {output_file}")
            if depths:
                logger.info(f"  Depth range: {min(depths):.2f}m - {max(depths):.2f}m")
            else:
                logger.info("  No valid depth readings found")

            return output_file

        except Exception as e:
            logger.error(f"Error creating depth heatmap: {e}")
            raise

    @staticmethod
    def create_temperature_heatmap(
        csv_file: Path,
        output_file: Optional[Path] = None
    ) -> Path:
        """Create a heatmap of water temperature variations"""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_temperature_heatmap.geojson")

        logger.info("Generating temperature heatmap...")

        features = []
        temps = []

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reading = parse_sonar_row(row)
                    if reading is None or reading.water_temp_c is None:
                        continue

                    temp = reading.water_temp_c
                    temps.append(temp)

                    feature = {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [reading.longitude, reading.latitude]},
                        'properties': {'temp_c': round(temp, 2)}
                    }
                    features.append(feature)

            if temps:
                min_temp = min(temps)
                max_temp = max(temps)

                for feature in features:
                    temp = feature['properties']['temp_c']
                    color = HeatmapGenerator._get_color_hex(temp, min_temp, max_temp)
                    feature['properties']['color'] = color

            geojson = {'type': 'FeatureCollection', 'features': features}

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)

            logger.info(f"Generated temperature heatmap: {output_file}")
            if temps:
                logger.info(f"  Temperature range: {min(temps):.2f}°C - {max(temps):.2f}°C")

            return output_file

        except Exception as e:
            logger.error(f"Error creating temperature heatmap: {e}")
            raise
