#!/usr/bin/env python3
"""
Generate a minimal synthetic .RSD file for testing and demos.

The binary layout matches the heuristic offsets used by sonar_converter_streaming.py.
"""

import struct
import sys
from pathlib import Path


def encode_coordinate(degrees: float) -> int:
    return int(round(degrees * 10_000_000))


def build_frame(
    latitude: float,
    longitude: float,
    depth_m: float,
    water_temp_c: float,
    frequency_khz: float,
    intensities: list[int],
) -> bytes:
    data = bytearray(256)
    struct.pack_into('<i', data, 4, encode_coordinate(latitude))
    struct.pack_into('<i', data, 8, encode_coordinate(longitude))
    struct.pack_into('<H', data, 10, int(depth_m * 10))
    struct.pack_into('<h', data, 14, int(water_temp_c * 10))
    struct.pack_into('<H', data, 16, min(int(frequency_khz * 1000), 65535))

    offset = 32
    for value in intensities:
        if offset + 2 > len(data):
            break
        struct.pack_into('<H', data, offset, value)
        offset += 2

    return bytes(data)


def generate_sample_rsd(output_file: Path, frame_count: int = 8) -> Path:
    """Write a synthetic RSD file with a short GPS track."""
    output_file = Path(output_file)
    base_lat = 40.7128
    base_lon = -74.0060

    with open(output_file, 'wb') as handle:
        for index in range(frame_count):
            lat = base_lat + index * 0.0001
            lon = base_lon + index * 0.0001
            depth = 5.0 + index * 1.5
            temp = 18.0 + index * 0.1
            intensity_base = 50 + index * 15
            intensities = [intensity_base + (value % 20) for value in range(16)]
            handle.write(
                build_frame(lat, lon, depth, temp, 50.0, intensities)
            )

    return output_file


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('fixtures/sample_sonar.rsd')
    target.parent.mkdir(parents=True, exist_ok=True)
    path = generate_sample_rsd(target)
    print(f'Generated sample RSD: {path} ({path.stat().st_size} bytes)')
