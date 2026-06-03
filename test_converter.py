#!/usr/bin/env python3
"""
Unit tests for sonar export utilities.
"""

import unittest
import tempfile
import json
import struct
from pathlib import Path
from unittest.mock import patch
from analysis_tools import MapGenerator
from fish_detection import FishDetector
from heatmap_generator import HeatmapGenerator
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer
from map_visuals import bathymetry_color, grid_cell_polygon
from geo_utils import decode_garmin_coordinate_pair
from sonar_converter import SonarRSDParser
from pingverter_adapter import validate_rsd_file
from survey_tools import merge_csv_files, compare_surveys, compute_track_quality
from geotiff_export import GeoTiffWriter
from las_export import LasExporter


class TestMapGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ply_export(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,sonar_intensity_avg,sonar_intensity_max,water_temp_c,sonar_frequency_khz,beam_count,frame_number\n')
            f.write('40.7128,-74.0060,5.0,100.0,150.0,18.2,200.0,32,1\n')
            f.write('40.7129,-74.0059,6.5,110.0,155.0,18.3,200.0,32,2\n')

        ply_file = MapGenerator.create_ply(csv_file)
        self.assertTrue(ply_file.exists())
        with open(ply_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertTrue(content.startswith('ply'))
        self.assertIn('element vertex 2', content)
        self.assertIn('property float x', content)
        self.assertIn('property float z', content)

    def test_geojson_export(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m\n')
            f.write('40.7128,-74.0060,5.0\n')
            f.write('40.7129,-74.0059,6.5\n')

        geojson_file = MapGenerator.create_geojson(csv_file)
        self.assertTrue(geojson_file.exists())
        with open(geojson_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('FeatureCollection', content)
        self.assertIn('Point', content)

    def test_kml_and_gpx_exports(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m\n')
            f.write('40.7128,-74.0060,5.0\n')
            f.write('40.7129,-74.0059,6.5\n')

        kml_file = MapGenerator.create_kml(csv_file)
        gpx_file = MapGenerator.create_gpx(csv_file)

        self.assertTrue(kml_file.exists())
        self.assertTrue(gpx_file.exists())
        self.assertIn('<kml', kml_file.read_text(encoding='utf-8'))
        self.assertIn('<gpx', gpx_file.read_text(encoding='utf-8'))

    def test_heatmap_exports(self):
        csv_file = self._write_full_sonar_csv()

        intensity_file = HeatmapGenerator.create_intensity_heatmap(csv_file)
        depth_file = HeatmapGenerator.create_depth_heatmap(csv_file)
        temperature_file = HeatmapGenerator.create_temperature_heatmap(csv_file)

        for output_file in (intensity_file, depth_file, temperature_file):
            self.assertTrue(output_file.exists())
            data = json.loads(output_file.read_text(encoding='utf-8'))
            self.assertEqual(data['type'], 'FeatureCollection')
            self.assertGreaterEqual(len(data['features']), 1)

        depth_data = json.loads(depth_file.read_text(encoding='utf-8'))
        self.assertEqual(depth_data['properties']['heatmap_type'], 'bathymetry')
        depth_feature = depth_data['features'][0]
        self.assertEqual(depth_feature['geometry']['type'], 'Polygon')
        self.assertIn('layer', depth_feature['properties'])
        self.assertEqual(depth_feature['properties']['layer'], 'seabed')
        self.assertRegex(depth_feature['properties']['color'], r'^#[0-9a-f]{6}$')

    def test_bathymetry_color_ramp(self):
        shallow = bathymetry_color(2.0, 2.0, 20.0)
        deep = bathymetry_color(20.0, 2.0, 20.0)
        self.assertNotEqual(shallow, deep)
        self.assertTrue(shallow.startswith('#'))
        self.assertTrue(deep.startswith('#'))

    def test_grid_cell_polygon_closed(self):
        ring = grid_cell_polygon(0.0, 0.0, 0.01)
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 5)

    def test_fish_health_and_dashboard_exports(self):
        csv_file = self._write_full_sonar_csv()

        detections_file, detections = FishDetector.detect_fish(csv_file)
        self.assertTrue(detections_file.exists())
        self.assertGreaterEqual(len(detections), 1)

        metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
        self.assertIn('health_indicators', metrics)

        depth_file = HeatmapGenerator.create_depth_heatmap(csv_file)
        dashboard_file = WebVisualizer.create_dashboard(
            detections_file,
            metrics,
            location_name='Test Lake',
            output_file=self.temp_path / 'dashboard.html',
            depth_geojson_file=depth_file,
        )
        content = dashboard_file.read_text(encoding='utf-8')
        self.assertTrue(dashboard_file.exists())
        self.assertIn('Sonar Survey Dashboard', content)
        self.assertIn('leaflet', content)
        self.assertIn('Seabed depth', content)
        self.assertIn('Fish detections', content)
        self.assertIn('layers.seabed', content)

    def test_decode_garmin_coordinate_pair_handles_alaska_ranges(self):
        lat_raw = int(61.2181 * 10_000_000)
        lon_raw = int(-149.9003 * 10_000_000)
        lat, lon = decode_garmin_coordinate_pair(lat_raw, lon_raw)
        self.assertIsNotNone(lat)
        self.assertIsNotNone(lon)
        self.assertAlmostEqual(lat, 61.2181, places=4)
        self.assertAlmostEqual(lon, -149.9003, places=4)

    def test_non_streaming_parser_extracts_full_scale_coordinates(self):
        parser = SonarRSDParser()
        data = bytearray(256)
        data[4:8] = struct.pack('<i', int(61.2181 * 10_000_000))
        data[8:12] = struct.pack('<i', int(-149.9003 * 10_000_000))
        data[32:34] = struct.pack('<H', 200)

        frame = parser._extract_sonar_data(bytes(data), 0)
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(frame.latitude, 61.2181, places=4)
        self.assertAlmostEqual(frame.longitude, -149.9003, places=4)

    def test_empty_heatmaps_do_not_crash(self):
        csv_file = self.temp_path / 'empty.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,sonar_intensity_avg,water_temp_c\n')

        for output_file in (
            HeatmapGenerator.create_intensity_heatmap(csv_file),
            HeatmapGenerator.create_depth_heatmap(csv_file),
            HeatmapGenerator.create_temperature_heatmap(csv_file),
        ):
            data = json.loads(output_file.read_text(encoding='utf-8'))
            self.assertEqual(data['features'], [])

    def _write_full_sonar_csv(self):
        csv_file = self.temp_path / 'sonar_full.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,sonar_intensity_avg,sonar_intensity_max,water_temp_c,sonar_frequency_khz,beam_count,frame_number\n')
            f.write('40.7128,-74.0060,8.0,85.0,110.0,18.2,200.0,32,1\n')
            f.write('40.7129,-74.0059,12.5,125.0,160.0,18.3,200.0,32,2\n')
            f.write('40.7130,-74.0058,0.0,5.0,8.0,18.4,200.0,32,3\n')
        return csv_file

    def test_depth_contours_export(self):
        csv_file = self._write_full_sonar_csv()
        contour_file = HeatmapGenerator.create_depth_contours(csv_file, interval_m=2.0)
        self.assertTrue(contour_file.exists())
        data = json.loads(contour_file.read_text(encoding='utf-8'))
        self.assertEqual(data['type'], 'FeatureCollection')
        self.assertIn('contour_interval_m', data['properties'])

    def test_fish_schools_and_aggregate_exports(self):
        csv_file = self._write_full_sonar_csv()
        _, detections = FishDetector.detect_fish(csv_file)
        schools_file = FishDetector.export_fish_schools_geojson(
            detections, self.temp_path / 'schools.geojson',
        )
        agg_file = FishDetector.export_fish_aggregate_geojson(
            detections, self.temp_path / 'aggregate.geojson',
        )
        self.assertTrue(schools_file.exists())
        self.assertTrue(agg_file.exists())
        schools_data = json.loads(schools_file.read_text(encoding='utf-8'))
        agg_data = json.loads(agg_file.read_text(encoding='utf-8'))
        self.assertEqual(schools_data['type'], 'FeatureCollection')
        self.assertEqual(agg_data['type'], 'FeatureCollection')

    def test_merge_and_compare_surveys(self):
        csv_a = self.temp_path / 'a.csv'
        csv_b = self.temp_path / 'b.csv'
        with open(csv_a, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,sonar_intensity_avg,frame_number\n')
            f.write('40.7100,-74.0100,5.0,80.0,1\n')
            f.write('40.7110,-74.0090,6.0,90.0,2\n')
        with open(csv_b, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,sonar_intensity_avg,frame_number\n')
            f.write('40.7100,-74.0100,7.0,85.0,1\n')

        merged = merge_csv_files([csv_a, csv_b], self.temp_path / 'merged.csv')
        self.assertTrue(merged.exists())
        merged_lines = merged.read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(len(merged_lines), 4)  # header + 3 rows

        diff = compare_surveys(csv_a, csv_b, grid_size=0.01)
        diff_data = json.loads(diff.read_text(encoding='utf-8'))
        self.assertEqual(diff_data['type'], 'FeatureCollection')

    def test_track_quality_score(self):
        csv_file = self._write_full_sonar_csv()
        quality = compute_track_quality(csv_file)
        self.assertIn('overall_score', quality)
        self.assertIn('grade', quality)
        self.assertGreater(quality['total_frames'], 0)

    @patch('pingverter_adapter.parse_rsd_with_pingverter')
    def test_rsd_validation(self, mock_parse):
        import pandas as pd
        from unittest.mock import MagicMock

        sonar = MagicMock()
        sonar.channel_info = [{'channel_id': 0, 'start_freq_hz': 150000, 'end_freq_hz': 250000}]
        sonar.header_dat = pd.DataFrame([
            {'lat': 40.7, 'lon': -74.0, 'inst_dep_m': 5.0, 'tempC': 18.0, 'channel_id': 0, 'ping_cnt': 100},
        ])
        mock_parse.return_value = sonar

        rsd_file = self.temp_path / 'test.rsd'
        rsd_file.write_bytes(b'RSD')
        report = validate_rsd_file(rsd_file)
        self.assertIn('overall_score', report)
        self.assertEqual(report['parser'], 'PINGVerter')

    def test_geotiff_and_las_exports(self):
        csv_file = self._write_full_sonar_csv()
        tif_file = GeoTiffWriter.create_depth_geotiff(csv_file, grid_size=0.01)
        las_file = LasExporter.create_las(csv_file)

        self.assertTrue(tif_file.exists())
        self.assertTrue(las_file.exists())
        self.assertEqual(tif_file.read_bytes()[:2], b'II')
        self.assertEqual(las_file.read_bytes()[:4], b'LASF')


if __name__ == '__main__':
    unittest.main()
