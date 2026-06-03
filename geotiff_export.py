#!/usr/bin/env python3
"""
GeoTIFF bathymetry export (stdlib-only, WGS84 georeferenced).

Writes a single-band Float32 TIFF with GeoTIFF tags (ModelPixelScale,
ModelTiepoint, GeoKeyDirectory) so QGIS and GDAL can open depth grids without
external dependencies. NoData pixels use -9999.0 for empty grid cells.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from heatmap_generator import HeatmapGenerator


class GeoTiffWriter:
    """Write a single-band Float32 GeoTIFF with WGS84 georeferencing."""

    @staticmethod
    def create_depth_geotiff(
        csv_file: Path,
        grid_size: float = 0.01,
        output_file: Optional[Path] = None,
        nodata: float = -9999.0,
    ) -> Path:
        csv_file = Path(csv_file)
        if output_file is None:
            output_file = csv_file.with_name(f"{csv_file.stem}_depth.tif")
        else:
            output_file = Path(output_file)

        grid, meta = HeatmapGenerator.build_depth_grid(csv_file, grid_size)
        if not grid:
            raise ValueError("No depth data available for GeoTIFF export")

        min_gx = meta["min_gx"]
        max_gx = meta["max_gx"]
        min_gy = meta["min_gy"]
        max_gy = meta["max_gy"]
        width = max_gx - min_gx + 1
        height = max_gy - min_gy + 1

        # Build north-up raster: rows iterate from max grid Y downward (north→south)
        pixels: List[float] = []
        for gy in range(max_gy, min_gy - 1, -1):
            for gx in range(min_gx, max_gx + 1):
                val = grid.get((gx, gy))
                pixels.append(float(val) if val is not None else nodata)

        origin_lon = min_gx * grid_size
        origin_lat = (max_gy + 1) * grid_size
        pixel_w = grid_size
        pixel_h = -grid_size

        GeoTiffWriter._write_float32_geotiff(
            output_file,
            width,
            height,
            pixels,
            origin_lon,
            origin_lat,
            pixel_w,
            pixel_h,
            nodata,
        )
        return output_file

    @staticmethod
    def _write_float32_geotiff(
        path: Path,
        width: int,
        height: int,
        pixels: List[float],
        origin_lon: float,
        origin_lat: float,
        pixel_w: float,
        pixel_h: float,
        nodata: float,
    ) -> None:
        if len(pixels) != width * height:
            raise ValueError("Pixel buffer size mismatch")

        image_bytes = b"".join(struct.pack("<f", v) for v in pixels)

        # GeoKey directory (WGS84 / geographic), 4 keys
        geo_keys = struct.pack(
            "<HHHHHHHHHHHHHHHHHHHH",
            1, 1, 0, 4,
            1024, 0, 1, 2,
            1025, 0, 1, 1,
            2048, 0, 1, 4326,
            2054, 0, 1, 9102,
        )

        model_pixel_scale = struct.pack("<ddd", pixel_w, abs(pixel_h), 0.0)
        model_tiepoint = struct.pack(
            "<dddddd",
            0.0, 0.0, 0.0,
            origin_lon, origin_lat, 0.0,
        )
        nodata_str = f"{nodata}\0".encode("ascii")

        def ifd_entry(tag: int, field_type: int, count: int, value_or_offset: int) -> bytes:
            return struct.pack("<HHII", tag, field_type, count, value_or_offset)

        header_size = 8
        num_entries = 15
        ifd_size = 2 + num_entries * 12 + 4
        strip_byte_counts = len(image_bytes)

        scale_offset = header_size + ifd_size
        tiepoint_offset = scale_offset + len(model_pixel_scale)
        geo_keys_offset = tiepoint_offset + len(model_tiepoint)
        nodata_offset = geo_keys_offset + len(geo_keys)
        strip_offset = nodata_offset + len(nodata_str)

        entries = [
            ifd_entry(256, 4, 1, width),           # ImageWidth
            ifd_entry(257, 4, 1, height),          # ImageLength
            ifd_entry(258, 3, 1, 32),              # BitsPerSample = 32
            ifd_entry(259, 3, 1, 1),               # Compression = none
            ifd_entry(262, 3, 1, 1),               # Photometric = min-is-black
            ifd_entry(277, 3, 1, 1),               # SamplesPerPixel
            ifd_entry(278, 4, 1, height),          # RowsPerStrip
            ifd_entry(279, 4, 1, strip_byte_counts),  # StripByteCounts
            ifd_entry(273, 4, 1, strip_offset),    # StripOffsets
            ifd_entry(284, 3, 1, 1),               # PlanarConfiguration
            ifd_entry(339, 3, 1, 3),               # SampleFormat = IEEE float
            ifd_entry(33550, 12, 3, scale_offset), # ModelPixelScaleTag
            ifd_entry(33922, 12, 6, tiepoint_offset),  # ModelTiepointTag
            ifd_entry(34735, 3, len(geo_keys) // 2, geo_keys_offset),  # GeoKeyDirectory
            ifd_entry(42113, 2, len(nodata_str), nodata_offset),  # GDAL_NODATA
        ]

        ifd = struct.pack("<H", num_entries)
        for entry in entries:
            ifd += entry
        ifd += struct.pack("<I", 0)  # next IFD

        with open(path, "wb") as f:
            f.write(b"II")
            f.write(struct.pack("<H", 42))
            f.write(struct.pack("<I", header_size))
            f.write(ifd)
            f.write(model_pixel_scale)
            f.write(model_tiepoint)
            f.write(geo_keys)
            f.write(nodata_str)
            f.write(image_bytes)
