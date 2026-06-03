#!/usr/bin/env python3
"""
Fish detection and tracking from sonar data.
Identifies fish schools and individual fish based on sonar intensity patterns.
"""

import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
from collections import defaultdict

from map_visuals import FISH_SIZE_LEGEND

logger = logging.getLogger(__name__)


@dataclass
class FishDetection:
    """Represents a detected fish or school"""
    latitude: float
    longitude: float
    depth: float
    intensity: float
    confidence: float  # 0.0-1.0
    size_category: str  # 'small', 'medium', 'large', 'school'
    frame_number: int
    timestamp: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'depth': self.depth,
            'intensity': self.intensity,
            'confidence': self.confidence,
            'size': self.size_category,
            'frame_number': self.frame_number,
            'timestamp': self.timestamp,
        }


class FishDetector:
    """Detect fish from sonar intensity patterns"""
    
    # Heuristic thresholds for fish detection
    # These are tuned based on typical sonar responses to fish
    MIN_FISH_INTENSITY = 40  # Minimum intensity to consider as potential fish
    MAX_FISH_INTENSITY = 200  # Fish rarely exceed this intensity
    
    # Depth ranges where fish are commonly found (in meters)
    MIN_FISH_DEPTH = 2
    MAX_FISH_DEPTH = 500

    SIZE_STYLES = FISH_SIZE_LEGEND
    
    @staticmethod
    def detect_fish(
        csv_file: Path,
        output_file: Optional[Path] = None,
        min_intensity: int = MIN_FISH_INTENSITY,
        max_intensity: int = MAX_FISH_INTENSITY
    ) -> Tuple[Path, List[FishDetection]]:
        """
        Detect potential fish signatures in sonar data.
        
        Args:
            csv_file: Input CSV file
            output_file: Output GeoJSON file for detections
            min_intensity: Minimum sonar intensity to consider
            max_intensity: Maximum sonar intensity (above this is likely noise/seafloor)
        
        Returns:
            Tuple of (output file path, list of detections)
        """
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_fish_detections.geojson")
        
        logger.info(f"Detecting fish signatures (intensity range: {min_intensity}-{max_intensity})...")
        
        detections: List[FishDetection] = []
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        lat = float(row.get('latitude', '') or 0)
                        lon = float(row.get('longitude', '') or 0)
                        depth = float(row.get('depth_m', '') or 0)
                        intensity = float(row.get('sonar_intensity_avg', '') or 0)
                        intensity_max = float(row.get('sonar_intensity_max', '') or 0)
                        frame_num = int(row.get('frame_number', '') or 0)
                        
                        if lat == 0 and lon == 0:
                            continue
                        
                        # Check if this reading matches fish characteristics
                        if min_intensity <= intensity <= max_intensity and \
                           FishDetector.MIN_FISH_DEPTH <= depth <= FishDetector.MAX_FISH_DEPTH:
                            
                            size_category, confidence = FishDetector._classify_fish(
                                intensity, intensity_max, depth
                            )
                            
                            detection = FishDetection(
                                latitude=lat,
                                longitude=lon,
                                depth=depth,
                                intensity=intensity,
                                confidence=confidence,
                                size_category=size_category,
                                frame_number=frame_num,
                            )
                            detections.append(detection)
                    
                    except (ValueError, TypeError):
                        continue
            
            # Export detections as GeoJSON
            features = []
            for detection in detections:
                style = FishDetector._get_size_style(detection.size_category)
                color = style['color']
                
                feature = {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [detection.longitude, detection.latitude]
                    },
                    'properties': {
                        'depth_m': round(detection.depth, 2),
                        'intensity': round(detection.intensity, 2),
                        'confidence': round(detection.confidence, 3),
                        'size': detection.size_category,
                        'frame': detection.frame_number,
                        'color': color,
                        'marker-color': color,
                        'marker-size': style['marker_size'],
                        'marker-symbol': style['marker_symbol'],
                        'fill': color,
                        'fill-opacity': round(0.45 + detection.confidence * 0.45, 2),
                        'stroke': '#0f172a',
                        'stroke-width': 1.5,
                    }
                }
                features.append(feature)
            
            geojson = {'type': 'FeatureCollection', 'features': features}
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)
            
            logger.info(f"Fish detection complete!")
            logger.info(f"  Total detections: {len(detections)}")
            logger.info(f"  Exported to: {output_file}")
            
            # Log detection summary
            size_counts = defaultdict(int)
            for detection in detections:
                size_counts[detection.size_category] += 1
            
            for size, count in sorted(size_counts.items()):
                logger.info(f"  {size}: {count} ({count/len(detections)*100:.1f}%)")
            
            return output_file, detections
        
        except Exception as e:
            logger.error(f"Error detecting fish: {e}")
            raise
    
    @staticmethod
    def _classify_fish(intensity: float, intensity_max: float, depth: float) -> Tuple[str, float]:
        """
        Classify detected fish by size and assign confidence.
        
        Returns:
            Tuple of (size_category, confidence)
        """
        # Higher intensity ratio suggests larger fish/school
        intensity_ratio = intensity_max / max(intensity, 1)
        
        # Depth penalty: fish are easier to detect at intermediate depths
        depth_score = 1.0 - abs(depth - 100) / 400
        depth_score = max(0.5, depth_score)  # Min 50% confidence from depth
        
        # Determine size category based on intensity
        if intensity > 120:
            size_category = 'school'
            base_confidence = 0.85
        elif intensity > 80:
            size_category = 'large'
            base_confidence = 0.75
        elif intensity > 60:
            size_category = 'medium'
            base_confidence = 0.70
        else:
            size_category = 'small'
            base_confidence = 0.60
        
        # Combine confidence scores
        confidence = min(0.99, base_confidence * depth_score * (1 + intensity_ratio * 0.1))
        
        return size_category, confidence
    
    @staticmethod
    def _get_size_color(size: str) -> str:
        """Get color for fish size category (aligned with map legend)."""
        return FishDetector._get_size_style(size)['color']

    @staticmethod
    def _get_size_style(size: str) -> Dict[str, str]:
        """Get map styling for fish size category."""
        return FishDetector.SIZE_STYLES.get(str(size).lower(), {
            'color': '#64748b',
            'label': 'Unknown',
            'marker_size': 'medium',
            'marker_symbol': 'circle',
        })
    
    @staticmethod
    def aggregate_fish_by_location(
        detections: List[FishDetection],
        grid_size: float = 0.01
    ) -> Dict[Tuple[int, int], Dict]:
        """
        Aggregate fish detections into grid cells.
        Useful for understanding fish distribution.
        """
        grid: Dict[Tuple[int, int], Dict] = defaultdict(lambda: {
            'count': 0,
            'intensities': [],
            'depths': [],
            'avg_confidence': [],
        })
        
        for detection in detections:
            grid_x = int(detection.longitude / grid_size)
            grid_y = int(detection.latitude / grid_size)
            key = (grid_x, grid_y)
            
            grid[key]['count'] += 1
            grid[key]['intensities'].append(detection.intensity)
            grid[key]['depths'].append(detection.depth)
            grid[key]['avg_confidence'].append(detection.confidence)
        
        # Calculate statistics
        result = {}
        for key, data in grid.items():
            result[key] = {
                'count': data['count'],
                'intensity_avg': sum(data['intensities']) / len(data['intensities']),
                'depth_avg': sum(data['depths']) / len(data['depths']),
                'confidence_avg': sum(data['avg_confidence']) / len(data['avg_confidence']),
            }
        
        return result
    
    @staticmethod
    def detect_fish_schools(
        detections: List[FishDetection],
        proximity_threshold: float = 0.01  # ~1km
    ) -> List[Dict]:
        """
        Identify fish schools (clusters of detections).
        
        Args:
            detections: List of individual fish detections
            proximity_threshold: Max distance in degrees for clustering
        
        Returns:
            List of identified schools with statistics
        """
        schools = []
        used = set()
        
        for i, detection in enumerate(detections):
            if i in used or detection.size_category != 'school':
                continue
            
            # Find nearby detections
            cluster = [i]
            used.add(i)
            
            for j, other in enumerate(detections):
                if j in used:
                    continue
                
                distance = math.sqrt(
                    (detection.latitude - other.latitude) ** 2 +
                    (detection.longitude - other.longitude) ** 2
                )
                
                if distance < proximity_threshold:
                    cluster.append(j)
                    used.add(j)
            
            # Calculate school statistics
            cluster_detections = [detections[idx] for idx in cluster]
            
            school = {
                'size': len(cluster),
                'center_lat': sum(d.latitude for d in cluster_detections) / len(cluster),
                'center_lon': sum(d.longitude for d in cluster_detections) / len(cluster),
                'avg_depth': sum(d.depth for d in cluster_detections) / len(cluster),
                'avg_intensity': sum(d.intensity for d in cluster_detections) / len(cluster),
                'avg_confidence': sum(d.confidence for d in cluster_detections) / len(cluster),
                'detections': cluster,
            }
            schools.append(school)
        
        logger.info(f"Identified {len(schools)} fish schools")
        return schools
