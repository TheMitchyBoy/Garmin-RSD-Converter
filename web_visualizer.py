#!/usr/bin/env python3
"""
Self-contained HTML dashboard generation for sonar fish detections.
"""

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class WebVisualizer:
    """Create offline HTML dashboards from detection GeoJSON and health metrics."""

    @staticmethod
    def create_dashboard(
        detections_file: Path,
        population_metrics: Dict[str, Any],
        location_name: str = "Fishing Survey Area",
        output_file: Optional[Path] = None,
    ) -> Path:
        """Create an HTML dashboard summarizing fish detections and population health."""
        detections_file = Path(detections_file)
        if output_file is None:
            output_file = Path(f"fishing_dashboard_{WebVisualizer._slugify(location_name)}.html")

        features = WebVisualizer._load_features(detections_file)
        points = WebVisualizer._extract_points(features)
        svg = WebVisualizer._build_svg(points)
        rows = WebVisualizer._build_detection_rows(features)

        health = population_metrics.get("health_indicators", {})
        composition = population_metrics.get("population_composition", {})
        population = population_metrics.get("population_health", {})
        depth = population_metrics.get("depth_distribution", {})

        title = html.escape(location_name)
        total_detections = population_metrics.get("total_detections", len(features))

        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sonar Dashboard - {title}</title>
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
      background: linear-gradient(135deg, #123c69, #2563eb);
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
    .map-wrap {{ overflow: auto; }}
    svg {{ width: 100%; min-height: 420px; border-radius: 10px; background: #eff6ff; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>Sonar Analysis Dashboard</h1>
    <p>{title}</p>
  </header>
  <main>
    <section class="grid">
      {WebVisualizer._metric_card("Detections", f"{total_detections:,}")}
      {WebVisualizer._metric_card("Health", health.get("overall_status", "Unknown"))}
      {WebVisualizer._metric_card("Health Score", f'{health.get("overall_health_score", 0)}/100')}
      {WebVisualizer._metric_card("Avg Depth", WebVisualizer._format_number(population.get("average_depth"), "m"))}
      {WebVisualizer._metric_card("Avg Intensity", WebVisualizer._format_number(population.get("average_intensity")))}
      {WebVisualizer._metric_card("Schools", f'{composition.get("school", 0):,}')}
    </section>

    <section class="card">
      <h2>Detection Map</h2>
      <p class="muted">Point positions are scaled from the detection latitude/longitude bounds.</p>
      <div class="map-wrap">{svg}</div>
    </section>

    <section class="grid" style="margin-top: 20px;">
      {WebVisualizer._metric_card("Min Depth", WebVisualizer._format_number(depth.get("min_depth_m"), "m"))}
      {WebVisualizer._metric_card("Median Depth", WebVisualizer._format_number(depth.get("median_depth_m"), "m"))}
      {WebVisualizer._metric_card("Max Depth", WebVisualizer._format_number(depth.get("max_depth_m"), "m"))}
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
</body>
</html>
"""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(document)

        return output_file

    @staticmethod
    def _load_features(detections_file: Path) -> List[Dict[str, Any]]:
        with open(detections_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("features", [])

    @staticmethod
    def _extract_points(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        points = []
        for feature in features:
            geometry = feature.get("geometry", {})
            coordinates = geometry.get("coordinates", [])
            if len(coordinates) < 2:
                continue
            try:
                lon = float(coordinates[0])
                lat = float(coordinates[1])
            except (TypeError, ValueError):
                continue
            props = feature.get("properties", {})
            points.append({
                "lat": lat,
                "lon": lon,
                "depth": props.get("depth_m"),
                "intensity": props.get("intensity"),
                "confidence": props.get("confidence"),
                "size": props.get("size", "unknown"),
                "color": props.get("color", "#2563eb"),
            })
        return points

    @staticmethod
    def _build_svg(points: List[Dict[str, Any]]) -> str:
        width = 960
        height = 420
        padding = 32

        if not points:
            return (
                f'<svg viewBox="0 0 {width} {height}" role="img" '
                'aria-label="No fish detections found">'
                f'<rect width="{width}" height="{height}" fill="#eff6ff"/>'
                f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" '
                'fill="#64748b" font-size="20">No fish detections found</text>'
                '</svg>'
            )

        min_lat = min(point["lat"] for point in points)
        max_lat = max(point["lat"] for point in points)
        min_lon = min(point["lon"] for point in points)
        max_lon = max(point["lon"] for point in points)
        lat_span = max(max_lat - min_lat, 0.000001)
        lon_span = max(max_lon - min_lon, 0.000001)

        circles = []
        for point in points:
            x = padding + ((point["lon"] - min_lon) / lon_span) * (width - padding * 2)
            y = height - padding - ((point["lat"] - min_lat) / lat_span) * (height - padding * 2)
            radius = 5 + min(float(point.get("confidence") or 0), 1.0) * 8
            label = html.escape(
                f"{point.get('size', 'unknown')} fish, depth {point.get('depth', 'n/a')}m"
            )
            color = html.escape(str(point.get("color") or "#2563eb"))
            circles.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                f'fill="{color}" fill-opacity="0.78"><title>{label}</title></circle>'
            )

        return (
            f'<svg viewBox="0 0 {width} {height}" role="img" '
            'aria-label="Fish detection map">'
            f'<rect width="{width}" height="{height}" fill="#eff6ff"/>'
            f'<rect x="{padding}" y="{padding}" width="{width - padding * 2}" '
            f'height="{height - padding * 2}" fill="none" stroke="#bfdbfe"/>'
            + "".join(circles)
            + '</svg>'
        )

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
