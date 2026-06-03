"""Tests for streaming upload form parsing."""

from __future__ import annotations

import io
from pathlib import Path

from sonar_upload_server import _parse_request_form_data_streaming


def _multipart_body(boundary: str, parts: list[dict]) -> bytes:
    chunks = []
    for part in parts:
        chunks.append(f'--{boundary}\r\n'.encode('utf-8'))
        disposition = f'form-data; name="{part["name"]}"'
        if part.get('filename'):
            disposition += f'; filename="{part["filename"]}"'
        chunks.append(f'Content-Disposition: {disposition}\r\n'.encode('utf-8'))
        if part.get('content_type'):
            chunks.append(f'Content-Type: {part["content_type"]}\r\n'.encode('utf-8'))
        chunks.append(b'\r\n')
        payload = part['value']
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        chunks.append(payload)
        chunks.append(b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode('utf-8'))
    return b''.join(chunks)


def test_streaming_multipart_parses_fields_and_csv(tmp_path: Path):
    boundary = '----BoundaryUploadTest'
    csv_bytes = (
        b'frame_number,latitude,longitude,depth_m,sonar_intensity_avg,time_s\n'
        b'1,61.1,-149.9,10,120,0.0\n'
    )
    body = _multipart_body(boundary, [
        {'name': 'workflow', 'value': 'pipeline'},
        {'name': 'nchunk', 'value': '500'},
        {'name': 'files', 'filename': 'sample.csv', 'content_type': 'text/csv', 'value': csv_bytes},
    ])
    fields, saved = _parse_request_form_data_streaming(
        f'multipart/form-data; boundary={boundary}',
        io.BytesIO(body),
        len(body),
        tmp_path / 'uploads',
    )
    assert fields['workflow'] == ['pipeline']
    assert fields['nchunk'] == ['500']
    assert len(saved) == 1
    assert saved[0].suffix.lower() == '.csv'
    assert saved[0].read_bytes() == csv_bytes


def test_streaming_multipart_ignores_unsupported_extensions(tmp_path: Path):
    boundary = '----BoundaryUploadTest2'
    body = _multipart_body(boundary, [
        {'name': 'files', 'filename': 'notes.txt', 'content_type': 'text/plain', 'value': 'not sonar'},
    ])
    fields, saved = _parse_request_form_data_streaming(
        f'multipart/form-data; boundary={boundary}',
        io.BytesIO(body),
        len(body),
        tmp_path / 'uploads',
    )
    assert fields == {}
    assert saved == []
