#!/usr/bin/env python3
"""
Unit tests for sonar export utilities.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from analysis_tools import MapGenerator
from fish_detection import FishDetector
from heatmap_generator import HeatmapGenerator
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer

import sonar_cli


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

    def test_kml_gpx_carry_depth(self):
        csv_file = self.temp_path / 'depth_track.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m\n')
            f.write('40.7128,-74.0060,5.0\n')
            f.write('40.7129,-74.0059,12.5\n')

        kml_file = MapGenerator.create_kml(csv_file)
        gpx_file = MapGenerator.create_gpx(csv_file)

        kml_text = kml_file.read_text(encoding='utf-8')
        gpx_text = gpx_file.read_text(encoding='utf-8')

        # KML coordinates should use -depth_m as elevation, not a constant 0.
        self.assertIn('-74.006,40.7128,-5.0', kml_text)
        self.assertIn('-74.0059,40.7129,-12.5', kml_text)
        self.assertIn('<altitudeMode>absolute</altitudeMode>', kml_text)

        # GPX should carry depth in extensions and use -depth as elevation.
        self.assertIn('<ele>-5.0</ele>', gpx_text)
        self.assertIn('<depth>5.0</depth>', gpx_text)
        self.assertIn('<depth>12.5</depth>', gpx_text)

    def test_ply_origin_uses_centroid(self):
        csv_file = self.temp_path / 'centroid.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m\n')
            f.write('40.0000,-74.0000,5.0\n')
            f.write('40.0002,-74.0002,5.0\n')

        ply_file = MapGenerator.create_ply(csv_file)
        lines = ply_file.read_text(encoding='utf-8').splitlines()
        vertex_lines = lines[lines.index('end_header') + 1:]

        xs = []
        ys = []
        for line in vertex_lines:
            parts = line.split()
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))

        # If the centroid was used as the origin the projected coordinates
        # should be symmetric (sum ≈ 0); using the first row as origin would
        # leave the second point with both positive x and y.
        self.assertAlmostEqual(sum(xs), 0.0, delta=0.5)
        self.assertAlmostEqual(sum(ys), 0.0, delta=0.5)

    def _write_full_sonar_csv(self):
        csv_file = self.temp_path / 'sonar_full.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,sonar_intensity_avg,sonar_intensity_max,water_temp_c,sonar_frequency_khz,beam_count,frame_number\n')
            f.write('40.7128,-74.0060,8.0,85.0,110.0,18.2,200.0,32,1\n')
            f.write('40.7129,-74.0059,12.5,125.0,160.0,18.3,200.0,32,2\n')
            f.write('40.7130,-74.0058,0.0,5.0,8.0,18.4,200.0,32,3\n')
        return csv_file


class TestSonarCli(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.cwd = os.getcwd()
        os.chdir(self.temp_path)

    def tearDown(self):
        os.chdir(self.cwd)
        self.temp_dir.cleanup()

    def _write_sample_csv(self) -> Path:
        csv_file = self.temp_path / 'sample.csv'
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write('latitude,longitude,depth_m,water_temp_c,sonar_frequency_khz,sonar_intensity_avg,sonar_intensity_max\n')
            f.write('40.0,-74.0,5.0,18.2,200.0,80.0,110.0\n')
            f.write('40.1,-74.1,12.5,18.3,200.0,120.0,160.0\n')
        return csv_file

    def _run_cli(self, argv):
        with mock.patch.object(sys, 'argv', ['sonar_cli.py'] + argv):
            return sonar_cli.main()

    def test_convert_missing_input_returns_error(self):
        with redirect_stdout(io.StringIO()):
            rc = self._run_cli(['convert', 'does-not-exist.RSD'])
        self.assertEqual(rc, 1)

    def test_convert_rejects_invalid_stride(self):
        rsd = self.temp_path / 'fake.RSD'
        rsd.write_bytes(b'\x00' * 1024)
        with redirect_stdout(io.StringIO()):
            rc = self._run_cli(['convert', str(rsd), '--stride', '0'])
        self.assertEqual(rc, 1)

    def test_fish_detect_rejects_inverted_intensity(self):
        csv_file = self._write_sample_csv()
        with redirect_stdout(io.StringIO()):
            rc = self._run_cli([
                'fish', 'detect', str(csv_file),
                '--min-intensity', '150', '--max-intensity', '50',
            ])
        self.assertEqual(rc, 1)

    def test_heatmap_rejects_non_positive_grid_size(self):
        csv_file = self._write_sample_csv()
        with redirect_stdout(io.StringIO()):
            rc = self._run_cli([
                'heatmap', str(csv_file), '--intensity', '--grid-size', '0',
            ])
        self.assertEqual(rc, 1)

    def test_analyze_json_to_stdout(self):
        csv_file = self._write_sample_csv()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = self._run_cli(['analyze', str(csv_file), '--json'])
        self.assertEqual(rc, 0)
        # CLI prints log lines via stderr; JSON document is the only thing
        # written to stdout in this mode.
        text = buffer.getvalue()
        payload = json.loads(text[text.index('{'):])
        self.assertEqual(payload['total_frames'], 2)
        self.assertEqual(payload['depth_m']['count'], 2)
        self.assertAlmostEqual(payload['depth_m']['avg'], 8.75)

    def test_analyze_json_to_file(self):
        csv_file = self._write_sample_csv()
        out_file = self.temp_path / 'summary.json'
        with redirect_stdout(io.StringIO()):
            rc = self._run_cli(['analyze', str(csv_file), '--json', str(out_file)])
        self.assertEqual(rc, 0)
        payload = json.loads(out_file.read_text(encoding='utf-8'))
        self.assertEqual(payload['total_frames'], 2)


if __name__ == '__main__':
    unittest.main()
