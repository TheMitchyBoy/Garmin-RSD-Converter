#!/usr/bin/env python3
"""
Local web UI for uploading and bulk-processing Garmin Sonar RSD files.

Uses only the Python standard library (no pip dependencies).
"""

from __future__ import annotations

import argparse
import cgi
import json
import logging
import shutil
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from batch_processor import batch_convert, batch_pipeline, format_batch_summary

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB per request


def _upload_page_html(port: int) -> str:
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Garmin Sonar RSD Upload</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --ok: #4ade80;
      --err: #f87171;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 720px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    h1 {{ font-size: 1.6rem; margin: 0 0 0.35rem; }}
    p.lead {{ color: var(--muted); margin: 0 0 1.5rem; }}
    .dropzone {{
      border: 2px dashed #475569;
      border-radius: 12px;
      padding: 2.5rem 1rem;
      text-align: center;
      background: var(--card);
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s;
    }}
    .dropzone.dragover {{
      border-color: var(--accent);
      background: #243044;
    }}
    .dropzone strong {{ color: var(--accent); }}
    input[type=file] {{ display: none; }}
    .options {{
      margin-top: 1.25rem;
      padding: 1rem;
      background: var(--card);
      border-radius: 12px;
    }}
    label {{ display: block; margin-bottom: 0.75rem; font-size: 0.95rem; }}
    select, input[type=text], input[type=number] {{
      width: 100%;
      margin-top: 0.25rem;
      padding: 0.5rem 0.65rem;
      border-radius: 8px;
      border: 1px solid #475569;
      background: #0f172a;
      color: var(--text);
    }}
    button {{
      margin-top: 1rem;
      width: 100%;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      font-weight: 600;
      border: none;
      border-radius: 10px;
      background: var(--accent);
      color: #0f172a;
      cursor: pointer;
    }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    #status {{ margin-top: 1.25rem; white-space: pre-wrap; font-size: 0.9rem; }}
    .file-list {{
      margin-top: 0.75rem;
      font-size: 0.85rem;
      color: var(--muted);
      text-align: left;
      max-height: 140px;
      overflow-y: auto;
    }}
    .result-item {{ margin: 0.35rem 0; }}
    .ok {{ color: var(--ok); }}
    .fail {{ color: var(--err); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Garmin Sonar RSD Upload</h1>
    <p class="lead">Drop one or many <code>.RSD</code> files to convert or run the full analysis pipeline.</p>

    <div class="dropzone" id="dropzone">
      <p><strong>Click or drag files here</strong></p>
      <p>Supports multiple Garmin Sonar RSD recordings</p>
      <input type="file" id="fileInput" accept=".rsd,.RSD" multiple>
      <div class="file-list" id="fileList"></div>
    </div>

    <div class="options">
      <label>
        Workflow
        <select id="workflow">
          <option value="convert">Convert to CSV (+ optional maps)</option>
          <option value="pipeline">Full pipeline (maps, heatmaps, fish, dashboard)</option>
        </select>
      </label>
      <label>
        Map exports (convert only)
        <select id="maps">
          <option value="">CSV only</option>
          <option value="all">All map formats (PLY, GeoJSON, KML, GPX)</option>
          <option value="geojson">GeoJSON only</option>
        </select>
      </label>
      <label>
        Location name (pipeline)
        <input type="text" id="location" placeholder="Uses file name if empty">
      </label>
      <label>
        PINGVerter chunk size
        <input type="number" id="nchunk" value="500" min="0" step="50">
      </label>
    </div>

    <button type="button" id="submitBtn" disabled>Upload and process</button>
    <div id="status"></div>
  </div>
  <script>
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const fileList = document.getElementById('fileList');
    const submitBtn = document.getElementById('submitBtn');
    const statusEl = document.getElementById('status');
    let selectedFiles = [];

    function refreshFileList() {{
      submitBtn.disabled = selectedFiles.length === 0;
      if (!selectedFiles.length) {{
        fileList.textContent = '';
        return;
      }}
      fileList.innerHTML = selectedFiles.map(f =>
        `<div>${{f.name}} (${{(f.size / 1024 / 1024).toFixed(1)}} MB)</div>`
      ).join('');
    }}

    function addFiles(fileListLike) {{
      const incoming = Array.from(fileListLike).filter(f =>
        /\\.rsd$/i.test(f.name)
      );
      if (!incoming.length) {{
        statusEl.textContent = 'Please select .RSD files only.';
        return;
      }}
      const names = new Set(selectedFiles.map(f => f.name));
      incoming.forEach(f => {{
        if (!names.has(f.name)) selectedFiles.push(f);
      }});
      refreshFileList();
    }}

    dropzone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', e => addFiles(e.target.files));

    ['dragenter', 'dragover'].forEach(evt => {{
      dropzone.addEventListener(evt, e => {{
        e.preventDefault();
        dropzone.classList.add('dragover');
      }});
    }});
    ['dragleave', 'drop'].forEach(evt => {{
      dropzone.addEventListener(evt, e => {{
        e.preventDefault();
        dropzone.classList.remove('dragover');
      }});
    }});
    dropzone.addEventListener('drop', e => addFiles(e.dataTransfer.files));

    submitBtn.addEventListener('click', async () => {{
      if (!selectedFiles.length) return;
      submitBtn.disabled = true;
      statusEl.textContent = 'Uploading and processing… this may take a while for large surveys.';

      const form = new FormData();
      selectedFiles.forEach(f => form.append('files', f));
      form.append('workflow', document.getElementById('workflow').value);
      form.append('maps', document.getElementById('maps').value);
      form.append('location', document.getElementById('location').value);
      form.append('nchunk', document.getElementById('nchunk').value);

      try {{
        const res = await fetch('/api/process', {{ method: 'POST', body: form }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Processing failed');
        let html = `Done: ${{data.succeeded}}/${{data.total}} succeeded\\n`;
        html += `Output folder: ${{data.output_dir}}\\n\\n`;
        (data.results || []).forEach(r => {{
          const cls = r.success ? 'ok' : 'fail';
          html += `<div class="result-item ${{cls}}">${{r.success ? '✓' : '✗'}} ${{r.name}}: ${{r.message}}</div>`;
          if (r.csv) html += `<div class="result-item">   → ${{r.csv}}</div>`;
        }});
        statusEl.innerHTML = html;
      }} catch (err) {{
        statusEl.textContent = 'Error: ' + err.message;
      }} finally {{
        submitBtn.disabled = selectedFiles.length === 0;
      }}
    }});
  </script>
</body>
</html>'''


class SonarUploadHandler(BaseHTTPRequestHandler):
    """HTTP handler for RSD upload UI and processing API."""

    uploads_root: Path
    output_root: Path
    server_version = 'SonarUpload/1.0'

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
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            port = self.server.server_address[1]
            self._send_html(_upload_page_html(port))
            return
        if parsed.path == '/api/health':
            self._send_json({'status': 'ok'})
            return
        self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlparse(self.path).path != '/api/process':
            self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
            return

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

        environ = {
            'REQUEST_METHOD': 'POST',
            'CONTENT_TYPE': self.headers.get('Content-Type', ''),
            'CONTENT_LENGTH': str(content_length),
        }
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ=environ,
            keep_blank_values=True,
        )

        workflow = _field_value(form, 'workflow') or 'convert'
        maps = _field_value(form, 'maps') or ''
        location = _field_value(form, 'location') or None
        try:
            nchunk = int(_field_value(form, 'nchunk') or _field_value(form, 'stride') or '500')
        except ValueError:
            nchunk = 500

        saved_paths = _save_uploaded_files(form, self.uploads_root)
        if not saved_paths:
            self._send_json({'error': 'No .RSD files uploaded'}, HTTPStatus.BAD_REQUEST)
            return

        session_dir = self.output_root / uuid.uuid4().hex[:12]
        session_dir.mkdir(parents=True, exist_ok=True)

        map_formats: Optional[List[str]] = None
        if maps == 'all':
            map_formats = ['all']
        elif maps == 'geojson':
            map_formats = ['geojson']

        try:
            if workflow == 'pipeline':
                summary = batch_pipeline(
                    saved_paths,
                    output_dir=session_dir,
                    nchunk=nchunk,
                    location=location,
                )
            else:
                summary = batch_convert(
                    saved_paths,
                    output_dir=session_dir,
                    nchunk=nchunk,
                    map_formats=map_formats,
                )
        except Exception as exc:
            logger.exception('Batch processing failed')
            self._send_json({'error': str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        logger.info(format_batch_summary(summary))

        self._send_json({
            'total': summary.total,
            'succeeded': summary.succeeded,
            'failed': summary.failed,
            'output_dir': str(session_dir.resolve()),
            'results': [
                {
                    'name': item.input_path.name,
                    'success': item.success,
                    'message': item.message,
                    'csv': str(item.csv_path) if item.csv_path else None,
                }
                for item in summary.results
            ],
        })


def _field_value(form: cgi.FieldStorage, name: str) -> Optional[str]:
    if name not in form:
        return None
    field = form[name]
    if isinstance(field, list):
        return field[0].value if field else None
    return field.value


def _save_uploaded_files(form: cgi.FieldStorage, uploads_root: Path) -> List[Path]:
    uploads_root.mkdir(parents=True, exist_ok=True)
    batch_dir = uploads_root / uuid.uuid4().hex[:12]
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Path] = []
    file_fields = form['files'] if 'files' in form else []
    if not isinstance(file_fields, list):
        file_fields = [file_fields]

    for field in file_fields:
        if not getattr(field, 'filename', None):
            continue
        name = Path(field.filename).name
        if not name.lower().endswith('.rsd'):
            continue
        dest = batch_dir / name
        with open(dest, 'wb') as out:
            shutil.copyfileobj(field.file, out)
        saved.append(dest)

    return saved


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
