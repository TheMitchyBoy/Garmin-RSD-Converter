#!/usr/bin/env python3
"""
Deprecated legacy Garmin Sonar RSD parser.

This module is retained for backward compatibility. New code should use
sonar_converter_streaming.py via sonar_cli.py.
"""

import sys
import warnings
from pathlib import Path
from typing import Optional, Tuple

from sonar_converter_streaming import convert_sonar_rsd_to_csv
from sonar_schema import setup_logging

warnings.warn(
    'sonar_converter.py is deprecated; use sonar_converter_streaming.py or sonar_cli.py instead.',
    DeprecationWarning,
    stacklevel=2,
)


def main() -> int:
    setup_logging()

    if len(sys.argv) < 2:
        print("Usage: python sonar_converter.py <input_rsd_file> [output_csv_file] [stride]")
        print("Note: This script is deprecated. Prefer: python sonar_cli.py convert <input>")
        return 1

    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    stride = int(sys.argv[3]) if len(sys.argv) > 3 else 256

    result_file, frame_count = convert_sonar_rsd_to_csv(input_file, output_file, stride=stride)
    print(f"✓ Conversion successful (via streaming parser)")
    print(f"  Output: {result_file}")
    print(f"  Frames: {frame_count}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
