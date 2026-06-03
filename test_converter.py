#!/usr/bin/env python3
"""
Unit tests for sonar export utilities.
"""

import unittest
import tempfile
from pathlib import Path
from analysis_tools import MapGenerator


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


if __name__ == '__main__':
    unittest.main()
