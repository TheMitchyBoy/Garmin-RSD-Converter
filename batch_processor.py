#!/usr/bin/env python3
"""
Discover Garmin Sonar RSD files and run bulk convert / pipeline workflows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

from sonar_converter_streaming import convert_sonar_rsd_to_csv
from analysis_tools import MapGenerator
from heatmap_generator import HeatmapGenerator
from fish_detection import FishDetector
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer

logger = logging.getLogger(__name__)

RSD_SUFFIXES = {'.rsd', '.RSD'}


@dataclass
class FileJobResult:
    """Outcome for a single RSD file in a batch run."""

    input_path: Path
    success: bool
    message: str = ''
    csv_path: Optional[Path] = None
    frame_count: int = 0
    outputs: List[Path] = field(default_factory=list)


@dataclass
class BatchSummary:
    """Aggregate results for a batch run."""

    results: List[FileJobResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded


def is_rsd_file(path: Path) -> bool:
    return path.is_file() and path.suffix in RSD_SUFFIXES


def discover_rsd_files(
    sources: Sequence[Union[str, Path]],
    *,
    recursive: bool = True,
) -> List[Path]:
    """
    Collect RSD files from explicit paths, directories, or glob patterns.

    Args:
        sources: File paths, directories, or glob patterns (e.g. ``*.RSD``).
        recursive: When a source is a directory, search subdirectories too.

    Returns:
        De-duplicated list of RSD paths sorted by name.
    """
    found: dict[str, Path] = {}

    for raw in sources:
        path = Path(raw).expanduser()
        if any(ch in str(raw) for ch in '*?[]'):
            for match in Path().glob(str(raw)):
                if is_rsd_file(match):
                    found[str(match.resolve())] = match.resolve()
            continue

        if not path.exists():
            logger.warning('Skipping missing path: %s', path)
            continue

        if path.is_file():
            if is_rsd_file(path):
                found[str(path.resolve())] = path.resolve()
            else:
                logger.warning('Not an RSD file: %s', path)
            continue

        if path.is_dir():
            iterator: Iterable[Path] = path.rglob('*') if recursive else path.glob('*')
            for candidate in iterator:
                if is_rsd_file(candidate):
                    found[str(candidate.resolve())] = candidate.resolve()

    return sorted(found.values(), key=lambda p: p.name.lower())


def _resolve_output_csv(input_file: Path, output_dir: Optional[Path]) -> Path:
    if output_dir is None:
        return input_file.with_suffix('.csv')
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f'{input_file.stem}.csv'


def _location_label(input_file: Path, location: Optional[str]) -> str:
    if location:
        return location
    return input_file.stem.replace('_', ' ').replace('-', ' ')


def batch_convert(
    sources: Sequence[Union[str, Path]],
    *,
    output_dir: Optional[Union[str, Path]] = None,
    stride: int = 256,
    map_formats: Optional[Sequence[str]] = None,
    recursive: bool = True,
    continue_on_error: bool = True,
) -> BatchSummary:
    """Convert multiple RSD files to CSV, optionally generating map exports."""
    files = discover_rsd_files(sources, recursive=recursive)
    summary = BatchSummary()

    if not files:
        logger.warning('No RSD files found in: %s', list(sources))
        return summary

    out_root = Path(output_dir).expanduser() if output_dir else None
    formats: List[str] = []
    if map_formats:
        formats = ['ply', 'geojson', 'kml', 'gpx'] if 'all' in map_formats else list(map_formats)

    for input_file in files:
        result = FileJobResult(input_path=input_file, success=False)
        try:
            csv_path = _resolve_output_csv(input_file, out_root)
            csv_file, frame_count = convert_sonar_rsd_to_csv(
                input_file, csv_path, stride=stride,
            )
            result.csv_path = csv_file
            result.frame_count = frame_count
            result.outputs.append(csv_file)

            for fmt in formats:
                if fmt == 'ply':
                    result.outputs.append(MapGenerator.create_ply(csv_file))
                elif fmt == 'geojson':
                    result.outputs.append(MapGenerator.create_geojson(csv_file))
                elif fmt == 'kml':
                    result.outputs.append(MapGenerator.create_kml(csv_file))
                elif fmt == 'gpx':
                    result.outputs.append(MapGenerator.create_gpx(csv_file))

            result.success = True
            result.message = f'Converted {frame_count:,} frames'
        except Exception as exc:
            result.message = str(exc)
            logger.error('Failed to convert %s: %s', input_file, exc)
            if not continue_on_error:
                summary.results.append(result)
                raise
        summary.results.append(result)

    return summary


def batch_pipeline(
    sources: Sequence[Union[str, Path]],
    *,
    output_dir: Optional[Union[str, Path]] = None,
    stride: int = 256,
    location: Optional[str] = None,
    recursive: bool = True,
    continue_on_error: bool = True,
) -> BatchSummary:
    """Run the full analysis pipeline on each RSD file."""
    files = discover_rsd_files(sources, recursive=recursive)
    summary = BatchSummary()

    if not files:
        logger.warning('No RSD files found in: %s', list(sources))
        return summary

    out_root = Path(output_dir).expanduser() if output_dir else None

    for input_file in files:
        result = FileJobResult(input_path=input_file, success=False)
        label = _location_label(input_file, location)
        try:
            csv_path = _resolve_output_csv(input_file, out_root)
            csv_file, frame_count = convert_sonar_rsd_to_csv(
                input_file, csv_path, stride=stride,
            )
            result.csv_path = csv_file
            result.frame_count = frame_count
            result.outputs.append(csv_file)

            for path in (
                MapGenerator.create_ply(csv_file),
                MapGenerator.create_geojson(csv_file),
                MapGenerator.create_kml(csv_file),
                MapGenerator.create_gpx(csv_file),
            ):
                result.outputs.append(path)

            intensity_hm = HeatmapGenerator.create_intensity_heatmap(csv_file)
            depth_hm = HeatmapGenerator.create_depth_heatmap(csv_file, grid_size=0.01)
            temperature_hm = HeatmapGenerator.create_temperature_heatmap(
                csv_file, grid_size=0.01,
            )
            result.outputs.extend([intensity_hm, depth_hm, temperature_hm])

            detections_file, detections = FishDetector.detect_fish(csv_file)
            result.outputs.append(detections_file)

            metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
            report_file = PopulationHealthAnalytics.generate_public_report(
                metrics, location_name=label,
            )
            dashboard_file = WebVisualizer.create_dashboard(
                detections_file,
                metrics,
                location_name=label,
                depth_geojson_file=depth_hm,
            )
            result.outputs.extend([report_file, dashboard_file])

            result.success = True
            result.message = (
                f'Pipeline complete: {frame_count:,} frames, '
                f'{len(detections):,} fish detections'
            )
        except Exception as exc:
            result.message = str(exc)
            logger.error('Pipeline failed for %s: %s', input_file, exc)
            if not continue_on_error:
                summary.results.append(result)
                raise
        summary.results.append(result)

    return summary


def format_batch_summary(summary: BatchSummary) -> str:
    """Human-readable batch run report."""
    lines = [
        '',
        '=== Batch Summary ===',
        f'Files processed: {summary.total}',
        f'Succeeded: {summary.succeeded}',
        f'Failed: {summary.failed}',
        '',
    ]
    for item in summary.results:
        status = 'OK' if item.success else 'FAIL'
        lines.append(f'[{status}] {item.input_path.name}: {item.message}')
        if item.csv_path:
            lines.append(f'       CSV: {item.csv_path}')
    return '\n'.join(lines)
