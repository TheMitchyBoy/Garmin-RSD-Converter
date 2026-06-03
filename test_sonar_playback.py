#!/usr/bin/env python3
"""Tests for Garmin-style sonar playback rendering."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from sonar_playback import (
    load_playback_channel,
    palette_rgb,
    pick_playback_channel_id,
    render_live_frame,
    export_html_player,
    export_gif,
    _resize_nearest,
)


class TestSonarPlayback(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _mock_sonar(self):
        sonar = MagicMock()
        sonar.channel_info = [
            {'channel_id': 0, 'start_freq_hz': 150000, 'end_freq_hz': 250000},
            {'channel_id': 1, 'start_freq_hz': 455000, 'end_freq_hz': 800000},
        ]
        df = pd.DataFrame([
            {
                'lat': 40.7128, 'lon': -74.0060, 'inst_dep_m': 8.5, 'tempC': 18.2,
                'channel_id': 0, 'beam': 2, 'sequence_cnt': 100, 'index': 20480,
                'time_s': 1.0, 'min_range': 0.0, 'max_range': 20.0,
                'data_size': 100, 'sample_cnt': 4, 'son_offset': 512,
            },
            {
                'lat': 40.7128, 'lon': -74.0060, 'inst_dep_m': 8.5, 'tempC': 18.2,
                'channel_id': 1, 'beam': 1, 'sequence_cnt': 100, 'index': 20480,
                'time_s': 1.0, 'min_range': 0.0, 'max_range': 20.0,
                'data_size': 100, 'sample_cnt': 4, 'son_offset': 512,
            },
            {
                'lat': 40.7129, 'lon': -74.0059, 'inst_dep_m': 9.0, 'tempC': 18.3,
                'channel_id': 1, 'beam': 1, 'sequence_cnt': 101, 'index': 21000,
                'time_s': 2.0, 'min_range': 0.0, 'max_range': 20.0,
                'data_size': 100, 'sample_cnt': 4, 'son_offset': 512,
            },
        ])
        sonar.header_dat = df
        sonar.describe_channel.return_value = {'label': 'Traditional CHIRP 150-250 kHz'}
        sonar.extract_raw_sample_arrays.return_value = {
            1: [
                np.array([0, 100, 500, 1000], dtype=np.uint16),
                np.array([0, 120, 600, 1200], dtype=np.uint16),
            ],
        }
        sonar._scale_samples_for_waterfall.side_effect = lambda arr: np.clip(
            (np.log1p(arr.astype(np.float32)) * 20).astype(np.uint8), 0, 255,
        )
        sonar._garmin_waterfall_palette.return_value = list(range(256)) * 3
        return sonar

    def test_pick_playback_channel_prefers_down_beam(self):
        sonar = self._mock_sonar()
        self.assertEqual(pick_playback_channel_id(sonar), 1)

    def test_load_playback_channel(self):
        channel = load_playback_channel(self._mock_sonar())
        self.assertEqual(channel.channel_id, 1)
        self.assertEqual(channel.scaled.shape[0], 2)
        self.assertEqual(channel.scaled.shape[1], 4)
        self.assertEqual(len(channel.meta), 2)

    def test_render_live_frame_shape(self):
        sonar = self._mock_sonar()
        channel = load_playback_channel(sonar)
        pal = palette_rgb(sonar)
        frame = render_live_frame(channel, pal, ping_idx=1, window_pings=2, width=80, height=60)
        self.assertEqual(frame.shape, (60, 80, 3))
        self.assertEqual(frame.dtype, np.uint8)

    def test_resize_nearest(self):
        src = np.zeros((4, 6, 3), dtype=np.uint8)
        src[2, 3] = (255, 0, 0)
        out = _resize_nearest(src, 12, 8)
        self.assertEqual(out.shape, (8, 12, 3))

    def test_export_html_player(self):
        sonar = self._mock_sonar()
        channel = load_playback_channel(sonar)
        pal = palette_rgb(sonar)
        out = self.temp_path / 'playback.html'
        export_html_player(channel, pal, out, window_pings=2, width=120, height=80)
        text = out.read_text(encoding='utf-8')
        self.assertIn('Garmin Sonar Playback', text)
        self.assertIn('Traditional CHIRP', text)

    def test_export_gif(self):
        sonar = self._mock_sonar()
        channel = load_playback_channel(sonar)
        pal = palette_rgb(sonar)
        frames = [
            render_live_frame(channel, pal, 0, 2, 40, 30, hud=False),
            render_live_frame(channel, pal, 1, 2, 40, 30, hud=False),
        ]
        out = self.temp_path / 'playback.gif'
        export_gif(iter(frames), out, fps=5)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 100)


if __name__ == '__main__':
    unittest.main()
