#!/usr/bin/env python3
"""
Garmin RSD conversion via PINGVerter (pingverter package).

This module is the core conversion layer. It wraps PINGVerter's ``gar`` class,
which implements the documented Garmin RSD binary format (see Herbert Oppmann's
format notes), and normalizes decoded pings into the project's CSV schema.

Multi-channel RSD files produce one row per *sequence* (shared timestamp),
preferring down-looking beams (1=Traditional CHIRP, 4=Down Imaging) for depth
and GPS so track/bathymetry exports are not duplicated per side-scan channel.

Intensity columns are derived from raw uint16 sample arrays when PINGVerter
can extract them; otherwise those fields are left blank.
"""

from __future__ import annotations

import csv
import logging
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_CSV_FIELDS = [
    'frame_number',
    'offset',
    'latitude',
    'longitude',
    'depth_m',
    'water_temp_c',
    'sonar_frequency_khz',
    'sonar_intensity_avg',
    'sonar_intensity_max',
    'sonar_intensity_count',
    'channel_id',
    'beam',
    'sequence_cnt',
    'time_s',
]

# Beam priority when collapsing multi-channel pings to one track row.
# Lower index = higher priority. Down-looking beams give the best depth/GPS
# for bathymetry; side-scan channels (2/3) are fallbacks only.
PREFERRED_BEAMS = (1, 4, 0, 2, 3)


def _require_pingverter():
    try:
        from pingverter import gar
        return gar
    except ImportError as exc:
        raise ImportError(
            'PINGVerter is required for RSD conversion. Install with: pip install pingverter'
        ) from exc


def parse_rsd_with_pingverter(
    input_file: Path,
    nchunk: int = 500,
    export_unknown: bool = False,
    meta_dir: Optional[Path] = None,
):
    """
    Parse a Garmin RSD file and return an initialized pingverter.gar instance.

    Runs the full PINGVerter header + ping decode pipeline:
    file length → file header (channel info) → ping headers → record numbering.

    ``meta_dir`` holds intermediate CSV/debug output from PINGVerter; callers
    should use a temp directory and delete it after export.
    """
    gar = _require_pingverter()
    input_file = Path(input_file)

    if meta_dir is None:
        meta_dir = Path(tempfile.mkdtemp(prefix='pingverter_meta_'))
    else:
        meta_dir = Path(meta_dir)
        meta_dir.mkdir(parents=True, exist_ok=True)

    sonar = gar(str(input_file), nchunk=nchunk, exportUnknown=export_unknown)
    sonar.metaDir = str(meta_dir)
    sonar._getFileLen()
    sonar._parseFileHeader()
    sonar._parsePingHeader()
    sonar._recalcRecordNum()

    if not hasattr(sonar, 'header_dat') or sonar.header_dat is None or len(sonar.header_dat) == 0:
        raise ValueError(f'PINGVerter decoded no ping records from {input_file}')

    return sonar


def _freq_khz_for_channel(sonar, channel_id) -> Optional[float]:
    try:
        cid = int(channel_id)
    except (TypeError, ValueError):
        return None

    for info in getattr(sonar, 'channel_info', []) or []:
        try:
            if int(info.get('channel_id', -1)) != cid:
                continue
            start_hz = info.get('start_freq_hz')
            end_hz = info.get('end_freq_hz')
            if start_hz is not None and end_hz is not None and not (
                np.isnan(float(start_hz)) or np.isnan(float(end_hz))
            ):
                return (float(start_hz) + float(end_hz)) / 2000.0
        except (TypeError, ValueError):
            continue
    return None


def _sample_stats_for_row(
    sonar,
    row,
    channel_counters: Dict[int, int],
    samples_by_channel: Dict[int, List[np.ndarray]],
) -> Tuple[Optional[float], Optional[float], int]:
    """
    Look up raw sonar samples for one ping row.

    ``extract_raw_sample_arrays`` returns arrays grouped by channel_id in ping
    order; ``channel_counters`` tracks how many rows we've consumed per channel
    so stats align with the correct ping when iterating the dataframe.
    """
    try:
        channel_id = int(row['channel_id'])
    except (KeyError, TypeError, ValueError):
        return None, None, 0

    arrays = samples_by_channel.get(channel_id, [])
    idx = channel_counters.get(channel_id, 0)
    channel_counters[channel_id] = idx + 1

    if idx >= len(arrays):
        return None, None, 0

    arr = arrays[idx]
    if arr is None or arr.size == 0:
        return None, None, 0

    return float(np.mean(arr)), float(np.max(arr)), int(arr.size)


def _row_to_csv_dict(
    row,
    frame_number: int,
    sonar,
    channel_counters: Dict[int, int],
    samples_by_channel: Dict[int, List[np.ndarray]],
) -> Optional[dict]:
    try:
        lat = float(row['lat'])
        lon = float(row['lon'])
    except (KeyError, TypeError, ValueError):
        return None

    if np.isnan(lat) or np.isnan(lon) or (lat == 0 and lon == 0):
        return None

    depth = row.get('inst_dep_m', row.get('bottom_depth'))
    try:
        depth_m = float(depth) if depth is not None and not (isinstance(depth, float) and np.isnan(depth)) else None
    except (TypeError, ValueError):
        depth_m = None

    temp = row.get('tempC', row.get('water_temp'))
    try:
        temp_c = float(temp) if temp is not None and not (isinstance(temp, float) and np.isnan(temp)) else None
    except (TypeError, ValueError):
        temp_c = None

    intensity_avg, intensity_max, intensity_count = _sample_stats_for_row(
        sonar, row, channel_counters, samples_by_channel,
    )

    channel_id = row.get('channel_id')
    freq_khz = _freq_khz_for_channel(sonar, channel_id)

    offset = row.get('index', row.get('son_offset', 0))
    try:
        offset_val = int(offset)
    except (TypeError, ValueError):
        offset_val = 0

    sequence = row.get('sequence_cnt', frame_number)
    try:
        sequence_val = int(sequence)
    except (TypeError, ValueError):
        sequence_val = frame_number

    beam = row.get('beam')
    try:
        beam_val = int(beam) if beam is not None and not (isinstance(beam, float) and np.isnan(beam)) else ''
    except (TypeError, ValueError):
        beam_val = ''

    return {
        'frame_number': frame_number,
        'offset': offset_val,
        'latitude': round(lat, 8),
        'longitude': round(lon, 8),
        'depth_m': round(depth_m, 3) if depth_m is not None else '',
        'water_temp_c': round(temp_c, 2) if temp_c is not None else '',
        'sonar_frequency_khz': round(freq_khz, 2) if freq_khz is not None else '',
        'sonar_intensity_avg': round(intensity_avg, 2) if intensity_avg is not None else '',
        'sonar_intensity_max': round(intensity_max, 2) if intensity_max is not None else '',
        'sonar_intensity_count': intensity_count if intensity_count else '',
        'channel_id': int(channel_id) if channel_id is not None and not (
            isinstance(channel_id, float) and np.isnan(channel_id)
        ) else '',
        'beam': beam_val,
        'sequence_cnt': sequence_val,
        'time_s': row.get('time_s', ''),
    }


def _select_track_rows(df):
    """
    Collapse multi-channel pings to one row per ``sequence_cnt``.

    Garmin RSD files often contain parallel channels (CHIRP, SideVu port/star,
    Down Imaging) at the same instant. Map/heatmap/fish tools expect a single
    GPS track, so we pick one row per sequence using PREFERRED_BEAMS.
    """
    import pandas as pd

    if 'sequence_cnt' not in df.columns:
        return df.reset_index(drop=True)

    selected = []
    for _, group in df.groupby('sequence_cnt', sort=True):
        chosen = None
        if 'beam' in group.columns:
            for beam in PREFERRED_BEAMS:
                subset = group[group['beam'] == beam]
                if len(subset) > 0:
                    chosen = subset.iloc[0]
                    break
        if chosen is None and len(group) > 0:
            chosen = group.iloc[0]
        if chosen is not None:
            selected.append(chosen)

    if not selected:
        return df.reset_index(drop=True)
    return pd.DataFrame(selected).reset_index(drop=True)


def write_pingverter_csv(
    sonar,
    output_file: Path,
    track_only: bool = True,
) -> int:
    """Write PINGVerter ping metadata (and sample stats) to project CSV."""
    df = sonar.header_dat
    if track_only:
        df = _select_track_rows(df)

    samples_by_channel = sonar.extract_raw_sample_arrays(df)
    channel_counters: Dict[int, int] = defaultdict(int)

    rows: List[dict] = []
    for frame_number, (_, row) in enumerate(df.iterrows(), start=1):
        csv_row = _row_to_csv_dict(
            row, frame_number, sonar, channel_counters, samples_by_channel,
        )
        if csv_row is not None:
            rows.append(csv_row)

    output_file = Path(output_file)
    with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=PROJECT_CSV_FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def convert_sonar_rsd_to_csv(
    input_file: Path,
    output_file: Optional[Path] = None,
    stride: int = 256,
    nchunk: Optional[int] = None,
) -> Tuple[Path, int]:
    """
    Convert Garmin RSD to project CSV using PINGVerter.

    Args:
        input_file: Path to .RSD file
        output_file: Output CSV path
        stride: Deprecated alias for nchunk (backward compatibility)
        nchunk: PINGVerter chunk size (default 500)
    """
    input_file = Path(input_file)
    if not input_file.exists():
        raise FileNotFoundError(f'Input file not found: {input_file}')

    if output_file is None:
        output_file = input_file.with_suffix('.csv')
    else:
        output_file = Path(output_file)

    chunk_size = nchunk if nchunk is not None else (stride if stride != 256 else 500)

    logger.info(f'Converting via PINGVerter: {input_file} → {output_file}')
    logger.info(f'PINGVerter nchunk: {chunk_size}')

    meta_dir = tempfile.mkdtemp(prefix='pingverter_meta_')
    try:
        sonar = parse_rsd_with_pingverter(input_file, nchunk=chunk_size, meta_dir=Path(meta_dir))
        frame_count = write_pingverter_csv(sonar, output_file)
    finally:
        shutil.rmtree(meta_dir, ignore_errors=True)

    logger.info(f'✓ Conversion complete: {output_file} ({frame_count:,} frames)')
    return output_file, frame_count


def validate_rsd_file(
    input_file: Path,
    stride: int = 256,
    nchunk: Optional[int] = None,
    sample_limit: Optional[int] = None,
) -> dict:
    """Validate an RSD file by decoding with PINGVerter."""
    input_file = Path(input_file)
    if not input_file.exists():
        raise FileNotFoundError(f'Input file not found: {input_file}')

    chunk_size = nchunk if nchunk is not None else (stride if stride != 256 else 500)
    file_size = input_file.stat().st_size

    meta_dir = tempfile.mkdtemp(prefix='pingverter_validate_')
    try:
        sonar = parse_rsd_with_pingverter(input_file, nchunk=chunk_size, meta_dir=Path(meta_dir))
        df = sonar.header_dat
        if sample_limit is not None and len(df) > sample_limit:
            df = df.head(sample_limit)

        total = len(df)
        valid_gps = 0
        depth_ok = 0
        temp_ok = 0
        intensity_ok = 0
        freq_ok = 0

        for _, row in df.iterrows():
            try:
                lat = float(row.get('lat', np.nan))
                lon = float(row.get('lon', np.nan))
                if not (np.isnan(lat) or np.isnan(lon)) and not (lat == 0 and lon == 0):
                    valid_gps += 1
            except (TypeError, ValueError):
                pass

            depth = row.get('inst_dep_m', row.get('bottom_depth'))
            try:
                if depth is not None and float(depth) > 0:
                    depth_ok += 1
            except (TypeError, ValueError):
                pass

            temp = row.get('tempC')
            try:
                if temp is not None and float(temp) != 0:
                    temp_ok += 1
            except (TypeError, ValueError):
                pass

            ping_cnt = row.get('ping_cnt', row.get('sample_cnt', 0))
            try:
                if ping_cnt is not None and int(ping_cnt) > 0:
                    intensity_ok += 1
            except (TypeError, ValueError):
                pass

            if _freq_khz_for_channel(sonar, row.get('channel_id')) is not None:
                freq_ok += 1

        def pct(n: int) -> float:
            return round(n / total * 100, 1) if total else 0.0

        overall = (
            pct(valid_gps) * 0.35
            + pct(depth_ok) * 0.35
            + pct(intensity_ok) * 0.20
            + pct(temp_ok) * 0.05
            + pct(freq_ok) * 0.05
        )
        overall = round(min(100.0, max(0.0, overall)), 1)

        channel_count = len(getattr(sonar, 'channel_info', []) or [])
        unique_sequences = df['sequence_cnt'].nunique() if 'sequence_cnt' in df.columns else total

        return {
            'file': str(input_file),
            'file_size_bytes': file_size,
            'parser': 'PINGVerter',
            'nchunk': chunk_size,
            'frames_attempted': total,
            'frames_valid': total,
            'valid_frame_pct': 100.0 if total else 0.0,
            'gps_pct': pct(valid_gps),
            'depth_pct': pct(depth_ok),
            'temperature_pct': pct(temp_ok),
            'frequency_pct': pct(freq_ok),
            'intensity_pct': pct(intensity_ok),
            'overall_score': overall,
            'channel_count': channel_count,
            'unique_sequences': int(unique_sequences),
            'recommendation': _validation_recommendation(overall, pct(valid_gps), pct(depth_ok)),
        }
    finally:
        shutil.rmtree(meta_dir, ignore_errors=True)


def _validation_recommendation(overall: float, gps_pct: float, depth_pct: float) -> str:
    if overall >= 80:
        return 'Good — PINGVerter decoded usable ping metadata'
    if gps_pct < 40:
        return 'Poor GPS — verify the recording had a GPS fix during survey'
    if depth_pct < 40:
        return 'Poor depth data — file may be unsupported or incomplete'
    return 'Marginal — review CSV output before generating maps'


def format_validation_report(report: dict) -> str:
    """Format RSD validation report for CLI output."""
    lines = [
        '',
        '=== RSD Validation Report (PINGVerter) ===',
        f"File: {report['file']}",
        f"Size: {report['file_size_bytes']:,} bytes",
        f"Parser: {report.get('parser', 'PINGVerter')}",
        f"nchunk: {report.get('nchunk', report.get('stride', 'n/a'))}",
        f"Pings decoded: {report['frames_attempted']:,}",
        f"Unique sequences: {report.get('unique_sequences', 'n/a')}",
        f"Channels: {report.get('channel_count', 'n/a')}",
        '',
        'Field validity (decoded pings):',
        f"  GPS:         {report['gps_pct']:.1f}%",
        f"  Depth:       {report['depth_pct']:.1f}%",
        f"  Sample data: {report['intensity_pct']:.1f}%",
        f"  Temperature: {report['temperature_pct']:.1f}%",
        f"  Frequency:   {report['frequency_pct']:.1f}%",
        '',
        f"Overall score: {report['overall_score']}/100",
        f"Recommendation: {report['recommendation']}",
    ]
    return '\n'.join(lines)
