#!/usr/bin/env python3
"""
Garmin Sonar RSD conversion entry point.

All RSD decoding is delegated to PINGVerter via pingverter_adapter.
"""

from pathlib import Path

from pingverter_adapter import (
    convert_sonar_rsd_to_csv,
    validate_rsd_file,
    format_validation_report,
)

__all__ = [
    'convert_sonar_rsd_to_csv',
    'validate_rsd_file',
    'format_validation_report',
]


if __name__ == '__main__':
    import sys
    import logging

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    if len(sys.argv) < 2:
        print('Usage: python sonar_converter_streaming.py <input_rsd_file> [output_csv_file] [nchunk]')
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    nchunk = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    try:
        result_file, frame_count = convert_sonar_rsd_to_csv(
            Path(input_file), Path(output_file) if output_file else None, nchunk=nchunk,
        )
        print('✓ Conversion successful!')
        print(f'  Output: {result_file}')
        print(f'  Frames: {frame_count}')
    except Exception as e:
        logger.error(f'Conversion failed: {e}')
        sys.exit(1)
