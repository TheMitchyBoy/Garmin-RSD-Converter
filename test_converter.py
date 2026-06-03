#!/usr/bin/env python3
"""
Expanded unit and integration tests for the Garmin Sonar RSD Converter.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from analysis_tools import MapGenerator
from fish_detection import FishDetector
from fixtures.generate_sample_rsd import generate_sample_rsd
from heatmap_generator import HeatmapGenerator
from population_health import PopulationHealthAnalytics
from sonar_converter_streaming import convert_sonar_rsd_to_csv
from sonar_schema import (
    CSV_COLUMNS,
    StreamingNumericStats,
    parse_sonar_row,
)
from web_visualizer import WebVisualizer

REPO_ROOT = Path(__file__).resolve().parent


class TestSonarSchema(unittest.TestCase):
    def test_parse_sonar_row_rejects_invalid_gps(self):
        self.assertIsNone(parse_sonar_row({'latitude': '0', 'longitude': '0'}))

    def test_parse_sonar_row_reads_intensity_count_as_beam_count(self):
        row = {
            'latitude': '40.7128',
            'longitude': '-74.0060',
            'depth_m': '5.0',
            'sonar_intensity_count': '16',
        }
        reading = parse_sonar_row(row)
        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.beam_count, 16)

    def test_streaming_stats_median(self):
        stats = StreamingNumericStats(reservoir_size=100, seed=1)
        for value in range(1, 101):
            stats.add(float(value))
        self.assertEqual(stats.count, 100)
        self.assertAlmostEqual(stats.mean, 50.5)
        self.assertEqual(stats.median(), 50.5)


class TestMapGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ply_export_uses_intensity_count(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as handle:
            handle.write(','.join(CSV_COLUMNS) + '\n')
            handle.write('1,0,40.7128,-74.0060,5.0,18.2,200.0,100.0,150.0,16\n')

        ply_file = MapGenerator.create_ply(csv_file)
        content = ply_file.read_text(encoding='utf-8')
        self.assertIn('element vertex 1', content)
        self.assertIn(' 16 1\n', content)

    def test_kml_and_gpx_use_depth_as_elevation(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as handle:
            handle.write('latitude,longitude,depth_m\n')
            handle.write('40.7128,-74.0060,5.0\n')

        kml = MapGenerator.create_kml(csv_file).read_text(encoding='utf-8')
        gpx = MapGenerator.create_gpx(csv_file).read_text(encoding='utf-8')
        self.assertIn('-74.006,40.7128,-5.0', kml)
        self.assertIn('<ele>-5.0</ele>', gpx)

    def test_geojson_export(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as handle:
            handle.write('latitude,longitude,depth_m\n')
            handle.write('40.7128,-74.0060,5.0\n')

        geojson_file = MapGenerator.create_geojson(csv_file)
        data = json.loads(geojson_file.read_text(encoding='utf-8'))
        self.assertEqual(data['type'], 'FeatureCollection')
        self.assertGreaterEqual(len(data['features']), 1)


class TestHeatmapGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_depth_heatmap_includes_zero_depth(self):
        csv_file = self.temp_path / 'sonar.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as handle:
            handle.write('latitude,longitude,depth_m,sonar_intensity_avg,water_temp_c\n')
            handle.write('40.7128,-74.0060,0.0,50.0,18.0\n')

        output = HeatmapGenerator.create_depth_heatmap(csv_file)
        data = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(len(data['features']), 1)
        self.assertEqual(data['features'][0]['properties']['depth_m'], 0.0)

    def test_empty_heatmaps_do_not_crash(self):
        csv_file = self.temp_path / 'empty.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as handle:
            handle.write('latitude,longitude,depth_m,sonar_intensity_avg,water_temp_c\n')

        for creator in (
            HeatmapGenerator.create_intensity_heatmap,
            HeatmapGenerator.create_depth_heatmap,
            HeatmapGenerator.create_temperature_heatmap,
        ):
            data = json.loads(creator(csv_file).read_text(encoding='utf-8'))
            self.assertEqual(data['features'], [])


class TestRsdParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_synthetic_rsd_round_trip(self):
        rsd_file = generate_sample_rsd(self.temp_path / 'sample.rsd', frame_count=4)
        csv_file, frame_count = convert_sonar_rsd_to_csv(rsd_file, stride=256)

        self.assertGreater(frame_count, 0)
        lines = csv_file.read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(lines[0], ','.join(CSV_COLUMNS))
        self.assertIn('40.7128', lines[1])


class TestPipelineExports(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_full_sonar_csv(self):
        csv_file = self.temp_path / 'sonar_full.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as handle:
            handle.write(','.join(CSV_COLUMNS) + '\n')
            handle.write('1,0,40.7128,-74.0060,8.0,18.2,50.0,85.0,110.0,16\n')
            handle.write('2,256,40.7129,-74.0059,12.5,18.3,50.0,125.0,160.0,16\n')
        return csv_file

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
        content = dashboard_file.read_text(encoding='utf-8')
        self.assertIn('Sonar Analysis Dashboard', content)
        self.assertIn('leaflet', content.lower())
        self.assertIn('heuristic', content.lower())


class TestCli(unittest.TestCase):
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / 'sonar_cli.py'), '--help'],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('convert', result.stdout)

    def test_analyze_on_sample_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / 'sample.csv'
            rsd_file = generate_sample_rsd(Path(temp_dir) / 'sample.rsd', frame_count=3)
            convert_sonar_rsd_to_csv(rsd_file, csv_file)

            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / 'sonar_cli.py'), 'analyze', str(csv_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn('Sonar Survey Analysis', result.stdout)


if __name__ == '__main__':
    unittest.main()
