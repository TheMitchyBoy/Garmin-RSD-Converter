# Garmin Sonar RSD Converter

Convert Garmin Sonar `.RSD` data into CSV, map exports, heatmaps, dashboards, and 3D point-cloud exports.

> **Not affiliated with Garmin.** This project heuristically reverse-engineers the proprietary
> `.RSD` format. Fish detection and population health outputs are exploratory sonar analyses,
> not biological survey data. See [LICENSE](LICENSE) and [ARCHITECTURE.md](ARCHITECTURE.md).

## Features

- Convert Garmin sonar RSD files to CSV (streaming, low memory)
- Analyze sonar survey data with streaming statistics
- Export sonar data to 3D point clouds (`PLY`)
- Generate GeoJSON, KML, and GPX from sonar GPS tracks
- Generate sonar intensity, depth, and temperature heatmaps
- Detect heuristic intensity signatures and generate composite reports
- Build a self-contained HTML dashboard with an interactive Leaflet map
- CLI for batch processing and full pipeline workflows

## Installation

### Requirements

- Python 3.8+

### Setup

```bash
git clone https://github.com/TheMitchyBoy/Garmin-RSD-Converter.git
cd Garmin-RSD-Converter
pip install -e .
```

Or run directly without installing:

```bash
python sonar_cli.py --help
```

### Generate a sample RSD for testing

```bash
python fixtures/generate_sample_rsd.py fixtures/sample_sonar.rsd
python sonar_cli.py pipeline fixtures/sample_sonar.rsd --location "Demo Lake"
```

## Usage

### Convert sonar RSD to CSV

```bash
python sonar_cli.py convert Sonar000.RSD
# or
garmin-rsd convert Sonar000.RSD
```

### Convert and export all map formats

```bash
python sonar_cli.py convert Sonar000.RSD --maps all
```

This generates:

- `*_3d.ply` point cloud
- `*_map.geojson` web map track
- `*_map.kml` Google Earth track
- `*_map.gpx` GPS track

### Analyze sonar CSV

```bash
python sonar_cli.py analyze sonar_data.csv
```

### Generate heatmaps from CSV

```bash
python sonar_cli.py heatmap sonar_data.csv --all
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.005
```

### Detect intensity signatures and generate reports

```bash
python sonar_cli.py fish detect sonar_data.csv
python sonar_cli.py health sonar_data_fish_detections.geojson --report --location "My Lake"
python sonar_cli.py dashboard sonar_data.csv --location "My Lake"
```

### Run the full workflow

```bash
python sonar_cli.py pipeline Sonar000.RSD --location "My Lake"
```

## CSV Schema

The streaming converter produces a canonical CSV schema documented in
[ARCHITECTURE.md](ARCHITECTURE.md). Downstream exporters normalize fields automatically
(for example, `depth_m` is used for KML/GPX elevation and `sonar_intensity_count`
maps to PLY `beam_count`).

## Testing

```bash
python -m unittest discover -v
```

CI runs on Python 3.8, 3.10, and 3.12 via GitHub Actions.

## Files

| File | Purpose |
|------|---------|
| `sonar_cli.py` | CLI entry point |
| `sonar_schema.py` | Shared CSV schema, row parsing, streaming stats |
| `sonar_converter_streaming.py` | Active RSD → CSV converter |
| `sonar_converter.py` | Deprecated wrapper (delegates to streaming) |
| `analysis_tools.py` | GeoJSON, KML, GPX, PLY exports |
| `heatmap_generator.py` | Intensity, depth, temperature heatmaps |
| `fish_detection.py` | Heuristic intensity signature detection |
| `population_health.py` | Composite heuristic scores and reports |
| `web_visualizer.py` | HTML dashboard with Leaflet map |
| `fixtures/generate_sample_rsd.py` | Synthetic RSD generator for tests/demos |
| `test_converter.py` | Unit and integration tests |
| `ARCHITECTURE.md` | Architecture and data flow |
| `FEATURES_GUIDE.md` | Detailed feature guide |
| `SONAR_QUICKSTART.md` | Quick-start for RSD conversion |

## License

MIT — see [LICENSE](LICENSE).
