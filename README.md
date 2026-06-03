# Garmin Sonar RSD Converter

Convert Garmin Sonar .RSD data into CSV, map exports, heatmaps, dashboards, and 3D point-cloud exports.

## Features

- Convert Garmin sonar RSD files to CSV
- Analyze sonar survey data
- Export sonar data to 3D point clouds (`PLY`)
- Generate GeoJSON, KML, and GPX from sonar GPS tracks
- Generate sonar intensity, depth, and temperature heatmaps
- Detect fish signatures and generate population health reports
- Build a self-contained HTML dashboard from fish detections
- CLI for batch processing and fast streaming conversion

## Installation

### Requirements
- Python 3.8+
- [PINGVerter](https://pypi.org/project/pingverter/) (`pip install -r requirements.txt`)

RSD files are decoded with PINGVerter (documented Garmin format parser), not the legacy heuristic byte scanner.

### Setup

```bash
cd /workspaces/Garmin-RSD-Converter
pip install -r requirements.txt
```

## Usage

### Convert sonar RSD to CSV

```bash
python sonar_cli.py convert Sonar000.RSD
```

### Convert and export 3D point cloud

```bash
python sonar_cli.py convert Sonar000.RSD --maps ply
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

### Convert with custom CSV output and stride

```bash
python sonar_cli.py convert Sonar000.RSD -o sonar_data.csv --stride 512
```

### Analyze sonar CSV

```bash
python sonar_cli.py analyze sonar_data.csv
```

### Generate heatmaps from CSV

```bash
python sonar_cli.py heatmap sonar_data.csv --all
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.005
```

### Detect fish and generate health outputs

```bash
python sonar_cli.py fish detect sonar_data.csv
python sonar_cli.py health sonar_data_fish_detections.geojson --report --location "My Lake"
python sonar_cli.py dashboard sonar_data.csv --location "My Lake"
```

### Run the full workflow

```bash
python sonar_cli.py pipeline Sonar000.RSD --location "My Lake"
```

### Bulk upload and batch processing

Process every RSD in a folder (recursive by default):

```bash
python sonar_cli.py batch convert ./recordings --output-dir ./exports --maps all
python sonar_cli.py batch pipeline ./recordings --output-dir ./analysis
python sonar_cli.py batch list ./recordings
```

Multiple files or globs work on `convert` and `pipeline` too:

```bash
python sonar_cli.py convert Sonar001.RSD Sonar002.RSD --output-dir ./exports
python sonar_cli.py convert "./recordings/*.RSD" --maps geojson
```

**Web upload UI** — drag-and-drop one or many RSD files in the browser:

```bash
python sonar_cli.py upload
# Open http://127.0.0.1:8765/
```

Or run the server directly:

```bash
python sonar_upload_server.py --port 8765 --output-dir ./output
```

## 3D Export

The mapping exports convert sonar CSV rows into portable spatial formats:

- `PLY` uses GPS coordinates projected into a local ENU plane with depth encoded as the Z axis.
- `GeoJSON`, `KML`, and `GPX` preserve the GPS track for web maps, Google Earth, and GPS software.
- Heatmap GeoJSON files aggregate intensity, depth, and temperature values for visualization.

## CLI

The repository contains a single sonar-focused CLI:

- `sonar_cli.py` — convert SONAR RSD to CSV, analyze sonar CSV files, export maps, generate heatmaps, detect fish signatures, and create reports/dashboards
- `batch_processor.py` — discover and bulk-process multiple RSD files
- `sonar_upload_server.py` — local web UI for drag-and-drop upload and bulk conversion

## Files

- `sonar_converter.py` — sonar RSD parser and CSV exporter
- `pingverter_adapter.py` — PINGVerter-based RSD → CSV conversion
- `sonar_converter_streaming.py` — conversion CLI entry point (delegates to PINGVerter)
- `sonar_cli.py` — command-line interface for sonar workflows
- `analysis_tools.py` — sonar CSV mapping and 3D export helpers
- `heatmap_generator.py` — GeoJSON heatmaps for sonar intensity, depth, and temperature
- `fish_detection.py` — heuristic fish-signature detection from sonar readings
- `population_health.py` — fish population health metrics and public reports
- `web_visualizer.py` — self-contained HTML dashboard generation
- `FEATURES_GUIDE.md` — detailed feature guide
- `SONAR_QUICKSTART.md` — sonar usage notes
- `requirements.txt` — Python dependency requirements
- `test_converter.py` — sonar export unit tests
