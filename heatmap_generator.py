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
