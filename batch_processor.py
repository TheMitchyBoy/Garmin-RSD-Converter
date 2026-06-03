#!/usr/bin/env python3
"""
Discover Garmin Sonar RSD files and run bulk convert / pipeline workflows.

Supports explicit file lists, directories (recursive by default), and glob
patterns. Each RSD is decoded through PINGVerter; optional map exports and
the full analysis pipeline mirror the single-file ``sonar_cli.py`` commands.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

from sonar_converter_streaming import convert_sonar_rsd_to_csv
from analysis_tools import MapGenerator
from export_tools import generate_map_exports
from heatmap_generator import HeatmapGenerator
from fish_detection import FishDetector
from population_health import PopulationHealthAnalytics
from survey_viz_data import DEFAULT_DASHBOARD_GRID_SIZE
from web_visualizer import WebVisualizer

logger = logging.getLogger(__name__)

RSD_SUFFIXES = {'.rsd', '.RSD'}
CSV_SUFFIXES = {'.csv', '.CSV'}


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


def is_csv_file(path: Path) -> bool:
    return path.is_file() and path.suffix in CSV_SUFFIXES


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



def _count_csv_rows(csv_file: Path) -> int:
    import csv as csv_module

    with open(csv_file, newline='', encoding='utf-8', errors='replace') as handle:
        return sum(1 for _ in csv_module.DictReader(handle))


def run_csv_analysis_pipeline(
    csv_file: Path,
    *,
    location: Optional[str] = None,
    full_pipeline: bool = True,
    map_formats: Optional[Sequence[str]] = None,
    grid_size: float = DEFAULT_DASHBOARD_GRID_SIZE,
) -> List[Path]:
    """Run map / heatmap / fish analysis on an existing project CSV."""
    label = _location_label(csv_file, location)
    out_dir = csv_file.parent
    slug = WebVisualizer._slugify(label)
    outputs: List[Path] = [csv_file]

    if full_pipeline:
        outputs.extend([
            MapGenerator.create_ply(csv_file),
            MapGenerator.create_geojson(csv_file),
            MapGenerator.create_kml(csv_file),
            MapGenerator.create_gpx(csv_file),
        ])
        intensity_hm = HeatmapGenerator.create_intensity_heatmap(csv_file, grid_size=grid_size)
        depth_hm = HeatmapGenerator.create_depth_heatmap(csv_file, grid_size=grid_size)
        temperature_hm = HeatmapGenerator.create_temperature_heatmap(csv_file, grid_size=grid_size)
        outputs.extend([intensity_hm, depth_hm, temperature_hm])
        seabed_3d = WebVisualizer.create_seabed_3d_chart(
            depth_hm,
            location_name=label,
            output_file=out_dir / f"seabed_3d_{slug}.html",
        )
        outputs.append(seabed_3d)

        detections_file, detections = FishDetector.detect_fish(csv_file)
        outputs.append(detections_file)

        metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
        outputs.append(
            PopulationHealthAnalytics.generate_public_report(
                metrics,
                location_name=label,
                output_file=out_dir / f'fishing_health_report_{slug}.md',
            )
        )
        outputs.append(
            WebVisualizer.create_dashboard(
                detections_file,
                metrics,
                location_name=label,
                depth_geojson_file=depth_hm,
                seabed_3d_file=seabed_3d,
                output_file=out_dir / f'fishing_dashboard_{slug}.html',
                csv_file=csv_file,
                grid_size=grid_size,
            )
        )
    elif map_formats:
        outputs.extend(generate_map_exports(csv_file, map_formats))

    return outputs


def batch_analyze_csv(
    sources: Sequence[Union[str, Path]],
    *,
    output_dir: Optional[Union[str, Path]] = None,
    location: Optional[str] = None,
    full_pipeline: bool = True,
    map_formats: Optional[Sequence[str]] = None,
    continue_on_error: bool = True,
) -> BatchSummary:
    """Analyze existing sonar CSV files (maps, heatmaps, fish, dashboard)."""
    import shutil

    summary = BatchSummary()
    out_root = Path(output_dir).expanduser() if output_dir else None

    for raw in sources:
        input_file = Path(raw).expanduser()
        result = FileJobResult(input_path=input_file, success=False)
        if not is_csv_file(input_file):
            result.message = 'Not a CSV file'
            summary.results.append(result)
            continue

        label = _location_label(input_file, location)
        header_error = validate_sonar_csv(input_file)
        if header_error:
            result.message = header_error
            summary.results.append(result)
            continue
        try:
            if out_root:
                out_root.mkdir(parents=True, exist_ok=True)
                csv_file = out_root / input_file.name
                shutil.copy2(input_file, csv_file)
            else:
                csv_file = input_file

            result.csv_path = csv_file
            frame_count = _count_csv_rows(csv_file)
            result.frame_count = frame_count
            result.outputs.extend(
                run_csv_analysis_pipeline(
                    csv_file,
                    location=label,
                    full_pipeline=full_pipeline,
                    map_formats=map_formats,
                )
            )

            if full_pipeline:
                result.message = f'Analysis complete: {frame_count:,} rows'
            elif map_formats:
                result.message = f'Generated map exports ({frame_count:,} rows)'
            else:
                result.message = f'CSV ready ({frame_count:,} rows)'

            result.success = True
        except Exception as exc:
            result.message = str(exc)
            logger.error('Failed to analyze %s: %s', input_file, exc)
            if not continue_on_error:
                summary.results.append(result)
                raise
        summary.results.append(result)

    return summary


def merge_batch_summaries(*summaries: BatchSummary) -> BatchSummary:
    merged = BatchSummary()
    for summary in summaries:
        merged.results.extend(summary.results)
    return merged


def batch_process_uploads(
    rsd_paths: Sequence[Path],
    csv_paths: Sequence[Path],
    *,
    output_dir: Union[str, Path],
    workflow: str = 'convert',
    nchunk: int = 500,
    map_formats: Optional[Sequence[str]] = None,
    location: Optional[str] = None,
) -> BatchSummary:
    """Process a mixed upload of RSD and/or CSV files for the web UI."""
    summaries: List[BatchSummary] = []

    if rsd_paths:
        if workflow == 'pipeline':
            summaries.append(
                batch_pipeline(
                    rsd_paths,
                    output_dir=output_dir,
                    nchunk=nchunk,
                    location=location,
                )
            )
        else:
            summaries.append(
                batch_convert(
                    rsd_paths,
                    output_dir=output_dir,
                    nchunk=nchunk,
                    map_formats=map_formats,
                )
            )

    if csv_paths:
        summaries.append(
            batch_analyze_csv(
                csv_paths,
                output_dir=output_dir,
                location=location,
                full_pipeline=(workflow == 'pipeline'),
                map_formats=map_formats if workflow != 'pipeline' else None,
            )
        )

    if not summaries:
        return BatchSummary()
    if len(summaries) == 1:
        return summaries[0]
    return merge_batch_summaries(*summaries)



def validate_sonar_csv(csv_file: Path) -> Optional[str]:
    """Return an error message when CSV is not a supported sonar export."""
    import csv as csv_module

    try:
        with open(csv_file, newline='', encoding='utf-8', errors='replace') as handle:
            reader = csv_module.DictReader(handle)
            if not reader.fieldnames:
                return 'CSV has no header row.'
            fields = {name.strip().lower() for name in reader.fieldnames if name}
            if 'latitude' not in fields or 'longitude' not in fields:
                return (
                    'CSV must include latitude and longitude columns '
                    '(use a PINGVerter/Garmin sonar export CSV).'
                )
            if not any(reader):
                return 'CSV has no data rows.'
    except OSError as exc:
        return f'Could not read CSV: {exc}'
    except csv_module.Error as exc:
        return f'Invalid CSV format: {exc}'
    return None


def batch_convert(
    sources: Sequence[Union[str, Path]],
    *,
    output_dir: Optional[Union[str, Path]] = None,
    nchunk: int = 500,
    stride: Optional[int] = None,
    map_formats: Optional[Sequence[str]] = None,
    recursive: bool = True,
    continue_on_error: bool = True,
) -> BatchSummary:
    """Convert multiple RSD files to CSV via PINGVerter, optionally generating map exports."""
    chunk_size = stride if stride is not None else nchunk
    files = discover_rsd_files(sources, recursive=recursive)
    summary = BatchSummary()

    if not files:
        logger.warning('No RSD files found in: %s', list(sources))
        return summary

    out_root = Path(output_dir).expanduser() if output_dir else None

    for input_file in files:
        result = FileJobResult(input_path=input_file, success=False)
        try:
            csv_path = _resolve_output_csv(input_file, out_root)
            csv_file, frame_count = convert_sonar_rsd_to_csv(
                input_file, csv_path, nchunk=chunk_size,
            )
            result.csv_path = csv_file
            result.frame_count = frame_count
            result.outputs.append(csv_file)

            if map_formats:
                result.outputs.extend(generate_map_exports(csv_file, map_formats))

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
    nchunk: int = 500,
    stride: Optional[int] = None,
    location: Optional[str] = None,
    recursive: bool = True,
    continue_on_error: bool = True,
) -> BatchSummary:
    """Run the full analysis pipeline on each RSD file."""
    chunk_size = stride if stride is not None else nchunk
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
                input_file, csv_path, nchunk=chunk_size,
            )
            result.csv_path = csv_file
            result.frame_count = frame_count
            pipeline_outputs = run_csv_analysis_pipeline(
                csv_file, location=label, full_pipeline=True,
            )
            result.outputs.extend(pipeline_outputs)

            detections_file = next(
                (path for path in pipeline_outputs if path.name.endswith('_fish_detections.geojson')),
                None,
            )
            detection_count = 0
            if detections_file and detections_file.exists():
                import json
                with open(detections_file, encoding='utf-8') as handle:
                    payload = json.load(handle)
                detection_count = len(payload.get('features', []))

            result.success = True
            result.message = (
                f'Pipeline complete: {frame_count:,} frames, '
                f'{detection_count:,} fish detections'
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
