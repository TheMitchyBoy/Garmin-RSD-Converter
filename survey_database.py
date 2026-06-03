#!/usr/bin/env python3
"""SQLite persistence for survey uploads and training labels."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_db_lock = threading.Lock()
_connection: Optional[sqlite3.Connection] = None


def get_db_path() -> Path:
    raw = os.environ.get('SURVEY_DB_PATH', 'data/surveys.db')
    path = Path(raw).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        conn = sqlite3.connect(str(get_db_path()), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _connection = conn
    return _connection


def init_db() -> None:
    with _db_lock:
        conn = _connect()
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                survey_name TEXT NOT NULL,
                location TEXT,
                workflow TEXT,
                created_at REAL NOT NULL,
                min_lat REAL,
                max_lat REAL,
                min_lon REAL,
                max_lon REAL,
                csv_path TEXT,
                dashboard_path TEXT,
                fish_geojson_path TEXT,
                depth_geojson_path TEXT,
                row_count INTEGER DEFAULT 0,
                fish_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed'
            );
            CREATE INDEX IF NOT EXISTS idx_uploads_created ON uploads(created_at DESC);
            CREATE TABLE IF NOT EXISTS labels (
                id TEXT PRIMARY KEY,
                upload_id TEXT NOT NULL,
                species TEXT NOT NULL,
                size TEXT,
                frame INTEGER,
                time_s REAL,
                latitude REAL,
                longitude REAL,
                depth_m REAL,
                intensity REAL,
                notes TEXT,
                source TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (upload_id) REFERENCES uploads(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_labels_upload ON labels(upload_id);
            '''
        )
        conn.commit()


def _bounds_from_pings(pings: List[Dict[str, Any]]) -> Tuple[Optional[float], ...]:
    lats = [p['lat'] for p in pings if p.get('lat') is not None]
    lons = [p['lon'] for p in pings if p.get('lon') is not None]
    if not lats or not lons:
        return None, None, None, None
    return min(lats), max(lats), min(lons), max(lons)


def record_completed_upload(
    *,
    session_id: str,
    job_id: str,
    survey_name: str,
    location: Optional[str],
    workflow: str,
    session_dir: Path,
    result_payload: Dict[str, Any],
    output_root: Path,
) -> None:
    """Persist upload metadata and artifact paths after a job finishes."""
    from survey_viz_data import build_echogram_pings, load_csv_track_geojson

    init_db()
    session_dir = session_dir.resolve()
    output_root = output_root.resolve()

    csv_path: Optional[Path] = None
    dashboard_path: Optional[Path] = None
    fish_path: Optional[Path] = None
    depth_path: Optional[Path] = None
    row_count = 0
    fish_count = 0

    for entry in result_payload.get('results', []):
        if entry.get('csv'):
            candidate = Path(entry['csv'])
            if not candidate.is_file():
                candidate = session_dir / Path(entry['csv']).name
            if candidate.is_file():
                csv_path = candidate
        for artifact in entry.get('artifacts', []):
            rel = artifact.get('path', '')
            full = session_dir / rel
            if not full.is_file():
                continue
            atype = artifact.get('type')
            if atype == 'dashboard':
                dashboard_path = full
            elif atype == 'geojson' and 'fish' in full.name:
                fish_path = full
            elif atype == 'geojson' and 'depth' in full.name.lower():
                depth_path = full

    if csv_path is None:
        for path in session_dir.glob('*.csv'):
            csv_path = path
            break

    if fish_path is None:
        for path in session_dir.glob('*_fish_detections.geojson'):
            fish_path = path
            break

    if depth_path is None:
        for path in session_dir.glob('*_depth*.geojson'):
            depth_path = path
            break

    min_lat = max_lat = min_lon = max_lon = None
    if csv_path and csv_path.is_file():
        track = load_csv_track_geojson(csv_path)
        pings = track.get('pings', [])
        row_count = len(pings)
        min_lat, max_lat, min_lon, max_lon = _bounds_from_pings(pings)

    if fish_path and fish_path.is_file():
        try:
            with open(fish_path, encoding='utf-8') as handle:
                fish_count = len(json.load(handle).get('features', []))
        except (OSError, json.JSONDecodeError):
            fish_count = 0

    def _rel(path: Optional[Path]) -> Optional[str]:
        if path is None or not path.is_file():
            return None
        try:
            return str(path.relative_to(output_root))
        except ValueError:
            return str(path)

    with _db_lock:
        conn = _connect()
        conn.execute(
            '''
            INSERT OR REPLACE INTO uploads (
                id, job_id, survey_name, location, workflow, created_at,
                min_lat, max_lat, min_lon, max_lon,
                csv_path, dashboard_path, fish_geojson_path, depth_geojson_path,
                row_count, fish_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                session_id,
                job_id,
                survey_name,
                location or survey_name,
                workflow,
                time.time(),
                min_lat,
                max_lat,
                min_lon,
                max_lon,
                _rel(csv_path),
                _rel(dashboard_path),
                _rel(fish_path),
                _rel(depth_path),
                row_count,
                fish_count,
                'completed',
            ),
        )
        conn.commit()
    logger.info('Recorded upload %s in survey database (%s rows, %s fish)', session_id, row_count, fish_count)


def list_uploads(limit: int = 200) -> List[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            '''
            SELECT id, job_id, survey_name, location, workflow, created_at,
                   min_lat, max_lat, min_lon, max_lon,
                   row_count, fish_count, dashboard_path, csv_path, fish_geojson_path, status
            FROM uploads
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_upload(upload_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = _connect()
        row = conn.execute('SELECT * FROM uploads WHERE id = ?', (upload_id,)).fetchone()
    return dict(row) if row else None


def get_upload_by_job_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent upload record for a background job id."""
    init_db()
    with _db_lock:
        conn = _connect()
        row = conn.execute(
            '''
            SELECT * FROM uploads
            WHERE job_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            ''',
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def save_labels(upload_id: str, labels: List[Dict[str, Any]]) -> int:
    init_db()
    now = time.time()
    saved = 0
    with _db_lock:
        conn = _connect()
        for label in labels:
            label_id = label.get('id') or f'lbl_{uuid.uuid4().hex[:12]}'
            conn.execute(
                '''
                INSERT OR REPLACE INTO labels (
                    id, upload_id, species, size, frame, time_s,
                    latitude, longitude, depth_m, intensity, notes, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    label_id,
                    upload_id,
                    label.get('species', 'unknown'),
                    label.get('size'),
                    label.get('frame'),
                    label.get('time_s'),
                    label.get('latitude'),
                    label.get('longitude'),
                    label.get('depth_m'),
                    label.get('intensity'),
                    label.get('notes', ''),
                    label.get('source', 'user'),
                    now,
                ),
            )
            saved += 1
        conn.commit()
    return saved


def list_labels(upload_id: Optional[str] = None) -> List[Dict[str, Any]]:
    init_db()
    with _db_lock:
        conn = _connect()
        if upload_id:
            rows = conn.execute(
                'SELECT * FROM labels WHERE upload_id = ? ORDER BY created_at DESC',
                (upload_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM labels ORDER BY created_at DESC LIMIT 5000',
            ).fetchall()
    return [dict(row) for row in rows]
