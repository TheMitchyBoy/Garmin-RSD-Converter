#!/usr/bin/env python3
"""
Unit tests for sonar export utilities.
"""

import unittest
import tempfile
import json
from pathlib import Path
from analysis_tools import MapGenerator
from fish_detection import FishDetector
from heatmap_generator import HeatmapGenerator
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer


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

    def test_fish_health_and_dashboard_exports(self):
        csv_file = self._write_full_sonar_csv()

        detections_file, detections = FishDetector.detect_fish(csv_file)
        self.assertTrue(detections_file.exists())
        self.assertGreaterEqual(len(detections), 1)

        metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
        self.assertIn('health_indicators', metrics)

        dashboard_file = WebVisualizer.create_dashboard(
            detections_file,
            metrics,
            location_name='Test Lake',
            output_file=self.temp_path / 'dashboard.html',
        )
        self.assertTrue(dashboard_file.exists())
        self.assertIn('Sonar Analysis Dashboard', dashboard_file.read_text(encoding='utf-8'))

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


if __name__ == '__main__':
    unittest.main()
