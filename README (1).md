# Garmin Sonar RSD Converter

Convert Garmin Sonar .RSD data into CSV, 3D visualization, heatmaps, and comprehensive fishing population health analytics.

## 🎯 Key Features

- ✅ Convert Garmin sonar RSD files to CSV
- ✅ **3D Seafloor Visualization** - Interactive point cloud export (PLY format)
- ✅ **Navigation Tracks** - GPS routes in GeoJSON, KML, and GPX
- ✅ **Heatmaps** - Sonar intensity, depth, and temperature visualizations
- ✅ **Fish Detection** - AI-powered fish population detection
- ✅ **Population Health Analytics** - Score fishing area health (0-100)
- ✅ **Public Dashboard** - Beautiful interactive HTML for sharing
- ✅ **Population Reports** - Markdown reports for social media sharing
- ✅ **Complete Pipeline** - One-command analysis workflow

## 📋 Installation

### Requirements
- Python 3.8+

### Setup

```bash
cd /workspaces/Garmin-RSD-Converter
pip install -r requirements.txt
```

## 🚀 Quick Start

### Option 1: Complete Analysis Pipeline (Recommended)

```bash
python sonar_cli.py pipeline Sonar000.RSD --location "My Lake"
```

This generates ALL outputs in one command:
- 3D point cloud visualization
- Interactive web dashboard
- Population health report
- Heatmaps (intensity, depth, temperature)
- Navigation tracks
- Fish detections

### Option 2: Step-by-Step

```bash
# 1. Convert RSD to CSV
python sonar_cli.py convert Sonar000.RSD

# 2. Generate 3D visualization
python sonar_cli.py convert sonar_data.csv --maps ply

# 3. Detect fish populations
python sonar_cli.py fish detect sonar_data.csv

# 4. Analyze population health
python sonar_cli.py health fish_detections.geojson --report

# 5. Create web dashboard
python sonar_cli.py dashboard sonar_data.csv --location "My Lake"
```

## 📚 Detailed Documentation

See [FEATURES_GUIDE.md](FEATURES_GUIDE.md) for comprehensive documentation on:
- All features and their use cases
- Detailed command examples
- Data interpretation guide
- File format reference
- Advanced tips and troubleshooting
- API usage for developers

## 💡 Usage Examples

### 3D Seafloor Visualization
```bash
python sonar_cli.py convert Sonar000.RSD --maps ply
# Open sonar_data_3d.ply in CloudCompare or Blender
```

### Generate Heatmaps
```bash
# Intensity heatmap (shows fish concentration)
python sonar_cli.py heatmap sonar_data.csv --intensity

# Depth heatmap (bathymetry)
python sonar_cli.py heatmap sonar_data.csv --depth

# Temperature heatmap
python sonar_cli.py heatmap sonar_data.csv --temperature

# All heatmaps at once
python sonar_cli.py heatmap sonar_data.csv --all
```

### Fish Detection & Population Analysis
```bash
# Detect fish
python sonar_cli.py fish detect sonar_data.csv

# Analyze population health
python sonar_cli.py health fish_detections.geojson --report --location "Lake Superior"
```

### Create Interactive Dashboard
```bash
# Creates beautiful HTML dashboard for public sharing
python sonar_cli.py dashboard sonar_data.csv --location "Lake Superior"
# Open fishing_dashboard_lake_superior.html in any browser
```

### Navigation Tracks
```bash
# Generate tracks for GPS devices and web mapping
python sonar_cli.py convert Sonar000.RSD --maps all
# Generates: GeoJSON, KML (Google Earth), GPX (Garmin devices)
```

## 🎨 Key Outputs

| Output | Format | Use Case |
|--------|--------|----------|
| CSV Data | Table | Analysis, spreadsheets |
| 3D Point Cloud | PLY | Seafloor visualization (CloudCompare, Meshlab, Blender) |
| Interactive Map | GeoJSON | Web mapping (Leaflet, Mapbox, ArcGIS) |
| GPS Track | KML/GPX | Navigation (Google Earth, Garmin BaseCamp) |
| Heatmap | GeoJSON | Intensity, depth, temperature visualization |
| Fish Detections | GeoJSON | Population data points with confidence scores |
| Health Report | Markdown | Social media sharing, documentation |
| Dashboard | HTML | Public-friendly interactive visualization (self-contained) |

## 🔍 CLI Commands

```bash
# Main help
python sonar_cli.py --help

# Convert RSD to CSV with options
python sonar_cli.py convert [RSD_FILE] -o [OUTPUT_CSV] --stride [BYTES] --maps [FORMAT]

# Analyze sonar data
python sonar_cli.py analyze [CSV_FILE]

# Generate heatmaps
python sonar_cli.py heatmap [CSV_FILE] [--intensity|--depth|--temperature|--all]

# Detect fish
python sonar_cli.py fish detect [CSV_FILE] --min-intensity [INT] --max-intensity [INT]

# Analyze population health
python sonar_cli.py health [DETECTIONS_GEOJSON] [--report] [--location NAME]

# Create web dashboard
python sonar_cli.py dashboard [CSV_FILE] [--detections GEOJSON] [--location NAME]

# Complete pipeline
python sonar_cli.py pipeline [RSD_FILE] [--location NAME] [--stride BYTES]
```

## 📊 Health Score Interpretation

### Overall Health Scores
- **Excellent (>75)**: Abundant, active fish with good diversity
- **Good (60-75)**: Stable population with healthy indicators
- **Fair (45-60)**: Moderate population, monitor trends
- **Poor (<45)**: Low population, conservation recommended

### Population Breakdown
- **Abundance**: Number of fish detected
- **Activity**: Average sonar intensity (fish vigor)
- **Diversity**: Mix of fish sizes and schooling behavior

## 📁 Project Structure

- `sonar_converter.py` - Core RSD binary parser
- `sonar_converter_streaming.py` - Memory-efficient streaming parser
- `analysis_tools.py` - CSV export and mapping utilities
- `heatmap_generator.py` - Intensity, depth, temperature heatmaps
- `fish_detection.py` - Fish population detection engine
- `population_health.py` - Health score analytics
- `web_visualizer.py` - Interactive HTML dashboard generator
- `sonar_cli.py` - Command-line interface
- `FEATURES_GUIDE.md` - Comprehensive feature documentation

## 🔧 Advanced Options

### Custom Conversion Stride
```bash
# Finer detail (slower, larger output)
python sonar_cli.py convert Sonar000.RSD --stride 128

# Coarser detail (faster, smaller output)
python sonar_cli.py convert Sonar000.RSD --stride 512
```

### Fish Detection Sensitivity
```bash
# Find more fish (including tiny ones)
python sonar_cli.py fish detect sonar_data.csv --min-intensity 30

# Find only large fish/schools
python sonar_cli.py fish detect sonar_data.csv --min-intensity 100
```

### Heatmap Grid Resolution
```bash
# Fine detail (~500m resolution)
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.005

# Coarse overview (~2km resolution)
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.02
```

## 🌐 Public Sharing

The system generates multiple formats for sharing fishing health data:

1. **Web Dashboard** (HTML) - Beautiful, interactive, no hosting needed
2. **Health Report** (Markdown) - Shareable on forums, blogs, social media
3. **Navigation Maps** (GeoJSON/KML) - Share fishing locations
4. **Fish Detections** (GeoJSON) - Show where fish are concentrated

Simply share the HTML dashboard file with others - it works offline and in any browser!

## 📈 Use Cases

- 🎣 **Fishing Trip Planning** - Map routes and analyze fishing areas
- 🌊 **Environmental Monitoring** - Track population health over time
- 🐟 **Fish Population Research** - Automated detection and analysis
- 🗺️ **Bathymetry Mapping** - Create seafloor elevation maps
- 📊 **Public Education** - Share fishing area conditions
- 🔍 **Conservation Analysis** - Monitor ecosystem health

## 📄 Additional Documentation

- `SONAR_QUICKSTART.md` - Quick technical reference
- `FEATURES_GUIDE.md` - Complete feature guide with examples
- `test_converter.py` - Unit tests and usage examples

## 🤝 Contributing

Issues, feature requests, and pull requests are welcome!

## 📝 License

See repository for license information.

---

**Get started now:**
```bash
python sonar_cli.py pipeline Sonar000.RSD --location "Your Lake"
```
