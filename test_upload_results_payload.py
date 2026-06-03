"""Tests for upload results payload artifact exposure."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sonar_upload_server import _completed_job_payload_from_upload, _summary_to_payload


def test_summary_payload_includes_seabed_3d_url(tmp_path: Path):
    session_dir = tmp_path / 'session-123'
    session_dir.mkdir()
    dashboard = session_dir / 'dashboard_demo.html'
    seabed = session_dir / 'seabed_3d_demo.html'
    dashboard.write_text('<html></html>', encoding='utf-8')
    seabed.write_text('<html></html>', encoding='utf-8')

    item = SimpleNamespace(
        input_path=Path('sample.csv'),
        success=True,
        message='ok',
        csv_path=None,
        outputs=[dashboard, seabed],
    )
    summary = SimpleNamespace(total=1, succeeded=1, failed=0, results=[item])

    payload = _summary_to_payload(summary, session_dir)

    assert payload.get('dashboard_url', '').endswith('/dashboard_demo.html')
    assert payload.get('seabed_3d_url', '').endswith('/seabed_3d_demo.html')
    artifacts = payload['results'][0]['artifacts']
    assert any(a['type'] == 'seabed_3d' for a in artifacts)


def test_completed_payload_recovers_seabed_chart_from_session_files(tmp_path: Path):
    session_id = 'session-456'
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    seabed = session_dir / 'seabed_3d_recovered.html'
    seabed.write_text('<html></html>', encoding='utf-8')

    upload = {
        'id': session_id,
        'survey_name': 'Recovered survey',
        'dashboard_path': None,
        'csv_path': None,
        'fish_geojson_path': None,
        'depth_geojson_path': None,
    }
    payload = _completed_job_payload_from_upload(upload, tmp_path)

    assert payload.get('seabed_3d_url', '').endswith('/seabed_3d_recovered.html')
    artifacts = payload['results'][0]['artifacts']
    assert any(
        artifact['type'] == 'seabed_3d' and artifact['path'] == 'seabed_3d_recovered.html'
        for artifact in artifacts
    )
