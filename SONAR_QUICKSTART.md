# Garmin Sonar RSD Converter - Quick Start Guide

Convert Garmin sonar recordings (RSD files) to CSV format for analysis and visualization.

## Overview

The Garmin Sonar RSD converter extracts sonar survey data from binary RSD files into standard CSV format. Each frame contains:

- **GPS Location**: Latitude and longitude (when available)
- **Depth**: Water depth in meters
- **Water Temperature**: Temperature in Celsius
- **Sonar Frequency**: Operating frequency in kHz
- **Sonar Intensity**: Signal strength metrics

## Installation

No additional dependencies required - uses Python standard library only.

```bash
# Verify Python 3.8+
python --version

# Navigate to project directory
cd /path/to/Garmin-RSD-Converter
```

## Basic Usage

### Bulk upload (web UI)

For drag-and-drop of one or many RSD files:

```bash
python3 sonar_cli.py upload
```

Open `http://127.0.0.1:8765/`, select files, and choose **Convert** or **Full pipeline**. Outputs are written under `./output/<session-id>/`.

### Bulk convert from the command line

```bash
# All RSD files in a folder
python3 sonar_cli.py batch convert ./recordings --output-dir ./exports --maps all

# Preview which files will run
python3 sonar_cli.py batch list ./recordings
```

### Convert Sonar File to CSV

```bash
# Convert with PINGVerter (default nchunk 500)
python sonar_cli.py convert Sonar000.RSD

# Specify custom output filename
python sonar_cli.py convert Sonar000.RSD -o my_sonar_survey.csv

# Validate RSD before converting
python sonar_cli.py convert Sonar000.RSD --validate
```

### Analyze Sonar CSV

```bash
# Get comprehensive statistics from CSV data
python sonar_cli.py analyze sonar_data.csv
```

Expected output:
```
=== Sonar Survey Analysis ===
Total Frames: 1,191,679
File Size: 65.2 MB

Depth Data:
  Records: 293,308
  Range: 0.1m - 999.9m
  Average: 364.9m
  Median: 332.8m

Water Temperature:
  Records: 139,418
  Range: -9.8°C - 48.5°C
  Average: 2.8°C

Sonar Frequency:
  Records: 1,125,775
  Unique values: 67
  Range: 0 - 66 kHz

GPS Coverage:
  Latitude records: 195,782
  Longitude records: 195,174
  Lat range: -9.999206 - 9.890204
  Lon range: -9.999206 - 9.890251
```

## CSV Format

The generated CSV contains the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `frame_number` | Integer | Sequential frame index |
| `offset` | Integer | Byte offset in original RSD file |
| `latitude` | Float | Decimal degrees (-90 to 90) |
| `longitude` | Float | Decimal degrees (-180 to 180) |
| `depth_m` | Float | Water depth in meters |
| `water_temp_c` | Float | Water temperature in Celsius |
| `sonar_frequency_khz` | Float | Sonar operating frequency in kHz |
| `sonar_intensity_avg` | Integer | Average signal intensity |
| `sonar_intensity_max` | Integer | Peak signal intensity |
| `sonar_intensity_count` | Integer | Number of intensity samples |

## Performance Tuning

The `--stride` parameter controls sampling density:

### Stride Values

- **128 bytes**: Maximum detail, slowest (2-3x more data)
- **256 bytes** (default): Good balance of detail and speed
- **512 bytes**: Faster processing, coarser data (2x less detail)
- **1024 bytes**: Very fast, minimal detail

### Example Performance

For a 290 MB sonar file:

| Stride | Frames | Output Size | Time |
|--------|--------|------------|------|
| 128 | 2.38M | 130 MB | ~120 sec |
| 256 | 1.19M | 65 MB | ~46 sec |
| 512 | 595K | 33 MB | ~25 sec |
| 1024 | 297K | 16 MB | ~15 sec |

## Use Cases

### Bathymetric Analysis
Extract depth data for seabed mapping:
```bash
python sonar_cli.py convert Sonar000.RSD
# Then open sonar_data.csv in your analysis tool
# Filter for depth_m column
```

### Temperature Profiling
Analyze water temperature patterns:
```bash
python sonar_cli.py convert Sonar000.RSD
python sonar_cli.py analyze sonar_data.csv
```

### GPS Track Extraction
Export survey path from embedded GPS:
```bash
# In your analysis tool, filter CSV for:
# - latitude != empty
# - longitude != empty
# Create GeoJSON or GPX from these points
```

### Signal Strength Analysis
Monitor sonar transducer performance:
```bash
# Look for patterns in sonar_intensity_avg and sonar_intensity_max
# Low/missing values may indicate equipment issues
```

## Troubleshooting

### File Not Found
```
Error: File not found: Sonar000.RSD
```
- Verify RSD file exists in current directory
- Check filename spelling and case sensitivity
- Use full path if file is in different directory: `python sonar_cli.py convert /path/to/Sonar000.RSD`

### Memory Issues with Large Files
```
# Use a larger stride to reduce data size
python sonar_cli.py convert Sonar000.RSD --stride 512
```

### CSV File Grows Too Large
```
# Use coarser stride for analysis
python sonar_cli.py convert Sonar000.RSD --stride 1024 -o analysis.csv
```

### Missing Depth/Temperature Data
- Not all sonar frames contain depth or temperature readings
- Analysis statistics show record counts - zeros mean no data for that frame
- GPS data is also sparse - only present when device has position fix

## Advanced Analysis

### Using with Python

```python
import csv

# Load and process sonar CSV
with open('sonar_data.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        lat = float(row['latitude']) if row['latitude'] else None
        lon = float(row['longitude']) if row['longitude'] else None
        depth = float(row['depth_m']) if row['depth_m'] else None
        temp = float(row['water_temp_c']) if row['water_temp_c'] else None
        
        # Your analysis here
        if depth and depth < 100:  # Shallow water
            print(f"Shallow water at ({lat:.4f}, {lon:.4f}): {depth}m")
```

### Using with External Tools

The CSV can be imported into:
- **Google Earth Pro**: Plot GPS positions as time series
- **QGIS**: Create bathymetric maps with depth data
- **Excel/Sheets**: Generate depth/temperature charts
- **Python/pandas**: Advanced statistical analysis
- **R**: Spatial and statistical analysis

## File Formats

### Input: RSD (Garmin Sonar Raw Data)
- Binary format proprietary to Garmin
- Typically 100-300+ MB per survey
- Contains GPS, sonar, and environmental data

### Output: CSV (Comma-Separated Values)
- Text format, easily imported into any analysis tool
- Typical 20-30% of original file size
- ~1-2.5M rows per 300MB RSD file

## Additional Help

View all available commands:
```bash
python sonar_cli.py -h
python sonar_cli.py convert -h
python sonar_cli.py analyze -h
```

## Example Workflow

```bash
# 1. Convert sonar file
python sonar_cli.py convert Sonar000.RSD

# 2. Analyze the data
python sonar_cli.py analyze sonar_data.csv

# 3. Now use sonar_data.csv in your preferred analysis tool
# Export depths for bathymetric mapping
# Export temperatures for thermal analysis
# Export GPS coordinates for track visualization
```

---
