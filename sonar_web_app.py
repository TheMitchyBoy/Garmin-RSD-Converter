#!/usr/bin/env python3
"""
Hostable web application for Garmin Sonar RSD processing.

Upload .RSD recordings in a browser, watch live-style sonar playback, convert
to CSV, run the full analysis pipeline, and download or open generated files.

Uses the Python standard library HTTP server (no Flask/Django required).
"""

from __future__ import annotations

import argparse
import cgi
import json
import logging
import mimetypes
import os
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from batch_processor import batch_convert, batch_pipeline, format_batch_summary
from sonar_playback import generate_playback

logger = logging.getLogger(__name__)

DEFAULT_MAX_UPLOAD_BYTES = int(os.environ.get('SONAR_MAX_UPLOAD_BYTES', 2 * 1024 * 1024 * 1024))


@dataclass
class WebAppConfig:
    """Runtime configuration for the sonar web application."""

    host: str = '0.0.0.0'
    port: int = 8080
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get('SONAR_DATA_DIR', 'data')))
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES

    @property
    def uploads_root(self) -> Path:
        return self.data_dir / 'uploads'

    @property
    def sessions_root(self) -> Path:
        return self.data_dir / 'sessions'


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _app_html(base_path: str = '') -> str:
    prefix = base_path.rstrip('/')
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Garmin Sonar RSD Web App</title>
  <style>
    :root {{
      --bg: #0b1220;
      --panel: #141f33;
      --panel2: #1a2740;
      --text: #e8eef9;
      --muted: #93a4bf;
      --accent: #38bdf8;
      --accent2: #6366f1;
      --ok: #4ade80;
      --err: #f87171;
      --line: #2a3a57;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #1e3a5f 0%, transparent 55%), var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      padding: 1.5rem 1.25rem 1rem;
      border-bottom: 1px solid var(--line);
      background: rgba(11, 18, 32, 0.85);
      backdrop-filter: blur(8px);
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    header h1 {{ margin: 0; font-size: 1.45rem; }}
    header p {{ margin: 0.35rem 0 0; color: var(--muted); font-size: 0.95rem; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 1.25rem 1.25rem 3rem; }}
    .tabs {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
      margin-bottom: 1rem;
    }}
    .tab {{
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 0.55rem 0.95rem;
      border-radius: 999px;
      cursor: pointer;
      font-size: 0.92rem;
    }}
    .tab.active {{
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      color: #061018;
      border-color: transparent;
      font-weight: 700;
    }}
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 1.1rem;
      margin-bottom: 1rem;
    }}
    .dropzone {{
      border: 2px dashed #41577a;
      border-radius: 12px;
      padding: 2rem 1rem;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s;
      background: var(--panel2);
    }}
    .dropzone.dragover {{ border-color: var(--accent); background: #1b2a45; }}
    .dropzone strong {{ color: var(--accent); }}
    input[type=file] {{ display: none; }}
    label {{ display: block; margin-bottom: 0.75rem; font-size: 0.92rem; }}
    select, input[type=text], input[type=number] {{
      width: 100%;
      margin-top: 0.25rem;
      padding: 0.5rem 0.65rem;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #0b1220;
      color: var(--text);
    }}
    button.primary {{
      width: 100%;
      margin-top: 0.5rem;
      padding: 0.75rem 1rem;
      font-size: 1rem;
      font-weight: 700;
      border: none;
      border-radius: 10px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      color: #061018;
      cursor: pointer;
    }}
    button.primary:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .file-list {{
      margin-top: 0.75rem;
      font-size: 0.85rem;
      color: var(--muted);
      text-align: left;
      max-height: 120px;
      overflow-y: auto;
    }}
    #status {{
      margin-top: 1rem;
      white-space: pre-wrap;
      font-size: 0.9rem;
      background: var(--panel2);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 1rem;
      min-height: 3rem;
    }}
    .links {{ margin-top: 0.75rem; }}
    .links a {{
      display: inline-block;
      margin: 0.25rem 0.5rem 0.25rem 0;
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    .links a:hover {{ text-decoration: underline; }}
    .ok {{ color: var(--ok); }}
    .fail {{ color: var(--err); }}
    .hint {{ color: var(--muted); font-size: 0.88rem; margin-top: 0.5rem; }}
    code {{ background: #0b1220; padding: 0.1rem 0.35rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>Garmin Sonar RSD Web App</h1>
    <p>Upload recordings, watch the sonar feed, convert to CSV, and run survey analysis — all in your browser.</p>
  </header>
  <main>
    <div class="tabs">
      <button type="button" class="tab active" data-tab="playback">Watch sonar feed</button>
      <button type="button" class="tab" data-tab="convert">Convert &amp; maps</button>
      <button type="button" class="tab" data-tab="pipeline">Full pipeline</button>
    </div>

    <section class="panel active" id="panel-playback">
      <div class="card">
        <p class="hint">Rebuilds the scrolling echogram from your recording — like the live Garmin display. No ffmpeg required (HTML player).</p>
        <div class="dropzone" data-drop="playback">
          <p><strong>Drop a .RSD file here</strong> or click to browse</p>
          <input type="file" accept=".rsd,.RSD" data-input="playback">
          <div class="file-list" data-list="playback"></div>
        </div>
        <label>Max pings (optional — leave blank for full recording)
          <input type="number" id="playbackMaxPings" min="100" step="100" placeholder="e.g. 5000 for quick preview">
        </label>
        <label>Scrolling window (pings on screen)
          <input type="number" id="playbackWindow" value="400" min="50" step="50">
        </label>
        <button type="button" class="primary" id="btnPlayback" disabled>Generate sonar playback</button>
      </div>
    </section>

    <section class="panel" id="panel-convert">
      <div class="card">
        <div class="dropzone" data-drop="convert">
          <p><strong>Drop .RSD files here</strong> (multiple allowed)</p>
          <input type="file" accept=".rsd,.RSD" multiple data-input="convert">
          <div class="file-list" data-list="convert"></div>
        </div>
        <label>Map exports
          <select id="convertMaps">
            <option value="">CSV only</option>
            <option value="all">All formats</option>
            <option value="geojson">GeoJSON track</option>
          </select>
        </label>
        <button type="button" class="primary" id="btnConvert" disabled>Convert to CSV</button>
      </div>
    </section>

    <section class="panel" id="panel-pipeline">
      <div class="card">
        <div class="dropzone" data-drop="pipeline">
          <p><strong>Drop .RSD files here</strong> for full analysis</p>
          <input type="file" accept=".rsd,.RSD" multiple data-input="pipeline">
          <div class="file-list" data-list="pipeline"></div>
        </div>
        <label>Survey location name
          <input type="text" id="pipelineLocation" placeholder="Lake Survey">
        </label>
        <button type="button" class="primary" id="btnPipeline" disabled>Run full pipeline</button>
        <p class="hint">CSV, maps, heatmaps, fish detection, and HTML dashboard.</p>
      </div>
    </section>

    <div class="card">
      <label>PINGVerter chunk size
        <input type="number" id="nchunk" value="500" min="0" step="50">
      </label>
    </div>

    <div id="status">Ready.</div>
  </main>
  <script>
    const API = '{prefix}';
    const filesByTab = {{ playback: [], convert: [], pipeline: [] }};

    document.querySelectorAll('.tab').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
      }});
    }});

    function refreshList(tab) {{
      const list = document.querySelector('[data-list="' + tab + '"]');
      const btnId = tab === 'playback' ? 'btnPlayback' : tab === 'convert' ? 'btnConvert' : 'btnPipeline';
      document.getElementById(btnId).disabled = filesByTab[tab].length === 0;
      if (!filesByTab[tab].length) {{ list.textContent = ''; return; }}
      list.innerHTML = filesByTab[tab].map(f =>
        `<div>${{f.name}} (${{(f.size/1024/1024).toFixed(1)}} MB)</div>`
      ).join('');
    }}

    function setupDrop(tab) {{
      const dz = document.querySelector('[data-drop="' + tab + '"]');
      const input = document.querySelector('[data-input="' + tab + '"]');
      dz.addEventListener('click', () => input.click());
      input.addEventListener('change', e => addFiles(tab, e.target.files));
      ['dragenter','dragover'].forEach(evt => dz.addEventListener(evt, e => {{
        e.preventDefault(); dz.classList.add('dragover');
      }}));
      ['dragleave','drop'].forEach(evt => dz.addEventListener(evt, e => {{
        e.preventDefault(); dz.classList.remove('dragover');
      }}));
      dz.addEventListener('drop', e => addFiles(tab, e.dataTransfer.files));
    }}

    function addFiles(tab, fileListLike) {{
      const incoming = Array.from(fileListLike).filter(f => /\\.rsd$/i.test(f.name));
      if (!incoming.length) {{
        document.getElementById('status').textContent = 'Please select .RSD files only.';
        return;
      }}
      if (tab === 'playback') {{
        filesByTab.playback = [incoming[0]];
      }} else {{
        const names = new Set(filesByTab[tab].map(f => f.name));
        incoming.forEach(f => {{ if (!names.has(f.name)) filesByTab[tab].push(f); }});
      }}
      refreshList(tab);
    }}

    ['playback','convert','pipeline'].forEach(setupDrop);

    function renderLinks(links) {{
      if (!links || !links.length) return '';
      return '<div class="links">' + links.map(l =>
        `<a href="${{l.url}}" target="_blank" rel="noopener">${{l.label}}</a>`
      ).join('') + '</div>';
    }}

    async function postForm(url, form) {{
      const res = await fetch(API + url, {{ method: 'POST', body: form }});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Request failed');
      return data;
    }}

    document.getElementById('btnPlayback').addEventListener('click', async () => {{
      const status = document.getElementById('status');
      status.textContent = 'Generating sonar playback… large recordings may take a minute.';
      const form = new FormData();
      form.append('files', filesByTab.playback[0]);
      form.append('window', document.getElementById('playbackWindow').value);
      form.append('nchunk', document.getElementById('nchunk').value);
      const maxP = document.getElementById('playbackMaxPings').value;
      if (maxP) form.append('max_pings', maxP);
      try {{
        const data = await postForm('/api/playback', form);
        status.innerHTML = `<span class="ok">✓ Playback ready</span>` + renderLinks(data.links);
        if (data.links && data.links[0]) window.open(data.links[0].url, '_blank');
      }} catch (err) {{
        status.innerHTML = `<span class="fail">Error: ${{err.message}}</span>`;
      }}
    }});

    document.getElementById('btnConvert').addEventListener('click', async () => {{
      await runProcess('convert');
    }});

    document.getElementById('btnPipeline').addEventListener('click', async () => {{
      await runProcess('pipeline');
    }});

    async function runProcess(workflow) {{
      const status = document.getElementById('status');
      status.textContent = 'Processing… this may take several minutes for large surveys.';
      const form = new FormData();
      filesByTab[workflow].forEach(f => form.append('files', f));
      form.append('workflow', workflow);
      form.append('maps', workflow === 'convert' ? document.getElementById('convertMaps').value : '');
      form.append('location', document.getElementById('pipelineLocation').value);
      form.append('nchunk', document.getElementById('nchunk').value);
      try {{
        const data = await postForm('/api/process', form);
        let html = `<span class="ok">Done: ${{data.succeeded}}/${{data.total}} succeeded</span><br>`;
        (data.results || []).forEach(r => {{
          html += `<div class="${{r.success ? 'ok' : 'fail'}}">${{r.success ? '✓' : '✗'}} ${{r.name}}: ${{r.message}}</div>`;
          html += renderLinks(r.links);
        }});
        status.innerHTML = html;
      }} catch (err) {{
        status.innerHTML = `<span class="fail">Error: ${{err.message}}</span>`;
      }}
    }}
  </script>
</body>
</html>'''


def _field_value(form: cgi.FieldStorage, name: str) -> Optional[str]:
    if name not in form:
        return None
    field = form[name]
    if isinstance(field, list):
        return field[0].value if field else None
    return field.value


def _save_uploaded_files(form: cgi.FieldStorage, dest_dir: Path) -> List[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
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
        dest = dest_dir / name
        with open(dest, 'wb') as out:
            shutil.copyfileobj(field.file, out)
        saved.append(dest)
    return saved


def _safe_session_path(sessions_root: Path, session_id: str, rel_path: str) -> Optional[Path]:
    if not session_id or '/' in session_id or '\\' in session_id or '..' in session_id:
        return None
    session_dir = (sessions_root / session_id).resolve()
    if not session_dir.is_dir():
        return None
    target = (session_dir / rel_path).resolve()
    try:
        target.relative_to(session_dir)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def _file_link(session_id: str, path: Path, session_dir: Path, label: Optional[str] = None) -> Dict[str, str]:
    rel = path.relative_to(session_dir).as_posix()
    return {
        'label': label or path.name,
        'url': f'/files/{session_id}/{rel}',
        'name': path.name,
        'kind': path.suffix.lower().lstrip('.') or 'file',
    }


def _collect_output_links(session_id: str, session_dir: Path, outputs: List[Path]) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    seen = set()
    for path in outputs:
        path = Path(path)
        if not path.exists() or not path.is_file():
            continue
        try:
            path.relative_to(session_dir)
        except ValueError:
            continue
        key = path.name
        if key in seen:
            continue
        seen.add(key)
        label = path.name
        suffix = path.suffix.lower()
        if suffix == '.html' and 'dashboard' in path.name.lower():
            label = 'Open dashboard'
        elif suffix == '.html' and 'playback' in path.name.lower():
            label = 'Watch sonar playback'
        elif suffix == '.csv':
            label = 'Download CSV'
        elif suffix == '.geojson':
            label = 'GeoJSON map'
        links.append(_file_link(session_id, path, session_dir, label))
    return links


def _write_manifest(session_dir: Path, session_id: str, payload: Dict[str, Any]) -> None:
    manifest_path = session_dir / 'manifest.json'
    existing: Dict[str, Any] = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            existing = {}
    jobs = existing.get('jobs', [])
    jobs.append(payload)
    manifest = {
        'session_id': session_id,
        'created': existing.get('created') or _utc_now_iso(),
        'updated': _utc_now_iso(),
        'jobs': jobs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')


class SonarWebHandler(BaseHTTPRequestHandler):
    """HTTP handler for the hostable sonar web application."""

    config: WebAppConfig
    base_path: str = ''
    server_version = 'SonarWeb/1.0'

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

    def _send_file(self, path: Path) -> None:
        mime, _ = mimetypes.guess_type(str(path))
        content_type = mime or 'application/octet-stream'
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Disposition', f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _parse_multipart(self) -> Tuple[Optional[cgi.FieldStorage], Optional[str]]:
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0:
            return None, 'Empty request'
        if content_length > self.config.max_upload_bytes:
            max_gb = self.config.max_upload_bytes / (1024 ** 3)
            return None, f'Upload too large (max {max_gb:.1f} GB)'
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
        return form, None

    def _new_session_dir(self) -> Tuple[str, Path]:
        session_id = uuid.uuid4().hex[:12]
        session_dir = self.config.sessions_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_id, session_dir

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if self.base_path and path.startswith(self.base_path):
            path = path[len(self.base_path):] or '/'

        if path in ('/', '/index.html'):
            self._send_html(_app_html(self.base_path))
            return

        if path == '/api/health':
            self._send_json({'status': 'ok', 'service': 'sonar-web'})
            return

        if path.startswith('/files/'):
            parts = path[len('/files/'):].split('/', 1)
            if len(parts) != 2:
                self._send_json({'error': 'Invalid file path'}, HTTPStatus.BAD_REQUEST)
                return
            session_id, rel_path = parts[0], unquote(parts[1])
            file_path = _safe_session_path(self.config.sessions_root, session_id, rel_path)
            if file_path is None:
                self._send_json({'error': 'File not found'}, HTTPStatus.NOT_FOUND)
                return
            self._send_file(file_path)
            return

        if path.startswith('/api/session/'):
            session_id = path.split('/')[-1]
            session_dir = self.config.sessions_root / session_id
            manifest = session_dir / 'manifest.json'
            if not manifest.is_file():
                self._send_json({'error': 'Session not found'}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(json.loads(manifest.read_text(encoding='utf-8')))
            return

        self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if self.base_path and path.startswith(self.base_path):
            path = path[len(self.base_path):] or '/'

        form, err = self._parse_multipart()
        if err:
            self._send_json({'error': err}, HTTPStatus.BAD_REQUEST)
            return
        assert form is not None

        if path == '/api/playback':
            self._handle_playback(form)
            return
        if path == '/api/process':
            self._handle_process(form)
            return

        self._send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

    def _handle_playback(self, form: cgi.FieldStorage) -> None:
        session_id, session_dir = self._new_session_dir()
        incoming_dir = session_dir / 'incoming'
        saved_paths = _save_uploaded_files(form, incoming_dir)
        if not saved_paths:
            self._send_json({'error': 'No .RSD file uploaded'}, HTTPStatus.BAD_REQUEST)
            return

        input_file = saved_paths[0]
        try:
            nchunk = int(_field_value(form, 'nchunk') or '500')
        except ValueError:
            nchunk = 500
        try:
            window_pings = int(_field_value(form, 'window') or '400')
        except ValueError:
            window_pings = 400
        max_pings_raw = _field_value(form, 'max_pings')
        max_pings = int(max_pings_raw) if max_pings_raw else None

        out_name = f'{input_file.stem}_playback.html'
        output_file = session_dir / out_name

        try:
            generate_playback(
                input_file,
                output_file=output_file,
                fmt='html',
                nchunk=nchunk,
                window_pings=window_pings,
                max_pings=max_pings,
            )
        except Exception as exc:
            logger.exception('Playback generation failed')
            self._send_json({'error': str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        links = _collect_output_links(session_id, session_dir, [output_file])
        _write_manifest(session_dir, session_id, {
            'type': 'playback',
            'input': input_file.name,
            'links': links,
        })
        self._send_json({
            'session_id': session_id,
            'links': links,
        })

    def _handle_process(self, form: cgi.FieldStorage) -> None:
        workflow = _field_value(form, 'workflow') or 'convert'
        maps = _field_value(form, 'maps') or ''
        location = _field_value(form, 'location') or None
        try:
            nchunk = int(_field_value(form, 'nchunk') or '500')
        except ValueError:
            nchunk = 500

        session_id, session_dir = self._new_session_dir()
        incoming_dir = session_dir / 'incoming'
        saved_paths = _save_uploaded_files(form, incoming_dir)
        if not saved_paths:
            self._send_json({'error': 'No .RSD files uploaded'}, HTTPStatus.BAD_REQUEST)
            return

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

        results_payload = []
        for item in summary.results:
            links = _collect_output_links(session_id, session_dir, item.outputs)
            results_payload.append({
                'name': item.input_path.name,
                'success': item.success,
                'message': item.message,
                'links': links,
            })

        _write_manifest(session_dir, session_id, {
            'type': workflow,
            'results': results_payload,
        })

        self._send_json({
            'session_id': session_id,
            'total': summary.total,
            'succeeded': summary.succeeded,
            'failed': summary.failed,
            'results': results_payload,
        })


def run_web_app(
    host: Optional[str] = None,
    port: Optional[int] = None,
    data_dir: Optional[Path] = None,
    base_path: str = '',
) -> None:
    """Start the sonar web application (blocks until interrupted)."""
    config = WebAppConfig(
        host=host or os.environ.get('SONAR_HOST', '0.0.0.0'),
        port=int(port or os.environ.get('SONAR_PORT', '8080')),
        data_dir=Path(data_dir or os.environ.get('SONAR_DATA_DIR', 'data')),
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_root.mkdir(parents=True, exist_ok=True)
    config.sessions_root.mkdir(parents=True, exist_ok=True)

    SonarWebHandler.config = config
    SonarWebHandler.base_path = base_path.rstrip('/')

    server = ThreadingHTTPServer((config.host, config.port), SonarWebHandler)
    display_host = config.host if config.host != '0.0.0.0' else 'localhost'
    url = f'http://{display_host}:{config.port}{SonarWebHandler.base_path}/'
    print(f'Garmin Sonar web app running at {url}')
    print(f'  Data directory: {config.data_dir.resolve()}')
    print(f'  Max upload: {config.max_upload_bytes / (1024**3):.1f} GB')
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
        server.shutdown()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Hostable web app for Garmin Sonar RSD upload, playback, and analysis',
    )
    parser.add_argument(
        '--host', default=os.environ.get('SONAR_HOST', '0.0.0.0'),
        help='Bind address (default: 0.0.0.0, or SONAR_HOST env)',
    )
    parser.add_argument(
        '--port', type=int, default=int(os.environ.get('SONAR_PORT', '8080')),
        help='Port (default: 8080, or SONAR_PORT env)',
    )
    parser.add_argument(
        '--data-dir', type=Path, default=Path(os.environ.get('SONAR_DATA_DIR', 'data')),
        help='Data root for uploads and session outputs (default: ./data)',
    )
    parser.add_argument(
        '--base-path', default=os.environ.get('SONAR_BASE_PATH', ''),
        help='URL prefix when served behind a reverse proxy subpath',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    run_web_app(args.host, args.port, args.data_dir, args.base_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
