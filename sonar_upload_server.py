#!/usr/bin/env python3
"""
Local web UI for uploading and bulk-processing Garmin Sonar RSD files.

Uses only the Python standard library (no pip dependencies).
"""

from __future__ import annotations

import argparse
import os
import json
import logging
import mimetypes
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

from area_map import build_area_map_geojson, load_echogram_segment
from batch_processor import batch_process_uploads, format_batch_summary
from survey_database import (
    get_db_path,
    get_upload_by_job_id,
    init_db,
    list_uploads,
    record_completed_upload,
    save_labels,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB per request
APP_BUILD_ID = '2026.06.03-upload-speed-compat-job-recovery'
# Hosted (Railway) web uploads: stream to disk; avoid loading huge bodies in RAM.
WEB_UPLOAD_MAX_BYTES = 150 * 1024 * 1024  # 150 MB per request on public UI
READ_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB
MAX_RETAINED_JOBS = 100
JOB_POLL_INTERVAL_SEC = 2


class JobStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


@dataclass
class ProcessingJob:
    """Background RSD conversion job (avoids long-lived HTTP requests on Railway)."""

    id: str
    status: JobStatus = JobStatus.PENDING
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    file_count: int = 0


RESULTS_ALLOWED_SUFFIXES = frozenset({
    '.html', '.htm', '.csv', '.geojson', '.json', '.kml', '.gpx', '.ply',
    '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.las', '.txt', '.md',
})


def _relative_output_path(session_dir: Path, artifact: Path) -> str:
    resolved = artifact.resolve()
    base = session_dir.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return artifact.name


def _classify_output_artifact(artifact: Path) -> Dict[str, str]:
    name = artifact.name.lower()
    if name.endswith('.html') and ('seabed_3d' in name or '3d_seabed' in name):
        return {'type': 'seabed_3d', 'label': '3D seabed chart'}
    if name.endswith('.html') and 'dashboard' in name:
        return {'type': 'dashboard', 'label': 'Analytics dashboard'}
    if name.endswith('_fish_detections.geojson'):
        return {'type': 'geojson', 'label': 'Fish detections (GeoJSON)'}
    if name.endswith('.geojson'):
        return {'type': 'geojson', 'label': 'Map layer (GeoJSON)'}
    if name.endswith('.kml'):
        return {'type': 'kml', 'label': 'KML map'}
    if name.endswith('.csv'):
        return {'type': 'csv', 'label': 'Sonar CSV'}
    if name.endswith('.png') or name.endswith('.jpg') or name.endswith('.jpeg'):
        return {'type': 'image', 'label': artifact.name}
    return {'type': 'file', 'label': artifact.name}


def _build_artifacts(session_dir: Path, item) -> List[Dict[str, str]]:
    session_id = session_dir.name
    artifacts: List[Dict[str, str]] = []
    seen: set[str] = set()
    for output_path in getattr(item, 'outputs', []) or []:
        path = Path(output_path)
        if not path.is_file():
            continue
        if path.suffix.lower() not in RESULTS_ALLOWED_SUFFIXES:
            continue
        rel = _relative_output_path(session_dir, path)
        if rel in seen:
            continue
        seen.add(rel)
        info = _classify_output_artifact(path)
        artifacts.append({
            'type': info['type'],
            'label': info['label'],
            'path': rel,
            'url': f'/results/{session_id}/{quote(rel, safe="/")}',
        })
    return artifacts


def _summary_to_payload(summary, session_dir: Path) -> Dict[str, Any]:
    session_id = session_dir.name
    results = []
    dashboard_urls: List[str] = []
    for item in summary.results:
        artifacts = _build_artifacts(session_dir, item)
        for artifact in artifacts:
            if artifact['type'] == 'dashboard':
                dashboard_urls.append(artifact['url'])
        results.append({
            'name': item.input_path.name,
            'success': item.success,
            'message': item.message,
            'csv': str(item.csv_path) if item.csv_path else None,
            'artifacts': artifacts,
        })
    payload: Dict[str, Any] = {
        'total': summary.total,
        'succeeded': summary.succeeded,
        'failed': summary.failed,
        'session_id': session_id,
        'output_dir': str(session_dir.resolve()),
        'results': results,
    }
    if dashboard_urls:
        payload['dashboard_url'] = dashboard_urls[0]
    return payload


def _prune_old_jobs(jobs: Dict[str, ProcessingJob]) -> None:
    if len(jobs) <= MAX_RETAINED_JOBS:
        return
    # Never evict active jobs; only prune completed/failed entries.
    terminal = sorted(
        (job for job in jobs.values() if job.status in (JobStatus.COMPLETED, JobStatus.FAILED)),
        key=lambda job: job.created_at,
    )
    prune_count = max(0, len(jobs) - MAX_RETAINED_JOBS)
    for job in terminal[:prune_count]:
        jobs.pop(job.id, None)


def _artifact_from_upload_record(
    upload: Dict[str, Any],
    session_id: str,
    field_name: str,
    *,
    artifact_type: str,
    label: str,
) -> Optional[Dict[str, str]]:
    stored = upload.get(field_name)
    if not stored:
        return None
    stored_path = Path(str(stored))
    parts = list(stored_path.parts)
    if parts and parts[0] == session_id:
        rel = Path(*parts[1:]).as_posix()
    else:
        rel = stored_path.name
    return {
        'type': artifact_type,
        'label': label,
        'path': rel,
        'url': f'/results/{session_id}/{quote(rel, safe="/")}',
    }


def _completed_job_payload_from_upload(upload: Dict[str, Any], output_root: Path) -> Dict[str, Any]:
    """Reconstruct a minimal completed payload when in-memory job state is unavailable."""
    session_id = str(upload.get('id') or '')
    survey_name = str(upload.get('survey_name') or session_id or 'survey')
    artifacts: List[Dict[str, str]] = []
    for spec in (
        ('dashboard_path', 'dashboard', 'Analytics dashboard'),
        ('csv_path', 'csv', 'Sonar CSV'),
        ('fish_geojson_path', 'geojson', 'Fish detections (GeoJSON)'),
        ('depth_geojson_path', 'geojson', 'Depth layer (GeoJSON)'),
    ):
        artifact = _artifact_from_upload_record(
            upload,
            session_id,
            spec[0],
            artifact_type=spec[1],
            label=spec[2],
        )
        if artifact:
            artifacts.append(artifact)

    payload: Dict[str, Any] = {
        'total': 1,
        'succeeded': 1,
        'failed': 0,
        'session_id': session_id,
        'output_dir': str((output_root / session_id).resolve()),
        'results': [{
            'name': survey_name,
            'success': True,
            'message': 'Recovered from persisted job record.',
            'csv': None,
            'artifacts': artifacts,
        }],
        'area_map_url': '/area-map',
    }
    dashboard = next((a for a in artifacts if a['type'] == 'dashboard'), None)
    if dashboard:
        payload['dashboard_url'] = dashboard['url']
    return payload


def _run_processing_job(
    job_id: str,
    rsd_paths: List[Path],
    csv_paths: List[Path],
    session_dir: Path,
    workflow: str,
    nchunk: int,
    map_formats: Optional[List[str]],
    location: Optional[str],
    output_root: Path,
    jobs: Dict[str, ProcessingJob],
    jobs_lock: threading.Lock,
) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job.status = JobStatus.RUNNING

    try:
        summary = batch_process_uploads(
            rsd_paths,
            csv_paths,
            output_dir=session_dir,
            workflow=workflow,
            nchunk=nchunk,
            map_formats=map_formats,
            location=location,
        )
        payload = _summary_to_payload(summary, session_dir)
        logger.info(format_batch_summary(summary))
        survey_name = location or session_dir.name
        if summary.results:
            survey_name = summary.results[0].input_path.stem
        try:
            record_completed_upload(
                session_id=session_dir.name,
                job_id=job_id,
                survey_name=survey_name,
                location=location,
                workflow=workflow,
                session_dir=session_dir,
                result_payload=payload,
                output_root=output_root,
            )
        except Exception:
            logger.exception('Failed to persist upload to database')
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                job.status = JobStatus.COMPLETED
                job.result = payload
                payload['area_map_url'] = '/area-map' 
    except Exception as exc:
        logger.exception('Batch processing failed for job %s', job_id)
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = str(exc)



def _read_request_body_to_file(rfile, content_length: int, dest: Path) -> None:
    """Stream request body to disk in chunks (avoids one giant memory allocation)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    remaining = content_length
    with open(dest, 'wb') as out:
        while remaining > 0:
            chunk = rfile.read(min(READ_CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError('Upload ended unexpectedly (connection closed)')
            out.write(chunk)
            remaining -= len(chunk)



def _parse_multipart_from_path(
    boundary: str,
    raw_path: Path,
    uploads_root: Path,
) -> Tuple[Dict[str, List[str]], List[Path]]:
    """Parse a multipart upload body saved to disk."""
    return _parse_multipart_form_data(boundary, raw_path.read_bytes(), uploads_root)


def _parse_request_form_data_streaming(
    content_type_header: str,
    rfile,
    content_length: int,
    uploads_root: Path,
) -> Tuple[Dict[str, List[str]], List[Path]]:
    content_type, params = _parse_header_value(content_type_header)

    if content_type == 'application/x-www-form-urlencoded':
        body = bytearray()
        remaining = content_length
        while remaining > 0:
            chunk = rfile.read(min(READ_CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError('Upload ended unexpectedly (connection closed)')
            body.extend(chunk)
            remaining -= len(chunk)
        decoded = bytes(body).decode('utf-8', errors='replace')
        parsed = parse_qs(decoded, keep_blank_values=True)
        return {key: values for key, values in parsed.items()}, []

    if content_type != 'multipart/form-data':
        raise ValueError('Unsupported Content-Type. Expected multipart/form-data upload.')

    boundary = params.get('boundary')
    if not boundary:
        raise ValueError('Missing multipart boundary in Content-Type header.')

    if content_length > WEB_UPLOAD_MAX_BYTES:
        raise ValueError(
            f'Upload is {content_length / (1024 * 1024):.1f} MB; the hosted converter accepts up to '
            f'{WEB_UPLOAD_MAX_BYTES // (1024 * 1024)} MB per request. '
            'Convert locally with: python sonar_cli.py convert yourfile.RSD'
        )
    body = bytearray()
    remaining = content_length
    while remaining > 0:
        chunk = rfile.read(min(READ_CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError('Upload ended unexpectedly (connection closed)')
        body.extend(chunk)
        remaining -= len(chunk)
    return _parse_multipart_form_data(boundary, bytes(body), uploads_root)




def _split_upload_paths(paths: List[Path]) -> Tuple[List[Path], List[Path]]:
    rsd_paths: List[Path] = []
    csv_paths: List[Path] = []
    for item in paths:
        suffix = item.suffix.lower()
        if suffix == '.rsd':
            rsd_paths.append(item)
        elif suffix == '.csv':
            csv_paths.append(item)
    return rsd_paths, csv_paths


_UPLOAD_PAGE_PATH = Path(__file__).with_name('sonar_upload_page.html')
_upload_page_cache: Optional[str] = None


def _upload_page_html(port: int) -> str:
    """Serve the upload UI from sonar_upload_page.html (build id injected)."""
    global _upload_page_cache
    if _upload_page_cache is None:
        _upload_page_cache = _UPLOAD_PAGE_PATH.read_text(encoding='utf-8')
    return _upload_page_cache.replace('__BUILD__', APP_BUILD_ID)


def _guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or 'application/octet-stream'


def _resolve_results_file(output_root: Path, session_id: str, rel_path: str) -> Path:
    if not session_id or '/' in session_id or '\\' in session_id or '..' in session_id:
        raise ValueError('Invalid session id')
    rel = unquote(rel_path).lstrip('/')
    if not rel or '..' in Path(rel).parts:
        raise ValueError('Invalid file path')
    session_dir = (output_root / session_id).resolve()
    file_path = (session_dir / rel).resolve()
    if not str(file_path).startswith(str(session_dir)):
        raise ValueError('Path traversal blocked')
    if file_path.suffix.lower() not in RESULTS_ALLOWED_SUFFIXES:
        raise ValueError('File type not allowed')
    if not file_path.is_file():
        raise ValueError('File not found')
    return file_path


class SonarUploadHandler(BaseHTTPRequestHandler):
    """HTTP handler for RSD upload UI and processing API."""

    uploads_root: Path
    output_root: Path
    jobs: Dict[str, ProcessingJob]
    jobs_lock: threading.Lock
    server_version = 'SonarUpload/1.2'

    def log_message(self, fmt: str, *args) -> None:
        logger.info('%s - %s', self.address_string(), fmt % args)

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path) -> None:
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', _guess_content_type(file_path))
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'private, max-age=3600')
        self.end_headers()
        self.wfile.write(content)

    def _handle_results_file(self, parsed) -> None:
        prefix = '/results/'
        rel = parsed.path[len(prefix):]
        if not rel:
            self._send_json({'error': 'Missing session id'}, HTTPStatus.BAD_REQUEST)
            return
        parts = rel.split('/', 1)
        session_id = parts[0]
        rel_path = parts[1] if len(parts) > 1 else ''
        try:
            file_path = _resolve_results_file(self.output_root, session_id, rel_path)
        except ValueError as exc:
            self._send_json({'error': str(exc)}, HTTPStatus.NOT_FOUND)
            return
        self._send_file(file_path)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            port = self.server.server_address[1]
            self._send_html(_upload_page_html(port))
            return
        if parsed.path.startswith('/results/'):
            self._handle_results_file(parsed)
            return
        if parsed.path == '/api/health':
            self._send_json({'status': 'ok'})
            return
        if parsed.path == '/api/version':
            self._send_json({
                'build': APP_BUILD_ID,
                'server': self.server_version,
                'accepts': ['.rsd', '.csv'],
                'features': ['async_jobs', 'csv_analysis', 'streaming_upload', 'results_download', 'survey_database', 'area_map'],
            })
            return
        if parsed.path.startswith('/api/jobs/'):
            job_id = parsed.path[len('/api/jobs/'):].strip('/')
            if not job_id:
                self._send_json({'error': 'Missing job id'}, HTTPStatus.BAD_REQUEST)
                return
            with self.jobs_lock:
                job = self.jobs.get(job_id)
            if not job:
                persisted = get_upload_by_job_id(job_id)
                if not persisted:
                    self._send_json({'error': 'Job not found'}, HTTPStatus.NOT_FOUND)
                    return
                fallback = _completed_job_payload_from_upload(persisted, self.output_root)
                self._send_json({
                    'job_id': job_id,
                    'status': JobStatus.COMPLETED.value,
                    'file_count': max(1, int(persisted.get('row_count') or 1)),
                    'result': fallback,
                    'recovered': True,
                })
                return
            body: Dict[str, Any] = {
                'job_id': job.id,
                'status': job.status.value,
                'file_count': job.file_count,
            }
            if job.error:
                body['error'] = job.error
            if job.result:
                body['result'] = job.result
            self._send_json(body)
            return
        if parsed.path == '/area-map':
            page = Path(__file__).with_name('area_map_page.html')
            self._send_html(page.read_text(encoding='utf-8'))
            return
        if parsed.path == '/api/surveys':
            self._send_json({'surveys': list_uploads()})
            return
        if parsed.path == '/api/area-map':
            self._send_json(build_area_map_geojson(self.output_root))
            return
        if parsed.path.startswith('/api/surveys/') and parsed.path.endswith('/echogram'):
            upload_id = parsed.path[len('/api/surveys/'): -len('/echogram')].strip('/')
            qs = parse_qs(parsed.query)
            start = int((qs.get('start') or ['0'])[0])
            limit = int((qs.get('limit') or ['1500'])[0])
            self._send_json(load_echogram_segment(self.output_root, upload_id, start, limit))
            return
        self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode('utf-8'))

    def _handle_save_labels(self) -> None:
        try:
            data = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({'error': 'Invalid JSON'}, HTTPStatus.BAD_REQUEST)
            return
        upload_id = data.get('upload_id')
        labels = data.get('labels') or []
        if not upload_id:
            self._send_json({'error': 'upload_id required'}, HTTPStatus.BAD_REQUEST)
            return
        count = save_labels(upload_id, labels)
        self._send_json({'saved': count, 'upload_id': upload_id})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == '/api/process':
                self._handle_process_upload()
            elif path == '/api/labels':
                self._handle_save_labels()
            else:
                self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.exception('Unhandled error in POST %s', path)
            self._send_json({'error': str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_one_request(self) -> None:
        if self.connection is not None:
            self.connection.settimeout(900.0)
        super().handle_one_request()

    def _handle_process_upload(self) -> None:
        expect = self.headers.get('Expect', '')
        if expect.lower() == '100-continue':
            self.send_response_only(HTTPStatus.CONTINUE)
            self.end_headers()

        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0:
            self._send_json({'error': 'Empty request'}, HTTPStatus.BAD_REQUEST)
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(
                {'error': f'Upload too large (max {MAX_UPLOAD_BYTES // (1024**3)} GB)'},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return

        try:
            fields, saved_paths = _parse_request_form_data_streaming(
                self.headers.get('Content-Type', ''),
                self.rfile,
                content_length,
                self.uploads_root,
            )
        except ValueError as exc:
            self._send_json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        workflow = _field_value(fields, 'workflow') or 'convert'
        maps = _field_value(fields, 'maps') or ''
        location = _field_value(fields, 'location') or None
        try:
            nchunk = int(_field_value(fields, 'nchunk') or _field_value(fields, 'stride') or '500')
        except ValueError:
            nchunk = 500

        if not saved_paths:
            self._send_json({'error': 'No .RSD or .CSV files uploaded'}, HTTPStatus.BAD_REQUEST)
            return

        rsd_paths, csv_paths = _split_upload_paths(saved_paths)

        session_dir = self.output_root / uuid.uuid4().hex[:12]
        session_dir.mkdir(parents=True, exist_ok=True)

        map_formats: Optional[List[str]] = None
        if maps == 'all':
            map_formats = ['all']
        elif maps == 'geojson':
            map_formats = ['geojson']

        job_id = uuid.uuid4().hex[:12]
        job = ProcessingJob(id=job_id, file_count=len(saved_paths))
        with self.jobs_lock:
            self.jobs[job_id] = job
            _prune_old_jobs(self.jobs)

        worker = threading.Thread(
            target=_run_processing_job,
            name=f'rsd-job-{job_id}',
            daemon=True,
            kwargs={
                'job_id': job_id,
                'rsd_paths': list(rsd_paths),
                'csv_paths': list(csv_paths),
                'session_dir': session_dir,
                'workflow': workflow,
                'nchunk': nchunk,
                'map_formats': map_formats,
                'location': location,
                'output_root': self.output_root,
                'jobs': self.jobs,
                'jobs_lock': self.jobs_lock,
            },
        )
        worker.start()

        self._send_json(
            {
                'job_id': job_id,
                'status': JobStatus.PENDING.value,
                'file_count': len(saved_paths),
                'message': 'Upload received; processing in background.',
            },
            HTTPStatus.ACCEPTED,
        )


def _field_value(fields: Dict[str, List[str]], name: str) -> Optional[str]:
    values = fields.get(name)
    return values[0] if values else None


def _parse_header_value(value: str) -> Tuple[str, Dict[str, str]]:
    parts = [part.strip() for part in value.split(';') if part.strip()]
    if not parts:
        return '', {}

    main = parts[0].lower()
    params: Dict[str, str] = {}
    for item in parts[1:]:
        if '=' not in item:
            continue
        key, raw_value = item.split('=', 1)
        key = key.strip().lower()
        raw_value = raw_value.strip()
        if raw_value.startswith('"') and raw_value.endswith('"') and len(raw_value) >= 2:
            raw_value = raw_value[1:-1]
        params[key] = raw_value
    return main, params


def _parse_request_form_data(
    content_type_header: str,
    body: bytes,
    uploads_root: Path,
) -> Tuple[Dict[str, List[str]], List[Path]]:
    content_type, params = _parse_header_value(content_type_header)

    if content_type == 'application/x-www-form-urlencoded':
        decoded = body.decode('utf-8', errors='replace')
        parsed = parse_qs(decoded, keep_blank_values=True)
        fields = {key: values for key, values in parsed.items()}
        return fields, []

    if content_type != 'multipart/form-data':
        raise ValueError('Unsupported Content-Type. Expected multipart/form-data upload.')

    boundary = params.get('boundary')
    if not boundary:
        raise ValueError('Missing multipart boundary in Content-Type header.')

    return _parse_multipart_form_data(boundary, body, uploads_root)


def _parse_multipart_form_data(
    boundary: str,
    body: bytes,
    uploads_root: Path,
) -> Tuple[Dict[str, List[str]], List[Path]]:
    uploads_root.mkdir(parents=True, exist_ok=True)
    batch_dir = uploads_root / uuid.uuid4().hex[:12]
    batch_dir.mkdir(parents=True, exist_ok=True)

    fields: Dict[str, List[str]] = {}
    saved: List[Path] = []

    delimiter = f'--{boundary}'.encode('utf-8')
    parts = body.split(delimiter)
    if len(parts) < 3:
        raise ValueError('Malformed multipart body.')

    for part in parts[1:]:
        part = part.lstrip(b'\r\n')
        if not part or part in (b'--', b'--\r\n'):
            continue
        if part.endswith(b'--'):
            part = part[:-2]
        if part.endswith(b'\r\n'):
            part = part[:-2]
        if not part:
            continue

        header_blob, separator, payload = part.partition(b'\r\n\r\n')
        if not separator:
            continue

        part_headers: Dict[str, str] = {}
        for raw_line in header_blob.split(b'\r\n'):
            key, sep, value = raw_line.partition(b':')
            if not sep:
                continue
            part_headers[key.decode('latin-1').strip().lower()] = value.decode('latin-1').strip()

        _, disposition_params = _parse_header_value(part_headers.get('content-disposition', ''))
        field_name = disposition_params.get('name')
        if not field_name:
            continue

        filename = disposition_params.get('filename')
        if filename:
            safe_name = Path(filename).name
            lower_name = safe_name.lower()
            if not (lower_name.endswith('.rsd') or lower_name.endswith('.csv')):
                continue
            dest = batch_dir / safe_name
            with open(dest, 'wb') as out:
                out.write(payload)
            saved.append(dest)
        else:
            fields.setdefault(field_name, []).append(payload.decode('utf-8', errors='replace'))

    return fields, saved


def run_server(
    host: str = '127.0.0.1',
    port: int = 8765,
    uploads_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> None:
    uploads_root = uploads_dir or Path('uploads')
    output_root = output_dir or Path('output')
    uploads_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    SonarUploadHandler.uploads_root = uploads_root
    SonarUploadHandler.output_root = output_root
    SonarUploadHandler.jobs = {}
    SonarUploadHandler.jobs_lock = threading.Lock()

    init_db()
    logger.info('Survey database: %s', get_db_path())

    server = ThreadingHTTPServer((host, port), SonarUploadHandler)
    url = f'http://{host}:{port}/'
    print(f'Sonar RSD upload server running at {url}')
    print(f'  Upload staging: {uploads_root.resolve()}')
    print(f'  Processed output: {output_root.resolve()}')
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
        server.shutdown()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Web UI to upload and bulk-process Garmin Sonar RSD files',
    )
    parser.add_argument('--host', default='127.0.0.1', help='Bind address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8765, help='Port (default: 8765)')
    parser.add_argument(
        '--uploads-dir', type=Path, default=Path('uploads'),
        help='Directory for incoming uploads',
    )
    parser.add_argument(
        '--output-dir', type=Path, default=Path('output'),
        help='Directory for converted outputs',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    run_server(args.host, args.port, args.uploads_dir, args.output_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
