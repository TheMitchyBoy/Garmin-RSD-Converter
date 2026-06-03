#!/usr/bin/env python3
"""Build merged area-map GeoJSON from all persisted surveys."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from survey_database import get_upload, list_uploads

logger = logging.getLogger(__name__)

MAX_FISH_PER_SURVEY = 800
MAX_TRACK_POINTS_PER_SURVEY = 2000


def _resolve_path(output_root: Path, relpath: Optional[str]) -> Optional[Path]:
    if not relpath:
        return None
    path = (output_root / relpath).resolve()
    if path.is_file():
        return path
    return None


def _subsample(features: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if len(features) <= limit:
        return features
    step = max(1, len(features) // limit)
    return [features[i] for i in range(0, len(features), step)][:limit]


def build_area_map_geojson(output_root: Path) -> Dict[str, Any]:
    """Merge tracks, fish detections, and user labels from all uploads."""
    from survey_viz_data import load_csv_track_geojson

    output_root = output_root.resolve()
    uploads = list_uploads()
    features: List[Dict[str, Any]] = []
    bounds: List[float] = []

    for upload in uploads:
        uid = upload['id']
        name = upload.get('survey_name') or uid
        csv_path = _resolve_path(output_root, upload.get('csv_path'))
        fish_path = _resolve_path(output_root, upload.get('fish_geojson_path'))

        if csv_path:
            track = load_csv_track_geojson(csv_path)
            for feat in track.get('features', []):
                if feat.get('geometry', {}).get('type') != 'LineString':
                    continue
                coords = feat['geometry']['coordinates']
                if len(coords) > MAX_TRACK_POINTS_PER_SURVEY:
                    step = max(1, len(coords) // MAX_TRACK_POINTS_PER_SURVEY)
                    coords = coords[::step]
                features.append({
                    'type': 'Feature',
                    'geometry': {'type': 'LineString', 'coordinates': coords},
                    'properties': {
                        'layer': 'track',
                        'survey_id': uid,
                        'survey_name': name,
                        'stroke': '#eab308',
                    },
                })
                for lon, lat in coords[:: max(1, len(coords) // 20)]:
                    bounds.extend([lon, lat])

        if fish_path:
            try:
                with open(fish_path, encoding='utf-8') as handle:
                    fish_data = json.load(handle)
                fish_feats = _subsample(fish_data.get('features', []), MAX_FISH_PER_SURVEY)
                for feat in fish_feats:
                    props = dict(feat.get('properties') or {})
                    props['layer'] = 'fish_auto'
                    props['survey_id'] = uid
                    props['survey_name'] = name
                    features.append({
                        'type': 'Feature',
                        'geometry': feat.get('geometry'),
                        'properties': props,
                    })
                    coords = feat.get('geometry', {}).get('coordinates')
                    if coords and len(coords) >= 2:
                        bounds.extend([coords[0], coords[1]])
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning('Could not load fish layer for %s: %s', uid, exc)

    from survey_database import list_labels

    for label in list_labels():
        lat = label.get('latitude')
        lon = label.get('longitude')
        if lat is None or lon is None:
            continue
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {
                'layer': 'fish_labeled',
                'species': label.get('species'),
                'size': label.get('size'),
                'survey_id': label.get('upload_id'),
                'notes': label.get('notes'),
                'source': label.get('source'),
            },
        })
        bounds.extend([lon, lat])

    meta: Dict[str, Any] = {
        'survey_count': len(uploads),
        'feature_count': len(features),
    }
    if bounds:
        meta['bbox'] = [
            min(bounds[0::2]),
            min(bounds[1::2]),
            max(bounds[0::2]),
            max(bounds[1::2]),
        ]

    return {'type': 'FeatureCollection', 'features': features, 'properties': meta}


def load_echogram_segment(
    output_root: Path,
    upload_id: str,
    start: int = 0,
    limit: int = 1500,
) -> Dict[str, Any]:
    """Load a ping slice from CSV for high-resolution echogram zoom."""
    from survey_viz_data import build_echogram_pings

    upload = get_upload(upload_id)
    if not upload:
        return {'error': 'Upload not found', 'pings': []}
    csv_path = _resolve_path(output_root, upload.get('csv_path'))
    if not csv_path:
        return {'error': 'CSV not found', 'pings': []}
    pings = build_echogram_pings(csv_path, max_pings=50000)
    end = min(len(pings), start + limit)
    return {
        'upload_id': upload_id,
        'survey_name': upload.get('survey_name'),
        'total_pings': len(pings),
        'start': start,
        'end': end,
        'pings': pings[start:end],
    }
