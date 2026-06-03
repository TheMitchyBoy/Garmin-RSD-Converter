#!/usr/bin/env python3
"""Tests for the hostable sonar web application."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sonar_web_app import (
    WebAppConfig,
    _app_html,
    _collect_output_links,
    _safe_session_path,
    resolve_port,
)


class TestSonarWebApp(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config = WebAppConfig(data_dir=self.root / 'data')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_app_html_includes_playback_tab(self):
        html = _app_html()
        self.assertIn('Watch sonar feed', html)
        self.assertIn('/api/playback', html)

    def test_resolve_port_prefers_railway_port(self):
        import os
        with patch.dict(os.environ, {'PORT': '3000', 'SONAR_PORT': '8080'}, clear=False):
            self.assertEqual(resolve_port(), 3000)
        self.assertEqual(resolve_port(9000), 9000)

    def test_safe_session_path_blocks_traversal(self):
        session_id = 'abc123'
        session_dir = self.config.sessions_root / session_id
        session_dir.mkdir(parents=True)
        safe_file = session_dir / 'playback.html'
        safe_file.write_text('<html></html>', encoding='utf-8')

        resolved = _safe_session_path(self.config.sessions_root, session_id, 'playback.html')
        self.assertEqual(resolved, safe_file.resolve())

        blocked = _safe_session_path(self.config.sessions_root, session_id, '../secret.txt')
        self.assertIsNone(blocked)

        blocked_id = _safe_session_path(self.config.sessions_root, '../bad', 'playback.html')
        self.assertIsNone(blocked_id)

    def test_collect_output_links(self):
        session_id = 'sess1'
        session_dir = self.root / 'sess1'
        session_dir.mkdir()
        csv_file = session_dir / 'Sonar000.csv'
        csv_file.write_text('a,b\n', encoding='utf-8')
        links = _collect_output_links(session_id, session_dir, [csv_file])
        self.assertEqual(len(links), 1)
        self.assertIn('/files/sess1/', links[0]['url'])
        self.assertEqual(links[0]['label'], 'Download CSV')


if __name__ == '__main__':
    unittest.main()
