"""Tests for survey visualization helpers."""

from pathlib import Path

from survey_viz_data import (
    DEFAULT_DASHBOARD_GRID_SIZE,
    build_echogram_pings,
    load_csv_track_geojson,
)


def test_default_grid_finer_than_legacy():
    assert DEFAULT_DASHBOARD_GRID_SIZE < 0.01


def test_track_and_echogram_from_csv(tmp_path: Path):
    csv_path = tmp_path / 'survey.csv'
    csv_path.write_text(
        'frame_number,latitude,longitude,depth_m,sonar_intensity_avg,time_s\n'
        '1,61.1,-149.9,10.0,120,0.0\n'
        '2,61.2,-149.8,12.0,80,1.0\n'
        '3,61.3,-149.7,8.0,150,2.0\n',
        encoding='utf-8',
    )
    track = load_csv_track_geojson(csv_path)
    assert len(track['features']) == 1
    assert track['features'][0]['geometry']['type'] == 'LineString'
    assert len(track['features'][0]['geometry']['coordinates']) == 3
    pings = build_echogram_pings(csv_path)
    assert len(pings) == 3
    assert pings[0]['frame'] == 1
