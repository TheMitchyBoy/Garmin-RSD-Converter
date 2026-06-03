#!/usr/bin/env python3
"""
Garmin Sonar RSD File Parser - Streaming Version
Converts proprietary Garmin Sonar RSD files to CSV with streaming (low memory)
"""

import struct
import csv
from pathlib import Path
from typing import Optional, Tuple
import logging

from geolocation_utils import CoordinateSanitizer, decode_raw_degrees

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class SonarRSDStreamingParser:
    """Parser for Garmin Sonar RSD files with streaming output"""
    
    def __init__(self):
        self.frame_count = 0
        self.total_bytes = 0
        self.metadata = {}
        self.coordinate_sanitizer = CoordinateSanitizer()
    
    def parse_to_csv(self, input_file: Path, output_file: Path, stride: int = 256) -> int:
        """
        Parse sonar RSD file and stream to CSV
        
        Args:
            input_file: Path to sonar RSD file
            output_file: Path to output CSV file
            stride: Sample interval (256 = every 256 bytes)
        
        Returns:
            Number of frames extracted
        """
        logger.info(f"Parsing sonar file: {input_file}")
        logger.info(f"Stride: {stride} bytes")
        
        file_size = input_file.stat().st_size
        logger.info(f"File size: {file_size:,} bytes ({file_size / 1024 / 1024:.1f} MB)")
        
        fieldnames = [
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
        ]
        
        frame_count = 0
        
        try:
            with open(input_file, 'rb') as infile, \
                 open(output_file, 'w', newline='', encoding='utf-8') as outfile:
                
                writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                writer.writeheader()
                
                offset = 0
                last_progress = 0
                
                # Stream through file
                while offset < file_size - 256:
                    try:
                        # Read chunk
                        infile.seek(offset)
                        data = infile.read(256)
                        
                        if len(data) < 64:
                            break
                        
                        # Extract frame data
                        frame_data = self._extract_frame_data(data, offset)
                        
                        if frame_data:
                            writer.writerow(frame_data)
                            frame_count += 1
                            
                            # Progress indicator
                            progress = (offset / file_size) * 100
                            if progress >= last_progress + 5:  # Log every 5%
                                logger.info(f"Progress: {progress:.0f}% ({frame_count} frames)")
                                last_progress = progress
                    
                    except Exception as e:
                        logger.debug(f"Error at offset {offset}: {e}")
                    
                    offset += stride
                
                logger.info(f"Completed: {frame_count} frames extracted")
        
        except Exception as e:
            logger.error(f"Error during parsing: {e}")
            raise
        
        return frame_count
    
    def _extract_frame_data(self, data: bytes, offset: int) -> Optional[dict]:
        """Extract frame data from chunk"""
        if len(data) < 64:
            return None
        
        frame_data = {
            'frame_number': offset // 256,
            'offset': offset,
            'latitude': None,
            'longitude': None,
            'depth_m': None,
            'water_temp_c': None,
            'sonar_frequency_khz': None,
            'sonar_intensity_avg': None,
            'sonar_intensity_max': None,
            'sonar_intensity_count': 0,
        }
        
        has_data = False
        
        try:
            # Extract latitude/longitude from signed int degrees*1e7
            try:
                lat_raw = struct.unpack('<i', data[4:8])[0]
                lon_raw = struct.unpack('<i', data[8:12])[0]

                decoded = decode_raw_degrees(lat_raw, lon_raw)
                if decoded:
                    sanitized = self.coordinate_sanitizer.sanitize(decoded[0], decoded[1])
                    if sanitized:
                        frame_data['latitude'], frame_data['longitude'] = sanitized
                        has_data = True
            except:
                pass
            
            # Extract depth
            try:
                depth_raw = struct.unpack('<H', data[10:12])[0]
                if 0 < depth_raw < 10000:
                    frame_data['depth_m'] = depth_raw * 0.1
                    has_data = True
            except:
                try:
                    depth_raw = struct.unpack('<h', data[12:14])[0]
                    if -5000 < depth_raw < 10000:
                        frame_data['depth_m'] = abs(depth_raw) * 0.01
                        has_data = True
                except:
                    pass
            
            # Extract temperature
            try:
                temp_raw = struct.unpack('<h', data[14:16])[0]
                if -100 < temp_raw < 500:
                    frame_data['water_temp_c'] = temp_raw * 0.1
                    has_data = True
            except:
                pass
            
            # Extract sonar frequency
            try:
                freq = struct.unpack('<H', data[16:18])[0]
                if 0 < freq < 500000:
                    frame_data['sonar_frequency_khz'] = freq / 1000.0
                    has_data = True
            except:
                pass
            
            # Extract sonar intensity data
            sonar_data = []
            for i in range(32, min(256, len(data)), 2):
                try:
                    intensity = struct.unpack('<H', data[i:i+2])[0]
                    if 0 <= intensity < 10000:
                        sonar_data.append(intensity)
                except:
                    break
            
            if sonar_data:
                frame_data['sonar_intensity_avg'] = sum(sonar_data) / len(sonar_data)
                frame_data['sonar_intensity_max'] = max(sonar_data)
                frame_data['sonar_intensity_count'] = len(sonar_data)
                has_data = True
        
        except Exception as e:
            logger.debug(f"Error extracting frame data: {e}")
        
        return frame_data if has_data else None


def convert_sonar_rsd_to_csv(input_file: Path, output_file: Optional[Path] = None, stride: int = 256) -> Tuple[Path, int]:
    """
    Main conversion function
    
    Args:
        input_file: Path to sonar RSD file
        output_file: Path to output CSV file
        stride: Sample interval in bytes
    
    Returns:
        Tuple of (output_path, frame_count)
    """
    input_file = Path(input_file)
    
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    
    if output_file is None:
        output_file = input_file.with_suffix('.csv')
    else:
        output_file = Path(output_file)
    
    logger.info(f"Converting sonar RSD: {input_file} → {output_file}")
    
    parser = SonarRSDStreamingParser()
    frame_count = parser.parse_to_csv(input_file, output_file, stride=stride)
    
    logger.info(f"✓ Conversion complete: {output_file}")
    return output_file, frame_count


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python sonar_converter_streaming.py <input_rsd_file> [output_csv_file] [stride]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    stride = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    
    try:
        result_file, frame_count = convert_sonar_rsd_to_csv(input_file, output_file, stride=stride)
        print(f"✓ Conversion successful!")
        print(f"  Output: {result_file}")
        print(f"  Frames: {frame_count}")
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        sys.exit(1)
