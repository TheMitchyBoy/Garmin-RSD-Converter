#!/usr/bin/env python3
"""
Self-contained HTML dashboard generation for sonar fish detections and seabed maps.
"""

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from map_visuals import (
    FISH_SIZE_LEGEND,
    depth_legend_stops,
    load_geojson_features,
)


class WebVisualizer:
    """Create offline HTML dashboards from detection GeoJSON and health metrics."""

    @staticmethod
    def create_dashboard(
        detections_file: Path,
        population_metrics: Dict[str, Any],
        location_name: str = "Fishing Survey Area",
        output_file: Optional[Path] = None,
        depth_geojson_file: Optional[Path] = None,
    ) -> Path:
        """
        Create an HTML dashboard with interactive seabed + fish detection layers.

        Args:
            detections_file: Fish detections GeoJSON
            population_metrics: Population health metrics dict
            location_name: Display name for the survey
            output_file: Optional output HTML path
            depth_geojson_file: Optional bathymetry/seabed heatmap GeoJSON
        """
        detections_file = Path(detections_file)
        if output_file is None:
            output_file = Path(f"fishing_dashboard_{WebVisualizer._slugify(location_name)}.html")

        fish_features = WebVisualizer._load_features(detections_file)
        seabed_features: List[Dict[str, Any]] = []
        depth_meta: Dict[str, Any] = {}

        if depth_geojson_file:
            depth_path = Path(depth_geojson_file)
            if depth_path.exists():
                with open(depth_path, "r", encoding="utf-8") as f:
                    depth_data = json.load(f)
                seabed_features = depth_data.get("features", [])
                depth_meta = depth_data.get("properties", {}) or {}

        fish_geojson = json.dumps({"type": "FeatureCollection", "features": fish_features})
        seabed_geojson = json.dumps({"type": "FeatureCollection", "features": seabed_features})
        rows = WebVisualizer._build_detection_rows(fish_features)

        health = population_metrics.get("health_indicators", {})
        composition = population_metrics.get("population_composition", {})
        population = population_metrics.get("population_health", {})
        depth_stats = population_metrics.get("depth_distribution", {})

        title = html.escape(location_name)
        total_detections = population_metrics.get("total_detections", len(fish_features))

        min_depth_m = depth_meta.get("depth_min_m")
        max_depth_m = depth_meta.get("depth_max_m")
        if min_depth_m is None and depth_stats.get("min_depth_m") is not None:
            min_depth_m = depth_stats.get("min_depth_m")
        if max_depth_m is None and depth_stats.get("max_depth_m") is not None:
            max_depth_m = depth_stats.get("max_depth_m")

        depth_legend_html = WebVisualizer._build_depth_legend_html(min_depth_m, max_depth_m)
        fish_legend_html = WebVisualizer._build_fish_legend_html()
        has_seabed = bool(seabed_features)

        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sonar Dashboard - {title}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --card: #ffffff;
      --ink: #1f2937;
      --muted: #64748b;
      --accent: #2563eb;
      --line: #dbe3ef;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 32px;
      background: linear-gradient(135deg, #0c4a6e, #2563eb);
      color: white;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 32px; }}
    header p {{ margin: 0; opacity: 0.9; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
    }}
    .label {{ color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; }}
    .value {{ font-size: 28px; font-weight: 700; margin-top: 6px; }}
    h2 {{ margin-top: 0; }}
    .map-note {{ margin-bottom: 14px; }}
    #map {{
      width: 100%;
      height: 520px;
      border-radius: 10px;
      border: 1px solid var(--line);
    }}
    .map-section {{ position: relative; }}
    .legends {{
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      margin-top: 14px;
    }}
    .legend {{
      flex: 1;
      min-width: 200px;
      padding: 12px 14px;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: 10px;
      font-size: 13px;
    }}
    .legend h3 {{
      margin: 0 0 10px;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }}
    .swatch {{
      width: 18px;
      height: 18px;
      border-radius: 4px;
      border: 1px solid rgba(0,0,0,0.12);
      flex-shrink: 0;
    }}
    .swatch-round {{
      border-radius: 50%;
    }}
    .depth-bar {{
      height: 14px;
      border-radius: 6px;
      margin: 8px 0;
      border: 1px solid var(--line);
    }}
    .depth-labels {{
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: var(--muted);
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>Sonar Survey Dashboard</h1>
    <p>{title} — seabed bathymetry &amp; fish detections</p>
  </header>
  <main>
    <section class="grid">
      {WebVisualizer._metric_card("Fish Detections", f"{total_detections:,}")}
      {WebVisualizer._metric_card("Health", health.get("overall_status", "Unknown"))}
      {WebVisualizer._metric_card("Health Score", f'{health.get("overall_health_score", 0)}/100')}
      {WebVisualizer._metric_card("Avg Depth", WebVisualizer._format_number(population.get("average_depth"), "m"))}
      {WebVisualizer._metric_card("Avg Intensity", WebVisualizer._format_number(population.get("average_intensity")))}
      {WebVisualizer._metric_card("Schools", f'{composition.get("school", 0):,}')}
    </section>

    <section class="card map-section">
      <h2>Survey Map</h2>
      <p class="muted map-note">Toggle layers: seabed depth (bathymetry) under fish detection markers. Color shows fish size class; marker size and opacity show confidence. Basemap requires network.</p>
      <div id="map" role="img" aria-label="Seabed and fish detection map"></div>
      <div class="legends">
        {depth_legend_html if has_seabed else '<div class="legend muted"><h3>Seabed</h3><p>No bathymetry layer — pass <code>--depth-heatmap</code> or run heatmap first.</p></div>'}
        {fish_legend_html}
      </div>
    </section>

    <section class="grid" style="margin-top: 20px;">
      {WebVisualizer._metric_card("Min Depth", WebVisualizer._format_number(depth_stats.get("min_depth_m"), "m"))}
      {WebVisualizer._metric_card("Median Depth", WebVisualizer._format_number(depth_stats.get("median_depth_m"), "m"))}
      {WebVisualizer._metric_card("Max Depth", WebVisualizer._format_number(depth_stats.get("max_depth_m"), "m"))}
      {WebVisualizer._metric_card("Avg Confidence", WebVisualizer._format_number(population.get("average_confidence")))}
    </section>

    <section class="card">
      <h2>Detection Details</h2>
      <table>
        <thead>
          <tr>
            <th>Size</th>
            <th>Latitude</th>
            <th>Longitude</th>
            <th>Depth</th>
            <th>Intensity</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
  </main>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script>
    const fishData = {fish_geojson};
    const seabedData = {seabed_geojson};
    const hasSeabed = {str(has_seabed).lower()};

    const map = L.map('map');
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);

    const layers = {{}};

    if (hasSeabed) {{
      layers.seabed = L.geoJSON(seabedData, {{
        style: (feature) => {{
          const p = feature.properties || {{}};
          return {{
            fillColor: p.color || '#38bdf8',
            color: p.color || '#0c4a6e',
            weight: 1,
            opacity: 0.85,
            fillOpacity: p.fill_opacity != null ? p.fill_opacity : 0.75
          }};
        }},
        onEachFeature: (feature, layer) => {{
          const p = feature.properties || {{}};
          layer.bindPopup(
            '<strong>Seabed depth</strong><br>' +
            'Depth: ' + (p.depth_m != null ? p.depth_m + ' m' : 'n/a') +
            (p.point_count ? '<br>Samples: ' + p.point_count : '')
          );
        }}
      }});
      layers.seabed.addTo(map);
    }}

    layers.fish = L.geoJSON(fishData, {{
      pointToLayer: (feature, latlng) => {{
        const p = feature.properties || {{}};
        const size = p.size || 'unknown';
        const confidence = p.confidence != null ? p.confidence : 0.5;
        const radii = {{ small: 5, medium: 7, large: 9, school: 12 }};
        const radius = (radii[size] || 6) + Math.min(confidence, 1) * 4;
        return L.circleMarker(latlng, {{
          radius,
          fillColor: p.color || '#f59e0b',
          color: '#1e293b',
          weight: 1.5,
          opacity: 0.95,
          fillOpacity: Math.max(0.45, Math.min(confidence, 1) * 0.45 + 0.45)
        }});
      }},
      onEachFeature: (feature, layer) => {{
        const p = feature.properties || {{}};
        layer.bindPopup(
          '<strong>' + (p.size || 'unknown') + ' fish</strong><br>' +
          'Depth: ' + (p.depth_m != null ? p.depth_m + ' m' : 'n/a') + '<br>' +
          'Intensity: ' + (p.intensity != null ? p.intensity : 'n/a') + '<br>' +
          'Confidence: ' + (p.confidence != null ? p.confidence : 'n/a')
        );
      }}
    }});
    layers.fish.addTo(map);

    const overlayMaps = {{}};
    if (hasSeabed) overlayMaps['Seabed depth'] = layers.seabed;
    overlayMaps['Fish detections'] = layers.fish;
    L.control.layers(null, overlayMaps, {{ collapsed: false }}).addTo(map);

    const allBounds = [];
    [layers.fish, layers.seabed].filter(Boolean).forEach((layer) => {{
      try {{
        const b = layer.getBounds();
        if (b.isValid()) allBounds.push(b);
      }} catch (e) {{}}
    }});
    if (allBounds.length) {{
      const combined = allBounds.reduce((acc, b) => acc.extend(b));
      map.fitBounds(combined, {{ padding: [28, 28] }});
    }} else {{
      map.setView([0, 0], 2);
    }}
  </script>
</body>
</html>
"""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(document)

        return output_file

    @staticmethod
    def create_survey_map_html(
        csv_file: Path,
        detections_file: Optional[Path] = None,
        depth_geojson_file: Optional[Path] = None,
        location_name: str = "Sonar Survey",
        output_file: Optional[Path] = None,
        grid_size: float = 0.01,
    ) -> Path:
        """
        Create a standalone HTML map focused on seabed + fish layers (no metrics table).
        """
        from heatmap_generator import HeatmapGenerator
        from fish_detection import FishDetector

        csv_file = Path(csv_file)
        if output_file is None:
            output_file = Path(f"survey_map_{WebVisualizer._slugify(location_name)}.html")

        if depth_geojson_file is None:
            depth_geojson_file = HeatmapGenerator.create_depth_heatmap(
                csv_file, grid_size=grid_size,
            )
        if detections_file is None:
            detections_file, _ = FishDetector.detect_fish(csv_file)

        return WebVisualizer.create_dashboard(
            detections_file,
            {"total_detections": len(load_geojson_features(Path(detections_file)))},
            location_name=location_name,
            output_file=output_file,
            depth_geojson_file=depth_geojson_file,
        )

    @staticmethod
    def _build_depth_legend_html(
        min_depth: Optional[float],
        max_depth: Optional[float],
    ) -> str:
        if min_depth is None or max_depth is None:
            return (
                '<div class="legend"><h3>Seabed depth</h3>'
                '<p class="muted">Depth range unavailable</p></div>'
            )
        stops = depth_legend_stops(float(min_depth), float(max_depth), steps=5)
        gradient = ", ".join(
            f"{s['color']} {i * 100 / (len(stops) - 1)}%"
            for i, s in enumerate(stops)
        )
        items = "".join(
            f'<div class="legend-item"><span class="swatch" style="background:{html.escape(s["color"])}"></span>'
            f'<span>{s["depth_m"]} m</span></div>'
            for s in stops
        )
        return f"""<div class="legend">
      <h3>Seabed depth</h3>
      <div class="depth-bar" style="background: linear-gradient(to right, {gradient});"></div>
      <div class="depth-labels">
        <span>Shallow {min_depth:.1f} m</span>
        <span>Deep {max_depth:.1f} m</span>
      </div>
      {items}
    </div>"""

    @staticmethod
    def _build_fish_legend_html() -> str:
        items = []
        for key, meta in FISH_SIZE_LEGEND.items():
            color = meta["color"]
            label = meta["label"]
            items.append(
                f'<div class="legend-item">'
                f'<span class="swatch swatch-round" style="background:{color}"></span>'
                f'<span>{html.escape(label)}</span></div>'
            )
        items.append(
            '<div class="legend-item muted">'
            '<span class="swatch swatch-round" style="background:#94a3b8; opacity:0.55"></span>'
            '<span>Marker size and opacity show confidence</span></div>'
        )
        return f'<div class="legend"><h3>Fish detections</h3>{"".join(items)}</div>'

    @staticmethod
    def _load_features(detections_file: Path) -> List[Dict[str, Any]]:
        with open(detections_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("features", [])

    @staticmethod
    def _build_detection_rows(features: List[Dict[str, Any]]) -> str:
        if not features:
            return '<tr><td colspan="6" class="muted">No detections found</td></tr>'

        rows = []
        for feature in features[:250]:
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", ["", ""])
            lon = coords[0] if len(coords) > 0 else ""
            lat = coords[1] if len(coords) > 1 else ""
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(props.get('size', 'unknown')))}</td>"
                f"<td>{WebVisualizer._format_number(lat)}</td>"
                f"<td>{WebVisualizer._format_number(lon)}</td>"
                f"<td>{WebVisualizer._format_number(props.get('depth_m'), 'm')}</td>"
                f"<td>{WebVisualizer._format_number(props.get('intensity'))}</td>"
                f"<td>{WebVisualizer._format_number(props.get('confidence'))}</td>"
                "</tr>"
            )

        if len(features) > 250:
            rows.append(
                f'<tr><td colspan="6" class="muted">Showing 250 of {len(features):,} detections</td></tr>'
            )

        return "\n".join(rows)

    @staticmethod
    def _metric_card(label: str, value: Any) -> str:
        return (
            '<article class="card">'
            f'<div class="label">{html.escape(str(label))}</div>'
            f'<div class="value">{html.escape(str(value))}</div>'
            '</article>'
        )

    @staticmethod
    def _format_number(value: Any, suffix: str = "") -> str:
        if value is None or value == "":
            return "N/A"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return html.escape(str(value))
        formatted = f"{number:.3f}".rstrip("0").rstrip(".")
        return f"{formatted} {suffix}".strip()

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
        return slug or "survey"
