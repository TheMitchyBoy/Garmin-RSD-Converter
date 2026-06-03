#!/usr/bin/env python3
"""Tests for RSD batch discovery and helpers."""

import tempfile
import unittest
from pathlib import Path

from batch_processor import (
    discover_rsd_files,
    format_batch_summary,
    is_csv_file,
    is_rsd_file,
    merge_batch_summaries,
    BatchSummary,
    FileJobResult,
)


class TestBatchDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_is_rsd_file(self):
        rsd = self.root / 'Sonar000.RSD'
        rsd.write_bytes(b'\x00')
        self.assertTrue(is_rsd_file(rsd))
        self.assertFalse(is_rsd_file(self.root / 'notes.txt'))

    def test_is_csv_file(self):
        csv_file = self.root / 'survey.csv'
        csv_file.write_text('latitude,longitude,depth_m\n', encoding='utf-8')
        self.assertTrue(is_csv_file(csv_file))
        self.assertFalse(is_csv_file(self.root / 'notes.txt'))

    def test_merge_batch_summaries(self):
        first = BatchSummary(results=[
            FileJobResult(input_path=Path('a.csv'), success=True, message='ok'),
        ])
        second = BatchSummary(results=[
            FileJobResult(input_path=Path('b.RSD'), success=False, message='fail'),
        ])
        merged = merge_batch_summaries(first, second)
        self.assertEqual(merged.total, 2)
        self.assertEqual(merged.succeeded, 1)

    def test_discover_from_directory_recursive(self):
        nested = self.root / 'trips' / 'june'
        nested.mkdir(parents=True)
        (nested / 'a.RSD').write_bytes(b'\x00')
        (nested / 'b.rsd').write_bytes(b'\x00')
        (nested / 'readme.txt').write_text('x', encoding='utf-8')

        found = discover_rsd_files([self.root / 'trips'], recursive=True)
        self.assertEqual(len(found), 2)

    def test_discover_non_recursive(self):
        nested = self.root / 'flat'
        nested.mkdir()
        sub = nested / 'deep'
        sub.mkdir()
        (nested / 'top.RSD').write_bytes(b'\x00')
        (sub / 'deep.RSD').write_bytes(b'\x00')

        found = discover_rsd_files([nested], recursive=False)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, 'top.RSD')

    def test_discover_explicit_files(self):
        one = self.root / 'One.RSD'
        two = self.root / 'Two.rsd'
        one.write_bytes(b'\x00')
        two.write_bytes(b'\x00')
        found = discover_rsd_files([one, two])
        self.assertEqual([p.name for p in found], ['One.RSD', 'Two.rsd'])

    def test_format_batch_summary(self):
        summary = BatchSummary(results=[
            FileJobResult(
                input_path=Path('Sonar000.RSD'),
                success=True,
                message='ok',
                csv_path=Path('Sonar000.csv'),
            ),
        ])
        text = format_batch_summary(summary)
        self.assertIn('Succeeded: 1', text)
        self.assertIn('Sonar000.RSD', text)


if __name__ == '__main__':
    unittest.main()
