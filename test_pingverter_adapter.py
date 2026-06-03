#!/usr/bin/env python3
"""Tests for PINGVerter-based RSD conversion adapter."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from pingverter_adapter import (
    write_pingverter_csv,
    validate_rsd_file,
    _select_track_rows,
    PROJECT_CSV_FIELDS,
)


class TestPingverterAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _mock_sonar(self):
        sonar = MagicMock()
        sonar.channel_info = [
            {'channel_id': 0, 'start_freq_hz': 150000, 'end_freq_hz': 250000},
        ]
        df = pd.DataFrame([
            {
                'lat': 40.7128,
                'lon': -74.0060,
                'inst_dep_m': 8.5,
                'tempC': 18.2,
                'channel_id': 0,
                'beam': 1,
                'sequence_cnt': 100,
                'index': 20480,
                'time_s': 1.0,
            },
            {
                'lat': 40.7129,
                'lon': -74.0059,
                'inst_dep_m': 9.0,
                'tempC': 18.3,
                'channel_id': 0,
                'beam': 1,
                'sequence_cnt': 101,
                'index': 21000,
                'time_s': 2.0,
            },
        ])
        sonar.header_dat = df
        sonar.extract_raw_sample_arrays.return_value = {
            0: [np.array([100, 120, 140], dtype=np.uint16), np.array([90, 110], dtype=np.uint16)],
        }
        return sonar

    def test_write_pingverter_csv(self):
        output = self.temp_path / 'out.csv'
        count = write_pingverter_csv(self._mock_sonar(), output)
        self.assertEqual(count, 2)
        text = output.read_text(encoding='utf-8')
        self.assertIn('latitude', text)
        self.assertIn('40.7128', text)
        self.assertIn('sonar_intensity_avg', text)

    def test_select_track_rows_prefers_down_beam(self):
        df = pd.DataFrame([
            {'sequence_cnt': 1, 'beam': 2, 'lat': 1.0, 'lon': 1.0},
            {'sequence_cnt': 1, 'beam': 1, 'lat': 2.0, 'lon': 2.0},
        ])
        selected = _select_track_rows(df)
        self.assertEqual(len(selected), 1)
        self.assertEqual(int(selected.iloc[0]['beam']), 1)

    @patch('pingverter_adapter.parse_rsd_with_pingverter')
    def test_validate_rsd_file(self, mock_parse):
        sonar = self._mock_sonar()
        mock_parse.return_value = sonar
        rsd_file = self.temp_path / 'fake.rsd'
        rsd_file.write_bytes(b'RSD')
        report = validate_rsd_file(rsd_file)
        self.assertEqual(report['parser'], 'PINGVerter')
        self.assertIn('overall_score', report)
        self.assertGreaterEqual(report['gps_pct'], 0)


if __name__ == '__main__':
    unittest.main()
