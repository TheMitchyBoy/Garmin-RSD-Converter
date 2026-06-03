# Garmin Sonar RSD Converter

Convert Garmin sonar RSD survey data into CSV, maps, and 3D point-cloud exports.

## Features

- Convert Garmin sonar RSD files to CSV
- Analyze sonar survey data
- Export sonar data to 3D point clouds (`PLY`)
- Generate GeoJSON, KML, and GPX from sonar GPS tracks
- CLI for batch processing and fast streaming conversion

## Installation

### Requirements
- Python 3.8+

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

### Convert with custom CSV output and stride

```bash
python sonar_cli.py convert Sonar000.RSD -o sonar_data.csv --stride 512
```

### Analyze sonar CSV

```bash
python sonar_cli.py analyze sonar_data.csv
```

## 3D Export

The `PLY` export converts sonar CSV rows into a 3D point cloud using GPS coordinates projected into a local ENU plane. Depth is encoded as the Z axis.

## CLI

The repository now contains a single sonar-focused CLI:

- `sonar_cli.py` — convert SONAR RSD to CSV, analyze sonar CSV files, and export 3D PLY point clouds

## Files

- `sonar_converter.py` — sonar RSD parser and CSV exporter
- `sonar_converter_streaming.py` — streaming sonar conversion for large files
- `sonar_cli.py` — command-line interface for sonar workflows
- `analysis_tools.py` — sonar CSV mapping and 3D export helpers
- `SONAR_QUICKSTART.md` — sonar usage notes
- `requirements.txt` — Python dependency requirements
- `test_converter.py` — sonar export unit tests
