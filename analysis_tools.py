#!/usr/bin/env python3
"""
Mapping utilities for Garmin sonar CSV output.
"""

import csv
import math
from pathlib import Path
from typing import Optional, Tuple
import logging

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
                    try:
                        lat = float(row.get('latitude', '') or 0)
                        lon = float(row.get('longitude', '') or 0)
                        if lat == 0 and lon == 0:
                            continue

                        coordinates.append([lon, lat])
                        properties = {k: v for k, v in row.items() if k not in ['latitude', 'longitude']}
                        feature = {
                            'type': 'Feature',
                            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                            'properties': properties,
                        }
                        features.append(feature)
                    except (ValueError, TypeError):
                        continue

            if coordinates:
                features.insert(0, {
                    'type': 'Feature',
                    'geometry': {'type': 'LineString', 'coordinates': coordinates},
                    'properties': {'name': 'Track', 'description': 'Sonar GPS track'},
                })

            geojson = {'type': 'FeatureCollection', 'features': features}
            import json
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(geojson, f, indent=2)

            logger.info(f"Generated GeoJSON: {output_file}")
            return output_file
        except Exception as e:
            logger.error(f"Error creating GeoJSON: {e}")
            raise

    @staticmethod
    def _track_elevation(row: dict) -> float:
        """Pick a track elevation value for KML/GPX.

        Prefer an explicit ``elevation`` column when present (e.g. the boat's
        altitude above sea level). Otherwise fall back to negative depth so the
        track sits on the seafloor in 3D viewers. Returns 0.0 when neither is
        available.
        """
        for key in ('elevation', 'altitude_m', 'altitude'):
            value = row.get(key)
            if value in (None, ''):
                continue
            try:
                return float(value)
            except (ValueError, TypeError):
                continue

        depth = row.get('depth_m')
        if depth not in (None, ''):
            try:
                return -float(depth)
            except (ValueError, TypeError):
                pass
        return 0.0

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
        <altitudeMode>absolute</altitudeMode>
        <coordinates>
'''

            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        lat = float(row.get('latitude', '') or 0)
                        lon = float(row.get('longitude', '') or 0)
                        if lat == 0 and lon == 0:
                            continue
                        elev = MapGenerator._track_elevation(row)
                        kml_content += f"          {lon},{lat},{elev}\n"
                    except (ValueError, TypeError):
                        continue

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
                    try:
                        lat = float(row.get('latitude', '') or 0)
                        lon = float(row.get('longitude', '') or 0)
                        if lat == 0 and lon == 0:
                            continue
                        elev = MapGenerator._track_elevation(row)
                        depth_raw = row.get('depth_m')
                        try:
                            depth_val = float(depth_raw) if depth_raw not in (None, '') else None
                        except (ValueError, TypeError):
                            depth_val = None

                        gpx_content += f'      <trkpt lat="{lat}" lon="{lon}">\n'
                        gpx_content += f'        <ele>{elev}</ele>\n'
                        if depth_val is not None:
                            gpx_content += (
                                '        <extensions>\n'
                                f'          <depth>{depth_val}</depth>\n'
                                '        </extensions>\n'
                            )
                        gpx_content += '      </trkpt>\n'
                    except (ValueError, TypeError):
                        continue

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

        def parse_float(value: Optional[str]) -> Optional[float]:
            try:
                if value is None or value == '':
                    return None
                return float(value)
            except (ValueError, TypeError):
                return None

        # First pass: collect valid rows and compute centroid for a stable
        # local ENU origin. Using the first row as the origin makes the
        # projection sensitive to GPS warm-up outliers; the centroid keeps
        # all coordinates well-conditioned regardless of where the track
        # starts.
        valid_rows = []
        lat_sum = 0.0
        lon_sum = 0.0

        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                lat = parse_float(row.get('latitude'))
                lon = parse_float(row.get('longitude'))
                if lat is None or lon is None:
                    continue
                depth = parse_float(row.get('depth_m'))
                elevation = parse_float(row.get('elevation'))
                if depth is None and elevation is None:
                    continue
                valid_rows.append((lat, lon, depth, elevation, row))
                lat_sum += lat
                lon_sum += lon

        if not valid_rows:
            raise ValueError('No valid sonar point data found in CSV for 3D export')

        origin_lat = lat_sum / len(valid_rows)
        origin_lon = lon_sum / len(valid_rows)

        points = []
        for lat, lon, depth, elevation, row in valid_rows:
            x, y = MapGenerator._wgs84_to_local_xy(lat, lon, origin_lat, origin_lon)
            z = -depth if depth is not None else elevation

            points.append({
                'x': x,
                'y': y,
                'z': z,
                'intensity_avg': parse_float(row.get('sonar_intensity_avg')) or 0.0,
                'intensity_max': parse_float(row.get('sonar_intensity_max')) or 0.0,
                'water_temp_c': parse_float(row.get('water_temp_c')) or 0.0,
                'sonar_frequency_khz': parse_float(row.get('sonar_frequency_khz')) or 0.0,
                'beam_count': int(parse_float(row.get('beam_count')) or 0),
                'frame_number': int(parse_float(row.get('frame_number')) or 0),
            })

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
