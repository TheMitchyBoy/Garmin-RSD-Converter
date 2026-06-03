"""Tests for 3D seabed chart generation."""

import json
from pathlib import Path

from web_visualizer import WebVisualizer


def test_create_seabed_3d_chart_from_depth_polygons(tmp_path: Path):
    depth_geojson = tmp_path / "depth.geojson"
    depth_geojson.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [-149.90, 61.10],
                                [-149.89, 61.10],
                                [-149.89, 61.11],
                                [-149.90, 61.11],
                                [-149.90, 61.10],
                            ]],
                        },
                        "properties": {"depth_m": 8.2},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-149.88, 61.12]},
                        "properties": {"depth_m": 12.7},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    output = WebVisualizer.create_seabed_3d_chart(
        depth_geojson,
        location_name="Unit Test Lake",
        output_file=tmp_path / "seabed_3d_unit_test_lake.html",
    )
    text = output.read_text(encoding="utf-8")
    assert output.exists()
    assert "Plotly.newPlot" in text
    assert "mesh3d" in text
    assert "3D Seabed Chart" in text


def test_create_seabed_3d_chart_handles_empty_depth_features(tmp_path: Path):
    depth_geojson = tmp_path / "empty_depth.geojson"
    depth_geojson.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    output = WebVisualizer.create_seabed_3d_chart(
        depth_geojson,
        location_name="No Data Lake",
        output_file=tmp_path / "seabed_3d_no_data.html",
    )
    text = output.read_text(encoding="utf-8")
    assert "No seabed depth points were available" in text
