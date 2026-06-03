#!/usr/bin/env python3
"""
Mapping utilities for Garmin sonar CSV output.
"""

import csv
import json
import math
from pathlib import Path
from typing import Optional, Tuple
import logging

from sonar_schema import parse_sonar_row

logger = logging.getLogger(__name__)


class MapGenerator:
    """Generate map and 3D export files from sonar CSV data."""

    @staticmethod
    def _wgs84_to_local_xy(lat: float, lon: float, origin_lat: float, origin_lon: float) -> Tuple[float, float]:
        """Project WGS84 coordinates to a local ENU plane in meters."""
        lat_rad = math.radians(origin_lat)
        meters_per_deg_lat = 111132.954 - 559.822 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
        meters_per_deg_lon = (111412.84 * math.cos(lat_rad)) - (93.5 * math.cos(3 * lat_rad))
        x = (lon - origin_lon) * meters_per_deg_lon
        y = (lat - origin_lat) * meters_per_deg_lat
        return x, y

    @staticmethod
    def create_geojson(csv_file: Path, output_file: Optional[Path] = None) -> Path:
        """Convert CSV to GeoJSON format for web mapping."""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_map.geojson")

        features = []
        coordinates = []

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reading = parse_sonar_row(row)
                    if reading is None:
                        continue

                    coordinates.append([reading.longitude, reading.latitude])
                    properties = {k: v for k, v in row.items() if k not in ['latitude', 'longitude']}
                    feature = {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [reading.longitude, reading.latitude]},
                        'properties': properties,
                    }
                    features.append(feature)

            if coordinates:
                features.insert(0, {
                    'type': 'Feature',
                    'geometry': {'type': 'LineString', 'coordinates': coordinates},
                    'properties': {'name': 'Track', 'description': 'Sonar GPS track'},
                })

            geojson = {'type': 'FeatureCollection', 'features': features}
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)

            logger.info(f"Generated GeoJSON: {output_file}")
            return output_file
        except Exception as e:
            logger.error(f"Error creating GeoJSON: {e}")
            raise

    @staticmethod
    def create_kml(csv_file: Path, output_file: Optional[Path] = None) -> Path:
        """Convert CSV to KML format."""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_map.kml")

        try:
            kml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sonar Track</name>
    <description>Converted from sonar CSV data</description>
    <Style id="lineStyle">
      <LineStyle>
        <color>ff0000ff</color>
        <width>2</width>
      </LineStyle>
    </Style>
    <Placemark>
      <name>Track</name>
      <styleUrl>#lineStyle</styleUrl>
      <LineString>
        <coordinates>
'''

            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reading = parse_sonar_row(row)
                    if reading is None:
                        continue
                    elev = reading.elevation_m if reading.elevation_m is not None else 0
                    kml_content += f"          {reading.longitude},{reading.latitude},{elev}\n"

            kml_content += '''        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
'''

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(kml_content)

            logger.info(f"Generated KML: {output_file}")
            return output_file
        except Exception as e:
            logger.error(f"Error creating KML: {e}")
            raise

    @staticmethod
    def create_gpx(csv_file: Path, output_file: Optional[Path] = None) -> Path:
        """Convert CSV to GPX format."""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_map.gpx")

        try:
            from datetime import datetime
            timestamp = datetime.now().isoformat()
            gpx_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Garmin Sonar Converter">
  <metadata>
    <time>{timestamp}</time>
  </metadata>
  <trk>
    <name>Track</name>
    <trkseg>
'''

            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    reading = parse_sonar_row(row)
                    if reading is None:
                        continue
                    elev = reading.elevation_m if reading.elevation_m is not None else 0
                    gpx_content += f'''      <trkpt lat="{reading.latitude}" lon="{reading.longitude}">
        <ele>{elev}</ele>
      </trkpt>
'''

            gpx_content += '''    </trkseg>
  </trk>
</gpx>
'''
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(gpx_content)

            logger.info(f"Generated GPX: {output_file}")
            return output_file
        except Exception as e:
            logger.error(f"Error creating GPX: {e}")
            raise

    @staticmethod
    def create_ply(csv_file: Path, output_file: Optional[Path] = None) -> Path:
        """Convert CSV sonar data to an ASCII PLY point cloud."""
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_3d.ply")

        points = []
        origin_lat = None
        origin_lon = None

        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                reading = parse_sonar_row(row)
                if reading is None:
                    continue
                if reading.depth_m is None:
                    continue

                if origin_lat is None or origin_lon is None:
                    origin_lat = reading.latitude
                    origin_lon = reading.longitude

                x, y = MapGenerator._wgs84_to_local_xy(
                    reading.latitude, reading.longitude, origin_lat, origin_lon
                )
                z = -reading.depth_m

                points.append({
                    'x': x,
                    'y': y,
                    'z': z,
                    'intensity_avg': reading.sonar_intensity_avg or 0.0,
                    'intensity_max': reading.sonar_intensity_max or 0.0,
                    'water_temp_c': reading.water_temp_c or 0.0,
                    'sonar_frequency_khz': reading.sonar_frequency_khz or 0.0,
                    'beam_count': reading.beam_count,
                    'frame_number': reading.frame_number or 0,
                })

        if not points:
            raise ValueError('No valid sonar point data found in CSV for 3D export')

        header = [
            'ply',
            'format ascii 1.0',
            f'element vertex {len(points)}',
            'property float x',
            'property float y',
            'property float z',
            'property float intensity_avg',
            'property float intensity_max',
            'property float water_temp_c',
            'property float sonar_frequency_khz',
            'property int beam_count',
            'property int frame_number',
            'end_header',
        ]

        with open(output_file, 'w', encoding='utf-8') as out:
            out.write('\n'.join(header) + '\n')
            for p in points:
                out.write(
                    f"{p['x']:.3f} {p['y']:.3f} {p['z']:.3f} "
                    f"{p['intensity_avg']:.3f} {p['intensity_max']:.3f} "
                    f"{p['water_temp_c']:.3f} {p['sonar_frequency_khz']:.3f} "
                    f"{p['beam_count']} {p['frame_number']}\n"
                )

        logger.info(f"Generated PLY point cloud: {output_file}")
        return output_file
