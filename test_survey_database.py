"""Tests for survey database."""

import json
import tempfile
from pathlib import Path

from survey_database import init_db, list_uploads, record_completed_upload, save_labels


def test_record_and_list_upload(tmp_path: Path):
    init_db()
    session = tmp_path / 'abc123'
    session.mkdir()
    csv = session / 'test.csv'
    csv.write_text(
        'frame_number,latitude,longitude,depth_m,sonar_intensity_avg,time_s\n'
        '1,61.1,-149.9,10,100,0\n2,61.2,-149.8,12,90,1\n',
        encoding='utf-8',
    )
    fish = session / 'test_fish_detections.geojson'
    fish.write_text(
        json.dumps({'type': 'FeatureCollection', 'features': [{
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [-149.9, 61.1]},
            'properties': {'size': 'medium'},
        }]}),
        encoding='utf-8',
    )
    record_completed_upload(
        session_id='abc123',
        job_id='job1',
        survey_name='test',
        location='Bay',
        workflow='pipeline',
        session_dir=session,
        result_payload={
            'results': [{
                'name': 'test.csv',
                'success': True,
                'csv': str(csv),
                'artifacts': [
                    {'type': 'csv', 'path': 'test.csv', 'url': '/x'},
                    {'type': 'geojson', 'path': 'test_fish_detections.geojson', 'url': '/y'},
                ],
            }],
        },
        output_root=tmp_path,
    )
    rows = list_uploads()
    assert any(r['id'] == 'abc123' for r in rows)


def test_save_labels(tmp_path: Path):
    import os
    os.environ['SURVEY_DB_PATH'] = str(tmp_path / 'test.db')
    init_db()
    record_completed_upload(
        session_id='s1',
        job_id='j',
        survey_name='s',
        location=None,
        workflow='pipeline',
        session_dir=tmp_path / 's1',
        result_payload={'results': []},
        output_root=tmp_path,
    )
    n = save_labels('s1', [{'species': 'salmon', 'frame': 1, 'latitude': 61.0, 'longitude': -149.0}])
    assert n == 1
