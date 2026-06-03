#!/usr/bin/env python3
"""
LAS / LAZ point cloud export from sonar CSV data (stdlib-only LAS writer).
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
from pathlib import Path
from typing import List, Optional

from analysis_tools import MapGenerator

logger = logging.getLogger(__name__)


class LasExporter:
    """Export sonar points to ASPRS LAS 1.2 (optionally compress to LAZ via laszip)."""

    @staticmethod
    def create_las(
        csv_file: Path,
        output_file: Optional[Path] = None,
        compress: bool = False,
    ) -> Path:
        """
        Write LAS 1.2 point cloud. When compress=True, attempts laszip CLI for LAZ.
        Falls back to .las if laszip is unavailable.
        """
        csv_file = Path(csv_file)
        if output_file is None:
            suffix = ".laz" if compress else ".las"
            output_file = csv_file.with_name(f"{csv_file.stem}_3d{suffix}")
        else:
            output_file = Path(output_file)

        points = LasExporter._read_sonar_points(csv_file)
        if not points:
            raise ValueError("No valid sonar point data found for LAS export")

        las_path = output_file
        if compress and output_file.suffix.lower() == ".laz":
            las_path = output_file.with_suffix(".las")

        LasExporter._write_las12(las_path, points)

        if compress and output_file.suffix.lower() == ".laz":
            if LasExporter._try_laszip_compress(las_path, output_file):
                las_path.unlink(missing_ok=True)
                return output_file
            logger.warning("laszip not found; keeping uncompressed .las instead of .laz")
            return las_path

        return las_path

    @staticmethod
    def _read_sonar_points(csv_file: Path) -> List[dict]:
        import csv

        points: List[dict] = []
        origin_lat: Optional[float] = None
        origin_lon: Optional[float] = None

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row.get("latitude") or 0)
                    lon = float(row.get("longitude") or 0)
                    if lat == 0 and lon == 0:
                        continue
                    if origin_lat is None:
                        origin_lat = lat
                        origin_lon = lon

                    depth = row.get("depth_m")
                    depth_f = float(depth) if depth not in (None, "") else None
                    if depth_f is None:
                        continue

                    x, y = MapGenerator._wgs84_to_local_xy(lat, lon, origin_lat, origin_lon)
                    intensity = float(row.get("sonar_intensity_avg") or 0)
                    points.append({
                        "x": x,
                        "y": y,
                        "z": -depth_f,
                        "intensity": min(65535, max(0, int(intensity))),
                    })
                except (ValueError, TypeError):
                    continue
        return points

    @staticmethod
    def _write_las12(path: Path, points: List[dict]) -> None:
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        zs = [p["z"] for p in points]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)

        scale = 0.001
        offset_x, offset_y, offset_z = min_x, min_y, min_z

        def to_int(v: float, off: float) -> int:
            return int(round((v - off) / scale))

        header_size = 227
        point_record_len = 28
        num_points = len(points)
        offset_to_points = header_size

        header = bytearray(227)
        header[0:4] = b"LASF"
        struct.pack_into("<H", header, 4, 0)
        struct.pack_into("<H", header, 6, 0)
        header[24] = 1
        header[25] = 2
        header[26:58] = b"Sonar RSD Converter".ljust(32)[:32]
        header[58:90] = b"Garmin Sonar RSD".ljust(32)[:32]
        struct.pack_into("<H", header, 90, 1)
        struct.pack_into("<H", header, 92, 2026)
        struct.pack_into("<H", header, 94, 227)
        struct.pack_into("<I", header, 96, offset_to_points)
        struct.pack_into("<I", header, 100, 0)
        header[104] = 1
        struct.pack_into("<H", header, 105, point_record_len)
        struct.pack_into("<I", header, 107, num_points)
        struct.pack_into("<I", header, 111, num_points)
        struct.pack_into("<d", header, 131, scale)
        struct.pack_into("<d", header, 139, scale)
        struct.pack_into("<d", header, 147, scale)
        struct.pack_into("<d", header, 155, offset_x)
        struct.pack_into("<d", header, 163, offset_y)
        struct.pack_into("<d", header, 171, offset_z)
        struct.pack_into("<d", header, 179, max_x)
        struct.pack_into("<d", header, 187, min_x)
        struct.pack_into("<d", header, 195, max_y)
        struct.pack_into("<d", header, 203, min_y)
        struct.pack_into("<d", header, 211, max_z)
        struct.pack_into("<d", header, 219, min_z)

        with open(path, "wb") as f:
            f.write(header)
            for p in points:
                record = struct.pack(
                    "<iiiHBBiii",
                    to_int(p["x"], offset_x),
                    to_int(p["y"], offset_y),
                    to_int(p["z"], offset_z),
                    p["intensity"],
                    0,
                    0,
                    0, 0, 0,
                )
                f.write(record)

    @staticmethod
    def _try_laszip_compress(las_path: Path, laz_path: Path) -> bool:
        laszip = shutil.which("laszip") or shutil.which("laszip64")
        if not laszip:
            return False
        try:
            subprocess.run(
                [laszip, "-i", str(las_path), "-o", str(laz_path)],
                check=True,
                capture_output=True,
            )
            return laz_path.exists()
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.debug("laszip compression failed: %s", exc)
            return False
