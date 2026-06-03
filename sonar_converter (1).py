#!/usr/bin/env python3
"""
Garmin Sonar RSD File Parser
Converts proprietary Garmin Sonar RSD files to CSV and mapping formats
"""

import struct
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class SonarFrame:
    """Represents a single sonar frame/ping"""
    timestamp: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    depth_meters: Optional[float] = None
    water_temperature: Optional[float] = None
    sonar_frequency: Optional[float] = None
    sonar_intensity: Optional[List[int]] = None
    frame_number: Optional[int] = None
    ping_rate: Optional[float] = None
    beam_count: Optional[int] = None
    
    def to_dict(self) -> Dict:
        """Convert frame to dictionary"""
        intensity_avg = sum(self.sonar_intensity) / len(self.sonar_intensity) if self.sonar_intensity else None
        intensity_max = max(self.sonar_intensity) if self.sonar_intensity else None
        
        return {
            'timestamp': self.timestamp,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'depth_m': self.depth_meters,
            'water_temp_c': self.water_temperature,
            'sonar_frequency_khz': self.sonar_frequency,
            'sonar_intensity_avg': intensity_avg,
            'sonar_intensity_max': intensity_max,
            'beam_count': self.beam_count,
            'frame_number': self.frame_number,
            'ping_rate': self.ping_rate,
        }


class SonarRSDParser:
    """Parser for Garmin Sonar RSD files"""
    
    # Garmin Sonar format signatures
    SONAR_FRAME_HEADER = 0x06  # Typical sonar frame header
    
    def __init__(self):
        self.frames: List[SonarFrame] = []
        self.metadata: Dict = {}
    
    def parse(self, file_path: Path) -> List[SonarFrame]:
        """Parse sonar RSD file"""
        logger.info(f"Parsing sonar file: {file_path}")
        
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            logger.info(f"File size: {len(file_data)} bytes")
            
            # Try to extract frames
            self._scan_for_frames(file_data)
            
            logger.info(f"Extracted {len(self.frames)} sonar frames")
            return self.frames
            
        except Exception as e:
            logger.error(f"Error parsing sonar file: {e}")
            raise
    
    def _scan_for_frames(self, data: bytes) -> None:
        """Scan binary data for sonar frames with stride"""
        frame_count = 0
        offset = 0
        stride = 256  # Sample every 256 bytes for speed
        
        # First pass - estimate frame size and content
        logger.info("Scanning file structure...")
        
        while offset < len(data) - 256:
            # Look for frame markers at stride intervals
            try:
                frame = self._extract_sonar_data(data, offset)
                if frame and (frame.depth_meters or frame.sonar_intensity):
                    self.frames.append(frame)
                    frame_count += 1
                    if frame_count % 50 == 0:
                        logger.info(f"Progress: {frame_count} frames extracted...")
            except Exception as e:
                logger.debug(f"Error at offset {offset}: {e}")
            
            offset += stride
        
        logger.info(f"Completed: extracted {frame_count} frames")
    
    def _is_potential_frame_header(self, data: bytes, offset: int) -> bool:
        """Check if offset points to a potential frame header"""
        if offset + 4 > len(data):
            return False
        
        # Look for common Garmin sonar frame patterns
        byte1 = data[offset]
        
        # Check for known frame start bytes
        return byte1 in [0x06, 0x07, 0x0B]
    
    def _extract_sonar_data(self, data: bytes, offset: int) -> Optional[SonarFrame]:
        """Extract sonar data from any offset in the file"""
        if offset + 64 > len(data):
            return None
        
        frame = SonarFrame()
        frame.frame_number = offset // 256
        
        try:
            # Extract depth value (usually around offset 10-14)
            try:
                # Try different interpretations
                depth_raw = struct.unpack('<H', data[offset+10:offset+12])[0]
                if 0 < depth_raw < 10000:  # Reasonable depth range
                    frame.depth_meters = depth_raw * 0.1
            except:
                try:
                    depth_raw = struct.unpack('<h', data[offset+12:offset+14])[0]
                    if -5000 < depth_raw < 10000:
                        frame.depth_meters = abs(depth_raw) * 0.01
                except:
                    pass
            
            # Extract water temperature
            try:
                temp_raw = struct.unpack('<h', data[offset+14:offset+16])[0]
                if -100 < temp_raw < 500:  # Reasonable temp range (-10 to 50C)
                    frame.water_temperature = temp_raw * 0.1
            except:
                pass
            
            # Extract coordinates if available
            try:
                lat_raw = struct.unpack('<i', data[offset+4:offset+8])[0]
                lon_raw = struct.unpack('<i', data[offset+8:offset+12])[0]
                
                # Check if values look like coordinates
                if abs(lat_raw) < 100000000 and abs(lon_raw) < 100000000:
                    frame.latitude = lat_raw / 10000000.0
                    frame.longitude = lon_raw / 10000000.0
            except:
                pass
            
            # Extract sonar intensity data (variable length)
            sonar_data = []
            for i in range(32, min(offset + 128, len(data) - offset), 2):
                try:
                    intensity = struct.unpack('<H', data[offset+i:offset+i+2])[0]
                    if intensity < 10000:  # Filter outliers
                        sonar_data.append(intensity)
                except:
                    break
            
            if sonar_data:
                frame.sonar_intensity = sonar_data
                frame.beam_count = len(sonar_data)
            
            return frame if (frame.depth_meters or frame.sonar_intensity) else None
            
        except Exception as e:
            logger.debug(f"Error extracting sonar data at {offset}: {e}")
            return None
    
    def extract_summary(self) -> Dict:
        """Extract file summary statistics"""
        if not self.frames:
            return {}
        
        valid_depths = [f.depth_meters for f in self.frames if f.depth_meters]
        valid_temps = [f.water_temperature for f in self.frames if f.water_temperature]
        
        summary = {
            'total_frames': len(self.frames),
            'avg_depth_m': sum(valid_depths) / len(valid_depths) if valid_depths else None,
            'max_depth_m': max(valid_depths) if valid_depths else None,
            'min_depth_m': min(valid_depths) if valid_depths else None,
            'avg_water_temp_c': sum(valid_temps) / len(valid_temps) if valid_temps else None,
            'max_water_temp_c': max(valid_temps) if valid_temps else None,
            'min_water_temp_c': min(valid_temps) if valid_temps else None,
        }
        
        return summary


class SonarCSVExporter:
    """Export sonar frames to CSV"""
    
    @staticmethod
    def export(frames: List[SonarFrame], output_path: Path) -> None:
        """Export frames to CSV"""
        if not frames:
            logger.warning("No frames to export")
            return
        
        fieldnames = [
            'timestamp',
            'latitude',
            'longitude',
            'depth_m',
            'water_temp_c',
            'sonar_frequency_khz',
            'sonar_intensity_avg',
            'sonar_intensity_max',
            'beam_count',
            'frame_number',
            'ping_rate',
        ]
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for frame in frames:
                    writer.writerow(frame.to_dict())
            
            logger.info(f"Exported {len(frames)} frames to {output_path}")
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")
            raise


class SonarMapGenerator:
    """Generate maps from sonar data"""
    
    @staticmethod
    def create_sonar_geojson(frames: List[SonarFrame], output_path: Path) -> Path:
        """Create GeoJSON with sonar depth data"""
        import json
        
        features = []
        coordinates = []
        
        for i, frame in enumerate(frames):
            if frame.latitude and frame.longitude:
                coordinates.append([frame.longitude, frame.latitude])
                
                # Create feature with depth as property
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [frame.longitude, frame.latitude]
                    },
                    "properties": {
                        "depth_m": frame.depth_meters,
                        "temp_c": frame.water_temperature,
                        "intensity_avg": frame.to_dict()['sonar_intensity_avg'],
                        "frame_num": frame.frame_number,
                    }
                }
                features.append(feature)
        
        # Add track line
        if coordinates:
            track_feature = {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates
                },
                "properties": {
                    "name": "Sonar Survey Track",
                    "frames": len(coordinates)
                }
            }
            features.insert(0, track_feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        with open(output_path, 'w') as f:
            json.dump(geojson, f, indent=2)
        
        logger.info(f"Generated GeoJSON: {output_path}")
        return output_path
    
    @staticmethod
    def create_sonar_gpx(frames: List[SonarFrame], output_path: Path) -> Path:
        """Create GPX with sonar waypoints"""
        gpx_content = '''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Garmin Sonar Converter">
  <metadata>
    <time>{timestamp}</time>
  </metadata>
  <trk>
    <name>Sonar Survey</name>
    <trkseg>
'''
        
        timestamp = datetime.now().isoformat()
        gpx_content = gpx_content.format(timestamp=timestamp)
        
        for frame in frames:
            if frame.latitude and frame.longitude:
                gpx_content += f'''      <trkpt lat="{frame.latitude}" lon="{frame.longitude}">
        <ele>{frame.depth_meters if frame.depth_meters else 0}</ele>
        <extensions>
          <depth>{frame.depth_meters}</depth>
          <water_temp>{frame.water_temperature}</water_temp>
        </extensions>
      </trkpt>
'''
        
        gpx_content += '''    </trkseg>
  </trk>
</gpx>
'''
        
        with open(output_path, 'w') as f:
            f.write(gpx_content)
        
        logger.info(f"Generated GPX: {output_path}")
        return output_path


def convert_sonar_rsd_to_csv(input_file: Path, output_file: Optional[Path] = None) -> Path:
    """
    Main conversion function for sonar RSD files
    
    Args:
        input_file: Path to sonar RSD file
        output_file: Path to output CSV file
    
    Returns:
        Path to generated CSV file
    """
    input_file = Path(input_file)
    
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    if output_file is None:
        output_file = input_file.with_suffix('.csv')
    else:
        output_file = Path(output_file)
    
    logger.info(f"Converting sonar RSD: {input_file} → {output_file}")
    
    # Parse sonar file
    parser = SonarRSDParser()
    frames = parser.parse(input_file)
    
    if not frames:
        logger.warning("No sonar frames extracted from file")
        return output_file
    
    # Export to CSV
    SonarCSVExporter.export(frames, output_file)
    
    # Generate summary
    summary = parser.extract_summary()
    logger.info("\n=== Sonar Survey Summary ===")
    for key, value in summary.items():
        if value is not None:
            logger.info(f"{key}: {value}")
    
    return output_file


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python sonar_converter.py <input_rsd_file> [output_csv_file]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        result = convert_sonar_rsd_to_csv(input_file, output_file)
        print(f"✓ Conversion successful: {result}")
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        sys.exit(1)
