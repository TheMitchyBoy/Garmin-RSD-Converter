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

    FISH_STYLES = {
        "small": {"color": "#22c55e", "radius": 5.0, "label": "Small"},
        "medium": {"color": "#f59e0b", "radius": 6.5, "label": "Medium"},
        "large": {"color": "#ef4444", "radius": 8.0, "label": "Large"},
        "school": {"color": "#7c3aed", "radius": 10.0, "label": "School"},
        "unknown": {"color": "#64748b", "radius": 6.0, "label": "Unknown"},
    }

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
    .map-note {{ margin-bottom: 14px; }}
    svg {{ width: 100%; min-height: 460px; border-radius: 12px; background: #e0f2fe; }}
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
      <p class="muted map-note">Point positions are scaled from the detection latitude/longitude bounds. Color shows fish size class and halo size shows confidence.</p>
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
        height = 460
        padding = 54

        if not points:
            return (
                f'<svg viewBox="0 0 {width} {height}" role="img" '
                'aria-label="No fish detections found">'
                f'<rect width="{width}" height="{height}" fill="#e0f2fe"/>'
                f'<rect x="{padding}" y="{padding}" width="{width - padding * 2}" '
                f'height="{height - padding * 2}" rx="18" fill="#f8fafc" stroke="#bae6fd"/>'
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

        plot_width = width - padding * 2
        plot_height = height - padding * 2

        grid_lines = []
        for step in range(1, 4):
            x = padding + (plot_width * step / 4)
            y = padding + (plot_height * step / 4)
            grid_lines.append(
                f'<line x1="{x:.1f}" y1="{padding}" x2="{x:.1f}" y2="{height - padding}" '
                'stroke="#cbd5e1" stroke-dasharray="4 6" stroke-opacity="0.75"/>'
            )
            grid_lines.append(
                f'<line x1="{padding}" y1="{y:.1f}" x2="{width - padding}" y2="{y:.1f}" '
                'stroke="#cbd5e1" stroke-dasharray="4 6" stroke-opacity="0.75"/>'
            )

        circles = []
        sorted_points = sorted(points, key=lambda item: WebVisualizer._safe_float(item.get("confidence")) or 0.0)
        for point in sorted_points:
            x = padding + ((point["lon"] - min_lon) / lon_span) * (width - padding * 2)
            y = height - padding - ((point["lat"] - min_lat) / lat_span) * (height - padding * 2)
            size = str(point.get("size", "unknown")).lower()
            style = WebVisualizer.FISH_STYLES.get(size, WebVisualizer.FISH_STYLES["unknown"])
            confidence = min(WebVisualizer._safe_float(point.get("confidence")) or 0.0, 1.0)
            radius = style["radius"] + confidence * 5
            halo_radius = radius + 7 + confidence * 7
            label = html.escape(
                f"{point.get('size', 'unknown')} fish, depth {point.get('depth', 'n/a')}m, "
                f"confidence {confidence:.2f}, intensity {point.get('intensity', 'n/a')}"
            )
            color = html.escape(str(point.get("color") or style["color"]))
            circles.append(
                f'<g class="detection detection-{html.escape(size)}">'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{halo_radius:.1f}" '
                f'fill="{color}" fill-opacity="{0.10 + confidence * 0.18:.2f}"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                f'fill="{color}" fill-opacity="0.9" stroke="#ffffff" stroke-width="2.2">'
                f'<title>{label}</title></circle>'
                '</g>'
            )

        return (
            f'<svg viewBox="0 0 {width} {height}" role="img" '
            'aria-label="Fish detection map">'
            '<defs>'
            '<linearGradient id="waterGradient" x1="0" x2="1" y1="0" y2="1">'
            '<stop offset="0%" stop-color="#f0f9ff"/>'
            '<stop offset="58%" stop-color="#bae6fd"/>'
            '<stop offset="100%" stop-color="#0f4c81"/>'
            '</linearGradient>'
            '</defs>'
            f'<rect width="{width}" height="{height}" fill="#e0f2fe"/>'
            f'<rect x="{padding}" y="{padding}" width="{width - padding * 2}" '
            f'height="{height - padding * 2}" rx="18" fill="url(#waterGradient)" stroke="#075985" '
            'stroke-opacity="0.36"/>'
            + "".join(grid_lines)
            + WebVisualizer._svg_bounds_labels(
                min_lat, max_lat, min_lon, max_lon, width, height, padding
            )
            + "".join(circles)
            + WebVisualizer._svg_map_legend(width, height)
            + '</svg>'
        )

    @staticmethod
    def _svg_bounds_labels(
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        width: int,
        height: int,
        padding: int,
    ) -> str:
        """Build subtle coordinate labels and a north marker for the SVG map."""
        labels = [
            f'<text x="{padding}" y="{padding - 16}" fill="#0f172a" font-size="13" font-weight="700">N</text>',
            f'<text x="{padding}" y="{height - 18}" fill="#475569" font-size="12">SW {min_lat:.5f}, {min_lon:.5f}</text>',
            f'<text x="{width - padding}" y="{padding - 16}" fill="#475569" font-size="12" text-anchor="end">NE {max_lat:.5f}, {max_lon:.5f}</text>',
            f'<line x1="{padding + 6}" y1="{padding - 12}" x2="{padding + 6}" y2="{padding - 34}" stroke="#0f172a" stroke-width="2"/>',
            f'<path d="M {padding + 6} {padding - 40} L {padding} {padding - 28} L {padding + 12} {padding - 28} Z" fill="#0f172a"/>',
        ]
        return "".join(labels)

    @staticmethod
    def _svg_map_legend(width: int, height: int) -> str:
        """Build an embedded fish size and confidence legend."""
        legend_x = width - 190
        legend_y = height - 184
        rows = []
        for offset, key in enumerate(("small", "medium", "large", "school")):
            style = WebVisualizer.FISH_STYLES[key]
            y = legend_y + 46 + offset * 24
            rows.append(
                f'<circle cx="{legend_x + 18}" cy="{y}" r="{style["radius"]:.1f}" '
                f'fill="{style["color"]}" fill-opacity="0.9" stroke="#ffffff" stroke-width="1.8"/>'
                f'<text x="{legend_x + 38}" y="{y + 4}" fill="#0f172a" font-size="12">'
                f'{style["label"]}</text>'
            )

        return (
            f'<g class="map-legend" aria-label="Map legend">'
            f'<rect x="{legend_x}" y="{legend_y}" width="158" height="154" rx="14" '
            'fill="#ffffff" fill-opacity="0.88" stroke="#cbd5e1"/>'
            f'<text x="{legend_x + 14}" y="{legend_y + 24}" fill="#0f172a" '
            'font-size="13" font-weight="700">Map legend</text>'
            + "".join(rows)
            f'<circle cx="{legend_x + 18}" cy="{legend_y + 140}" r="13" '
            'fill="#0ea5e9" fill-opacity="0.18"/>'
            f'<circle cx="{legend_x + 18}" cy="{legend_y + 140}" r="5" '
            'fill="#0ea5e9" fill-opacity="0.9"/>'
            f'<text x="{legend_x + 38}" y="{legend_y + 144}" fill="#0f172a" '
            'font-size="12">Confidence halo</text>'
            '</g>'
        )

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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
