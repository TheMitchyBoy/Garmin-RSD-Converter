# Sonar Analysis Features & Usage Guide

## Complete Sonar Analysis Platform

This is a comprehensive platform for analyzing Garmin sonar data, detecting fish populations, and sharing fishing health metrics with the public.

## Features Overview

### 1. 🗺️ 3D Seafloor Visualization

Convert sonar readings into interactive 3D point clouds showing seafloor topography.

**Use Cases:**
- Visualize underwater bathymetry
- Identify underwater structures and formations
- Create reference maps for navigation

**Outputs:**
- **PLY format**: 3D point cloud (use CloudCompare, Meshlab, or Blender to view)
- Each point contains: X/Y (ENU projection), Z (depth), intensity, temperature

**Command:**
```bash
python sonar_cli.py convert Sonar000.RSD --maps ply
python sonar_cli.py pipeline Sonar000.RSD  # Includes PLY + all visualizations
```

**Example viewing:**
```bash
# Open in CloudCompare (free software)
cloudcompare sonar_data_3d.ply
```

---

### 2. 🧭 Navigation Tracks

Generate GPS tracks in multiple formats for navigation and trip planning.

**Supported Formats:**
- **GeoJSON**: Web mapping (Leaflet, Mapbox, ArcGIS Online)
- **KML**: Google Earth, Google Maps
- **GPX**: GPS devices, Garmin BaseCamp

**Features:**
- Complete GPS coordinate path
- Depth and temperature metadata
- Compatible with all major GPS software

**Command:**
```bash
# Generate all track formats
python sonar_cli.py convert Sonar000.RSD --maps all

# Or individually
python sonar_cli.py convert Sonar000.RSD --maps geojson kml gpx
```

**Usage Examples:**
```bash
# View in Google Earth
python sonar_cli.py convert Sonar000.RSD --maps kml
# Then open the .kml file in Google Earth Pro

# Share on web mapping platform
# Upload the .geojson file to Mapbox, Leaflet, or similar
```

---

### 3. 🔥 Heatmaps

Generate color-coded intensity visualizations showing:
- **Sonar intensity**: Areas with strong acoustic returns (potential fish/structures)
- **Depth mapping**: Bathymetric visualization
- **Temperature patterns**: Water temperature variations

**Heatmap Types:**

#### Intensity Heatmap
Shows where fish/objects are concentrated based on sonar signal strength.
- Blue = weak signals (empty water)
- Green → Yellow → Red = increasing intensity (fish/structures)

```bash
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.01
```

#### Depth Heatmap
Visualizes seafloor elevation.
- Light cyan = shallow shoals
- Medium blue = mid-depth contours
- Dark navy = deepest water
- GeoJSON properties include map styling (`marker-color`, `fill`, `stroke`, `depth_band`) for common web map viewers

```bash
python sonar_cli.py heatmap sonar_data.csv --depth
```

#### Temperature Heatmap
Shows water temperature distribution.

```bash
python sonar_cli.py heatmap sonar_data.csv --temperature
```

#### All Heatmaps
Generate all three types at once:

```bash
python sonar_cli.py heatmap sonar_data.csv --all
```

**Grid Size Parameter:**
- Default: 0.01° (≈ 1km at equator)
- Smaller values (0.005) = more detail, larger file
- Larger values (0.05) = less detail, smaller file

---

### 4. 🐟 Fish Detection & Tracking

Automatically detect and classify fish based on sonar intensity patterns.

**Fish Classification:**
- **Small Fish**: Individual small fish (30-60 intensity)
- **Medium Fish**: Larger individuals or small groups (60-80 intensity)
- **Large Fish**: Trophy-sized fish or loose groups (80-120 intensity)
- **Schools**: Dense fish aggregations (>120 intensity)

**Detection Parameters:**
- Minimum intensity: 40 (default, adjustable)
- Maximum intensity: 200 (prevents noise from seafloor detection)
- Depth range: 2-500m (where fish are typically found)

**Command:**
```bash
# Detect fish with default thresholds
python sonar_cli.py fish detect sonar_data.csv

# Custom intensity thresholds
python sonar_cli.py fish detect sonar_data.csv --min-intensity 50 --max-intensity 150
```

**Output:**
- GeoJSON file with all detections
- Each point shows: location, depth, intensity, confidence score, fish size

**Confidence Score:**
- 0-1.0 scale
- Influenced by: intensity, depth, signal characteristics
- Higher = more likely to be actual fish

---

### 5. 📊 Population Health Analytics

Analyze and score fish population health across multiple dimensions.

**Metrics Calculated:**

1. **Abundance Score (0-100)**
   - Based on total fish detections
   - Higher = more fish present

2. **Activity Score (0-100)**
   - Based on average sonar intensity
   - Higher = more active fish

3. **Diversity Score (0-100)**
   - Based on size distribution and schooling behavior
   - Higher = good mix of fish sizes

4. **Overall Health Score (0-100)**
   - Average of all three metrics
   - Excellent (>75), Good (60-75), Fair (45-60), Poor (<45)

**Health Status Indicators:**
- **Abundance**: Abundant, Good, Moderate, Sparse
- **Activity**: Very Active, Active, Moderate, Low
- **Diversity**: Excellent, Good, Fair, Poor
- **Overall**: Excellent, Good, Fair, Poor

**Command:**
```bash
# Analyze population from fish detections
python sonar_cli.py health fish_detections.geojson

# With public report
python sonar_cli.py health fish_detections.geojson --report --location "Lake Superior"
```

**Public Report:**
- Markdown report suitable for sharing
- Health assessments and recommendations
- Visual breakdowns of population composition
- Habitat conditions summary

---

### 6. 🌐 Web Dashboard for Public Sharing

Create an interactive, beautiful HTML dashboard for sharing fishing health data.

**Dashboard Features:**
- Real-time interactive map (Leaflet)
- Health score visualization
- Population composition charts
- Habitat condition metrics
- Fish detection points with details
- Responsive design (mobile-friendly)
- No external dependencies needed (embedded all libraries)

**Colors & Styling:**
- Fish size indicated by point color:
  - Green = Small fish
  - Amber = Medium fish
  - Red = Large fish
  - Purple = Schools

- Point size and halo indicate confidence level
- Fish detection GeoJSON includes map styling (`marker-color`, `marker-size`, `marker-symbol`, `fill`, `stroke`) for direct upload to web mapping tools
- Health scores color-coded: Green (Excellent), Blue (Good), Yellow (Fair), Red (Poor)

**Command:**
```bash
# Create dashboard (auto-generates fish detections if not provided)
python sonar_cli.py dashboard sonar_data.csv --location "Lake Superior"

# With existing detections
python sonar_cli.py dashboard sonar_data.csv \
    --detections fish_detections.geojson \
    --location "Lake Superior"
```

**Output:**
- `fishing_dashboard_lake_superior.html`
- Open directly in any web browser
- Share the HTML file via email, web hosting, social media
- No server needed - fully standalone

---

### 7. 🚀 Complete Pipeline

Run the entire analysis workflow in one command.

```bash
python sonar_cli.py pipeline Sonar000.RSD --location "Lake Superior"
```

**What It Does:**
1. ✅ Converts RSD to CSV
2. ✅ Generates 3D PLY point cloud
3. ✅ Creates GeoJSON interactive map
4. ✅ Generates all heatmaps (intensity, depth, temperature)
5. ✅ Detects fish populations
6. ✅ Analyzes population health
7. ✅ Creates public-friendly markdown report
8. ✅ Generates interactive web dashboard

**Output Files:**
```
sonar_data.csv                      # Raw survey data
sonar_data_3d.ply                   # 3D seafloor visualization
sonar_data_map.geojson              # Interactive map
sonar_data_intensity_heatmap.geojson # Intensity heatmap
sonar_data_depth_heatmap.geojson    # Depth visualization
sonar_data_temperature_heatmap.geojson # Temperature map
sonar_data_fish_detections.geojson  # Fish population data
fishing_health_report_20240603.md   # Public report
fishing_dashboard_lake_superior.html # Interactive dashboard
```

---

## Usage Workflows

### Workflow 1: Create Public Fishing Health Report (Easiest)

```bash
# One command does everything
python sonar_cli.py pipeline Sonar000.RSD --location "My Favorite Lake"

# Results:
# - Dashboard ready to share: fishing_dashboard_my_favorite_lake.html
# - Report for social media: fishing_health_report_*.md
# - All visualization files
```

**To Share:**
- Email the HTML file to friends
- Upload to personal website
- Share report on fishing forums

---

### Workflow 2: Deep Seafloor Analysis

```bash
# Convert to CSV
python sonar_cli.py convert Sonar000.RSD

# Generate 3D visualization
python sonar_cli.py convert sonar_data.csv --maps ply

# Analyze bathymetry
python sonar_cli.py heatmap sonar_data.csv --depth

# View results in CloudCompare or Blender
```

---

### Workflow 3: Fish Population Monitoring

```bash
# Detect fish
python sonar_cli.py fish detect sonar_data.csv

# Analyze population
python sonar_cli.py health fish_detections.geojson --report

# Create dashboard
python sonar_cli.py dashboard sonar_data.csv --detections fish_detections.geojson
```

---

### Workflow 4: Track Navigation

```bash
# Generate navigation tracks
python sonar_cli.py convert Sonar000.RSD --maps geojson kml gpx

# Import to GPS device
# Open sonar_data_map.kml in Google Earth

# Or import to Garmin device
# Load sonar_data_map.gpx into Garmin BaseCamp
```

---

## Data Interpretation Guide

### Understanding Health Scores

**Excellent (>75):**
- Abundant fish population
- Good diversity in sizes
- High activity levels
- Healthy ecosystem

**Good (60-75):**
- Stable fish population
- Adequate diversity
- Reasonable activity
- Well-managed area

**Fair (45-60):**
- Moderate fish population
- Limited diversity
- Variable activity
- Monitor closely

**Poor (<45):**
- Low fish population
- Limited diversity
- Low activity
- Need conservation action

### Reading Intensity Values

- **0-40**: Empty water or noise
- **40-80**: Small individual fish
- **80-120**: Medium fish or loose groups
- **120-200**: Large fish or schools
- **>200**: Likely seafloor/structures (saturated signal)

### Depth Distribution Interpretation

- Fish concentration at specific depths = behavior preference
- Wide distribution = mobile population
- Changes between surveys = seasonal migration

---

## File Formats Reference

| Format | Best For | Tools |
|--------|----------|-------|
| CSV | Data analysis, spreadsheets | Excel, Python, R |
| PLY | 3D visualization | CloudCompare, Meshlab, Blender |
| GeoJSON | Web mapping | Leaflet, Mapbox, Google Maps, ArcGIS |
| KML | Google Earth, navigation | Google Earth Pro, BaseCamp |
| GPX | GPS devices | Garmin, most navigation apps |
| HTML | Public sharing | Any web browser |
| Markdown | Reports, documentation | Any text editor, web renderers |

---

## Advanced Tips

### Custom Grid Size for Heatmaps

```bash
# Finer detail (smaller area, more zoomed in)
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.005

# Less detail (larger area, more zoomed out)
python sonar_cli.py heatmap sonar_data.csv --intensity --grid-size 0.02
```

### Adjusting Fish Detection Sensitivity

```bash
# Find more fish (including smaller ones)
python sonar_cli.py fish detect sonar_data.csv --min-intensity 30

# Find only large fish/schools
python sonar_cli.py fish detect sonar_data.csv --min-intensity 80
```

### Faster Processing

```bash
# Coarser stride during conversion = faster processing, less detail
python sonar_cli.py convert Sonar000.RSD --stride 512

# Finer stride = slower processing, more detail
python sonar_cli.py convert Sonar000.RSD --stride 128
```

---

## Troubleshooting

**No fish detected?**
- Adjust intensity thresholds: `--min-intensity 30 --max-intensity 250`
- Verify sonar data quality with: `python sonar_cli.py analyze sonar_data.csv`

**Dashboard won't open in browser?**
- Make sure you use the full file path: `file:///full/path/to/dashboard.html`
- Try a different browser (Chrome, Firefox, Edge)

**Heatmap grid too coarse/fine?**
- Adjust `--grid-size` parameter up (less detail) or down (more detail)

**CSV file too large?**
- Use larger `--stride` value during conversion for faster processing

---

## API Usage (For Developers)

```python
from heatmap_generator import HeatmapGenerator
from fish_detection import FishDetector
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer

# Generate intensity heatmap
heatmap_file = HeatmapGenerator.create_intensity_heatmap('sonar_data.csv')

# Detect fish
detections_file, detections = FishDetector.detect_fish('sonar_data.csv')

# Analyze population
metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)

# Create dashboard
dashboard_file = WebVisualizer.create_dashboard(
    detections_file, 
    metrics,
    location_name="My Lake"
)
```

---

## Performance Notes

- **CSV Conversion**: ~1-2 seconds per 10MB RSD file
- **Heatmap Generation**: ~5-10 seconds per 10MB CSV
- **Fish Detection**: ~10-20 seconds for 1M+ data points
- **Population Analysis**: <1 second
- **Dashboard Generation**: ~2-5 seconds

Processing times vary by data size and system specifications.

---

**For questions or issues, check the main README.md or open an issue on GitHub.**
