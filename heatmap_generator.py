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

from map_visuals import (
    bathymetry_color,
    grid_cell_polygon,
    grid_center,
    grid_key,
    intensity_color,
)

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
            'depth_min': min(self.depths) if self.depths else None,
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
    def build_depth_grid(
        csv_file: Path,
        grid_size: float = 0.01,
    ) -> Tuple[Dict[Tuple[int, int], float], Dict]:
        """
        Build a sparse depth grid keyed by (grid_x, grid_y) -> average depth (m).

        Shared by depth heatmaps, contour generation, GeoTIFF export, and
        survey comparison. Returns grid dict plus metadata (min/max indices and
        depth range) for raster sizing and legend scaling.
        """
        grid: Dict[Tuple[int, int], GridCell] = {}

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed = HeatmapGenerator._read_csv_row(row)
                if parsed is None:
                    continue
                lat, lon, intensity, depth, temp = parsed
                if depth is None or depth <= 0:
                    continue
                key = grid_key(lon, lat, grid_size)
                if key not in grid:
                    cell_lat, cell_lon = grid_center(key, grid_size)
                    grid[key] = GridCell(cell_lat, cell_lon)
                grid[key].add_reading(intensity, depth, temp)

        depth_grid: Dict[Tuple[int, int], float] = {}
        depths: List[float] = []
        for key, cell in grid.items():
            stats = cell.get_stats()
            if stats.get("depth_avg") is not None:
                depth_grid[key] = stats["depth_avg"]
                depths.append(stats["depth_avg"])

        if not depth_grid:
            return {}, {"grid_size": grid_size, "cell_count": 0}

        gxs = [k[0] for k in depth_grid]
        gys = [k[1] for k in depth_grid]
        meta = {
            "grid_size": grid_size,
            "cell_count": len(depth_grid),
            "min_gx": min(gxs),
            "max_gx": max(gxs),
            "min_gy": min(gys),
            "max_gy": max(gys),
            "depth_min_m": min(depths),
            "depth_max_m": max(depths),
        }
        return depth_grid, meta

    @staticmethod
    def create_depth_contours(
        csv_file: Path,
        interval_m: float = 1.0,
        grid_size: float = 0.01,
        output_file: Optional[Path] = None,
    ) -> Path:
        """
        Generate bathymetric contour lines as GeoJSON LineStrings.

        Args:
            csv_file: Input sonar CSV
            interval_m: Contour interval in meters (default 1.0)
            grid_size: Grid resolution in degrees
            output_file: Output GeoJSON path
        """
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_depth_contours.geojson")
        else:
            output_file = Path(output_file)

        depth_grid, meta = HeatmapGenerator.build_depth_grid(csv_file, grid_size)
        if not depth_grid:
            geojson = {
                "type": "FeatureCollection",
                "properties": {"contour_interval_m": interval_m},
                "features": [],
            }
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(geojson, f, indent=2)
            return output_file

        min_gx = meta["min_gx"]
        max_gx = meta["max_gx"]
        min_gy = meta["min_gy"]
        max_gy = meta["max_gy"]
        width = max_gx - min_gx + 1
        height = max_gy - min_gy + 1

        nodata = float("nan")
        field: List[List[float]] = []
        for gy in range(min_gy, max_gy + 1):
            row: List[float] = []
            for gx in range(min_gx, max_gx + 1):
                val = depth_grid.get((gx, gy))
                row.append(val if val is not None else nodata)
            field.append(row)

        depth_min = meta["depth_min_m"]
        depth_max = meta["depth_max_m"]
        levels = HeatmapGenerator._contour_levels(depth_min, depth_max, interval_m)

        features = []
        for level in levels:
            segments = HeatmapGenerator._marching_squares(
                field, level, min_gx, min_gy, grid_size,
            )
            for seg in segments:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": seg,
                    },
                    "properties": {
                        "layer": "depth_contour",
                        "depth_m": round(level, 2),
                        "interval_m": interval_m,
                    },
                })

        geojson = {
            "type": "FeatureCollection",
            "properties": {
                "contour_interval_m": interval_m,
                "grid_size_deg": grid_size,
                "depth_min_m": round(depth_min, 2),
                "depth_max_m": round(depth_max, 2),
                "contour_count": len(levels),
            },
            "features": features,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(geojson, f, indent=2)

        logger.info(f"Generated depth contours: {output_file} ({len(features)} segments)")
        return output_file

    @staticmethod
    def _contour_levels(min_depth: float, max_depth: float, interval: float) -> List[float]:
        if interval <= 0:
            interval = 1.0
        start = math.ceil(min_depth / interval) * interval
        levels = []
        level = start
        while level <= max_depth + interval * 0.001:
            levels.append(round(level, 4))
            level += interval
        return levels

    @staticmethod
    def _marching_squares(
        field: List[List[float]],
        level: float,
        min_gx: int,
        min_gy: int,
        grid_size: float,
    ) -> List[List[List[float]]]:
        """Extract contour line segments at a given depth level from a 2D scalar field."""
        height = len(field)
        width = len(field[0]) if height else 0
        segments: List[List[List[float]]] = []

        def val_at(col: int, row: int) -> float:
            if 0 <= row < height and 0 <= col < width:
                v = field[row][col]
                if v != v:  # NaN
                    return level
                return v
            return level

        def to_lon_lat(gx: float, gy: float) -> List[float]:
            lon = (min_gx + gx) * grid_size
            lat = (min_gy + gy) * grid_size
            return [lon, lat]

        def interp(
            x1: float, y1: float, v1: float,
            x2: float, y2: float, v2: float,
        ) -> List[float]:
            if abs(v2 - v1) < 1e-9:
                t = 0.5
            else:
                t = (level - v1) / (v2 - v1)
            t = max(0.0, min(1.0, t))
            return to_lon_lat(x1 + t * (x2 - x1), y1 + t * (y2 - y1))

        for row in range(height - 1):
            for col in range(width - 1):
                v0 = val_at(col, row)
                v1 = val_at(col + 1, row)
                v2 = val_at(col + 1, row + 1)
                v3 = val_at(col, row + 1)

                # Classic marching squares: 4-bit case index from corner comparisons
                case = 0
                if v0 >= level:
                    case |= 1
                if v1 >= level:
                    case |= 2
                if v2 >= level:
                    case |= 4
                if v3 >= level:
                    case |= 8

                if case in (0, 15):
                    continue

                x, y = float(col), float(row)
                top = interp(x, y, v0, x + 1, y, v1)
                right = interp(x + 1, y, v1, x + 1, y + 1, v2)
                bottom = interp(x, y + 1, v3, x + 1, y + 1, v2)
                left = interp(x, y, v0, x, y + 1, v3)

                edge_map: Dict[int, List[List[List[float]]]] = {
                    1: [[left, bottom]],
                    2: [[bottom, right]],
                    3: [[left, right]],
                    4: [[right, top]],
                    5: [[left, top], [bottom, right]],
                    6: [[bottom, top]],
                    7: [[left, top]],
                    8: [[top, left]],
                    9: [[bottom, top]],
                    10: [[top, right], [bottom, left]],
                    11: [[right, top]],
                    12: [[right, left]],
                    13: [[bottom, left]],
                    14: [[right, bottom]],
                }

                for seg in edge_map.get(case, []):
                    segments.append(seg)

        return segments
    
    @staticmethod
    def _get_color_hex(value: float, min_val: float, max_val: float) -> str:
        """Backward-compatible alias for intensity coloring."""
        return intensity_color(value, min_val, max_val)

    @staticmethod
    def _read_csv_row(row: dict) -> Optional[Tuple[float, float, float, Optional[float], Optional[float]]]:
        """Parse a CSV row into lat, lon, intensity, depth, temp."""
        try:
            lat = float(row.get('latitude', '') or 0)
            lon = float(row.get('longitude', '') or 0)
            if lat == 0 and lon == 0:
                return None
            intensity = float(row.get('sonar_intensity_avg', '') or 0)
            depth_raw = row.get('depth_m')
            depth = float(depth_raw) if depth_raw not in (None, '') else None
            temp_raw = row.get('water_temp_c')
            temp = float(temp_raw) if temp_raw not in (None, '') else None
            return lat, lon, intensity, depth, temp
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _polygon_feature(
        lon: float,
        lat: float,
        grid_size: float,
        properties: Dict,
    ) -> Dict:
        return {
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [grid_cell_polygon(lon, lat, grid_size)],
            },
            'properties': properties,
        }
    
    @staticmethod
    def create_intensity_heatmap(
        csv_file: Path,
        grid_size: float = 0.01,  # ~1km at equator
        output_file: Optional[Path] = None,
        use_polygons: bool = True,
    ) -> Path:
        """
        Create a heatmap of sonar intensity readings.
        
        Args:
            csv_file: Input CSV file
            grid_size: Size of grid cells in degrees (default 0.01 ≈ 1km at equator)
            output_file: Output GeoJSON heatmap file
            use_polygons: Use grid polygons instead of center points for clearer maps
        
        Returns:
            Path to generated heatmap
        """
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_intensity_heatmap.geojson")
        
        logger.info(f"Generating intensity heatmap with grid size {grid_size}°...")
        
        grid: Dict[Tuple[int, int], GridCell] = {}
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    parsed = HeatmapGenerator._read_csv_row(row)
                    if parsed is None:
                        continue
                    lat, lon, intensity, depth, temp = parsed
                    key = grid_key(lon, lat, grid_size)
                    if key not in grid:
                        cell_lat, cell_lon = grid_center(key, grid_size)
                        grid[key] = GridCell(cell_lat, cell_lon)
                    grid[key].add_reading(intensity, depth, temp)
            
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
                    color = intensity_color(intensity_avg, min_intensity, max_intensity)
                    props = {
                        'layer': 'intensity',
                        'intensity_avg': round(intensity_avg, 2),
                        'intensity_max': round(stats['intensity_max'], 2),
                        'intensity_min': round(stats['intensity_min'], 2),
                        'point_count': stats['point_count'],
                        'depth_avg': round(stats['depth_avg'], 2) if stats['depth_avg'] else None,
                        'temp_avg': round(stats['temp_avg'], 2) if stats['temp_avg'] else None,
                        'color': color,
                        'fill_opacity': 0.72,
                    }
                    if use_polygons:
                        features.append(HeatmapGenerator._polygon_feature(
                            cell.lon, cell.lat, grid_size, props,
                        ))
                    else:
                        features.append({
                            'type': 'Feature',
                            'geometry': {
                                'type': 'Point',
                                'coordinates': [cell.lon, cell.lat],
                            },
                            'properties': props,
                        })
            
            geojson = {
                'type': 'FeatureCollection',
                'properties': {
                    'heatmap_type': 'intensity',
                    'grid_size_deg': grid_size,
                },
                'features': features,
            }
            
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
        grid_size: float = 0.01,
        output_file: Optional[Path] = None,
        use_polygons: bool = True,
    ) -> Path:
        """
        Create a gridded bathymetry (seabed depth) heatmap.

        Uses a bathymetric color ramp (shallow cyan -> deep navy) on aggregated
        grid cells for clearer seabed mapping than raw per-frame points.
        """
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_depth_heatmap.geojson")
        
        logger.info(f"Generating depth (bathymetry) heatmap with grid size {grid_size}°...")
        
        grid: Dict[Tuple[int, int], GridCell] = {}
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    parsed = HeatmapGenerator._read_csv_row(row)
                    if parsed is None:
                        continue
                    lat, lon, intensity, depth, temp = parsed
                    if depth is None or depth <= 0:
                        continue

                    key = grid_key(lon, lat, grid_size)
                    if key not in grid:
                        cell_lat, cell_lon = grid_center(key, grid_size)
                        grid[key] = GridCell(cell_lat, cell_lon)
                    grid[key].add_reading(intensity, depth, temp)
            
            features = []
            depths = [
                cell.get_stats()['depth_avg']
                for cell in grid.values()
                if cell.get_stats() and cell.get_stats().get('depth_avg') is not None
            ]
            
            if depths:
                min_depth = min(depths)
                max_depth = max(depths)
                
                for cell in grid.values():
                    stats = cell.get_stats()
                    if not stats or stats.get('depth_avg') is None:
                        continue
                    
                    depth_avg = stats['depth_avg']
                    color = bathymetry_color(depth_avg, min_depth, max_depth)
                    props = {
                        'layer': 'seabed',
                        'depth_m': round(depth_avg, 2),
                        'depth_min': round(stats['depth_min'], 2) if stats.get('depth_min') else None,
                        'depth_max': round(stats['depth_max'], 2) if stats.get('depth_max') else None,
                        'point_count': stats['point_count'],
                        'color': color,
                        'fill_opacity': 0.78,
                    }
                    if use_polygons:
                        features.append(HeatmapGenerator._polygon_feature(
                            cell.lon, cell.lat, grid_size, props,
                        ))
                    else:
                        features.append({
                            'type': 'Feature',
                            'geometry': {
                                'type': 'Point',
                                'coordinates': [cell.lon, cell.lat],
                            },
                            'properties': props,
                        })
            
            geojson = {
                'type': 'FeatureCollection',
                'properties': {
                    'heatmap_type': 'bathymetry',
                    'grid_size_deg': grid_size,
                    'depth_min_m': round(min(depths), 2) if depths else None,
                    'depth_max_m': round(max(depths), 2) if depths else None,
                },
                'features': features,
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)
            
            logger.info(f"Generated depth heatmap: {output_file}")
            if depths:
                logger.info(f"  Grid cells: {len(features)}")
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
        grid_size: float = 0.01,
        output_file: Optional[Path] = None,
        use_polygons: bool = True,
    ) -> Path:
        """Create a gridded heatmap of water temperature variations."""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_temperature_heatmap.geojson")
        
        logger.info(f"Generating temperature heatmap with grid size {grid_size}°...")
        
        grid: Dict[Tuple[int, int], GridCell] = {}
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    parsed = HeatmapGenerator._read_csv_row(row)
                    if parsed is None:
                        continue
                    lat, lon, intensity, depth, temp = parsed
                    if temp is None or temp == 0:
                        continue

                    key = grid_key(lon, lat, grid_size)
                    if key not in grid:
                        cell_lat, cell_lon = grid_center(key, grid_size)
                        grid[key] = GridCell(cell_lat, cell_lon)
                    grid[key].add_reading(intensity, depth, temp)
            
            features = []
            temps = [
                cell.get_stats()['temp_avg']
                for cell in grid.values()
                if cell.get_stats() and cell.get_stats().get('temp_avg') is not None
            ]
            
            if temps:
                min_temp = min(temps)
                max_temp = max(temps)
                
                for cell in grid.values():
                    stats = cell.get_stats()
                    if not stats or stats.get('temp_avg') is None:
                        continue
                    
                    temp_avg = stats['temp_avg']
                    color = intensity_color(temp_avg, min_temp, max_temp)
                    props = {
                        'layer': 'temperature',
                        'temp_c': round(temp_avg, 2),
                        'point_count': stats['point_count'],
                        'color': color,
                        'fill_opacity': 0.72,
                    }
                    if use_polygons:
                        features.append(HeatmapGenerator._polygon_feature(
                            cell.lon, cell.lat, grid_size, props,
                        ))
                    else:
                        features.append({
                            'type': 'Feature',
                            'geometry': {
                                'type': 'Point',
                                'coordinates': [cell.lon, cell.lat],
                            },
                            'properties': props,
                        })
            
            geojson = {
                'type': 'FeatureCollection',
                'properties': {
                    'heatmap_type': 'temperature',
                    'grid_size_deg': grid_size,
                },
                'features': features,
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)
            
            logger.info(f"Generated temperature heatmap: {output_file}")
            if temps:
                logger.info(f"  Temperature range: {min(temps):.2f}°C - {max(temps):.2f}°C")
            
            return output_file
        
        except Exception as e:
            logger.error(f"Error creating temperature heatmap: {e}")
            raise
