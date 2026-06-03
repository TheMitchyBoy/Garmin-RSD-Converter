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

        template_path = Path(__file__).with_name("sonar_dashboard_template.html")
        depth_block = (
            depth_legend_html
            if has_seabed
            else '<div class="legend muted"><h3>Seabed</h3><p>No bathymetry layer for this run.</p></div>'
        )
        metrics_primary = "".join([
            WebVisualizer._metric_card("Detections", f"{total_detections:,}"),
            WebVisualizer._metric_card("Health", health.get("overall_status", "Unknown")),
            WebVisualizer._metric_card("Health score", f'{health.get("overall_health_score", 0)}/100'),
            WebVisualizer._metric_card("Avg depth", WebVisualizer._format_number(population.get("average_depth"), "m")),
            WebVisualizer._metric_card("Avg intensity", WebVisualizer._format_number(population.get("average_intensity"))),
            WebVisualizer._metric_card("Schools", f'{composition.get("school", 0):,}'),
        ])
        metrics_secondary = "".join([
            WebVisualizer._metric_card("Min depth", WebVisualizer._format_number(depth_stats.get("min_depth_m"), "m")),
            WebVisualizer._metric_card("Median depth", WebVisualizer._format_number(depth_stats.get("median_depth_m"), "m")),
            WebVisualizer._metric_card("Max depth", WebVisualizer._format_number(depth_stats.get("max_depth_m"), "m")),
            WebVisualizer._metric_card("Avg confidence", WebVisualizer._format_number(population.get("average_confidence"))),
        ])
        document = (
            template_path.read_text(encoding="utf-8")
            .replace("__TITLE__", title)
            .replace("__METRICS_PRIMARY__", metrics_primary)
            .replace("__METRICS_SECONDARY__", metrics_secondary)
            .replace("__DEPTH_LEGEND__", depth_block)
            .replace("__FISH_LEGEND__", fish_legend_html)
            .replace("__ROWS__", rows)
            .replace("__FISH_GEOJSON__", fish_geojson)
            .replace("__SEABED_GEOJSON__", seabed_geojson)
            .replace("__HAS_SEABED__", str(has_seabed).lower())
        )

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
            '<article class="stat-card">'
            f'<span class="stat-label">{html.escape(str(label))}</span>'
            f'<span class="stat-value">{html.escape(str(value))}</span>'
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
