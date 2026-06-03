#!/usr/bin/env python3
"""
CLI tool for Garmin Sonar RSD conversion and analysis
Enhanced with heatmap generation, fish detection, and population health analytics
"""

import argparse
import sys
import logging
import csv
from pathlib import Path

from sonar_converter_streaming import convert_sonar_rsd_to_csv
from analysis_tools import MapGenerator
from heatmap_generator import HeatmapGenerator
from fish_detection import FishDetector
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Complete Sonar Analysis Platform: Convert, Map, Detect Fish, Analyze Population Health',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Convert sonar file to CSV
  python sonar_cli.py convert Sonar000.RSD
  
  # Convert and generate all visualizations
  python sonar_cli.py convert Sonar000.RSD --maps all
  
  # Generate heatmaps from CSV
  python sonar_cli.py heatmap sonar_data.csv --all
  
  # Detect fish and create population report
  python sonar_cli.py fish detect sonar_data.csv --location "Lake Superior"
  
  # Create web dashboard
  python sonar_cli.py dashboard sonar_data.csv --location "Lake Superior"
  
  # Full pipeline: convert, analyze, detect, and visualize
  python sonar_cli.py pipeline Sonar000.RSD --location "Lake Superior"
        '''
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Convert command
    convert_cmd = subparsers.add_parser('convert', help='Convert Sonar RSD to CSV')
    convert_cmd.add_argument('input', help='Input Sonar RSD file')
    convert_cmd.add_argument('-o', '--output', help='Output CSV file')
    convert_cmd.add_argument('--stride', type=int, default=256,
                           help='Sample every N bytes (default: 256)')
    convert_cmd.add_argument('--maps', nargs='+', choices=['ply', 'all', 'geojson', 'kml', 'gpx'],
                           help='Generate export formats')
    
    # Analyze command
    analyze_cmd = subparsers.add_parser('analyze', help='Analyze CSV file')
    analyze_cmd.add_argument('input', help='Input CSV file')
    
    # Heatmap command
    heatmap_cmd = subparsers.add_parser('heatmap', help='Generate heatmaps from CSV')
    heatmap_cmd.add_argument('input', help='Input CSV file')
    heatmap_cmd.add_argument('--intensity', action='store_true', help='Generate intensity heatmap')
    heatmap_cmd.add_argument('--depth', action='store_true', help='Generate depth heatmap')
    heatmap_cmd.add_argument('--temperature', action='store_true', help='Generate temperature heatmap')
    heatmap_cmd.add_argument('--all', action='store_true', help='Generate all heatmaps')
    heatmap_cmd.add_argument('--grid-size', type=float, default=0.01, 
                            help='Grid cell size in degrees (default: 0.01 ≈ 1km)')
    
    # Fish detection command
    fish_cmd = subparsers.add_parser('fish', help='Fish detection and analysis')
    fish_sub = fish_cmd.add_subparsers(dest='fish_command')
    
    detect_cmd = fish_sub.add_parser('detect', help='Detect fish from sonar data')
    detect_cmd.add_argument('input', help='Input CSV file')
    detect_cmd.add_argument('--min-intensity', type=int, default=40,
                           help='Minimum sonar intensity (default: 40)')
    detect_cmd.add_argument('--max-intensity', type=int, default=200,
                           help='Maximum sonar intensity (default: 200)')
    
    # Population health command
    health_cmd = subparsers.add_parser('health', help='Population health analysis')
    health_cmd.add_argument('input', help='Fish detections GeoJSON file')
    health_cmd.add_argument('--location', default='Fishing Area',
                           help='Location name (default: Fishing Area)')
    health_cmd.add_argument('--report', action='store_true',
                           help='Generate markdown report')
    
    # Dashboard command
    dashboard_cmd = subparsers.add_parser('dashboard', help='Create web dashboard')
    dashboard_cmd.add_argument('csv_file', help='Input sonar CSV file')
    dashboard_cmd.add_argument('--detections', help='Optional: fish detections GeoJSON file')
    dashboard_cmd.add_argument('--location', default='Fishing Survey Area',
                              help='Location name')
    
    # Pipeline command
    pipeline_cmd = subparsers.add_parser('pipeline', help='Full analysis pipeline')
    pipeline_cmd.add_argument('input', help='Input Sonar RSD file')
    pipeline_cmd.add_argument('--location', default='Survey Area',
                             help='Location name for reports')
    pipeline_cmd.add_argument('--stride', type=int, default=256,
                             help='Conversion stride (default: 256)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    try:
        if args.command == 'convert':
            return cmd_convert(args)
        elif args.command == 'analyze':
            return cmd_analyze(args)
        elif args.command == 'heatmap':
            return cmd_heatmap(args)
        elif args.command == 'fish':
            return cmd_fish(args)
        elif args.command == 'health':
            return cmd_health(args)
        elif args.command == 'dashboard':
            return cmd_dashboard(args)
        elif args.command == 'pipeline':
            return cmd_pipeline(args)
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    
    return 0


def cmd_convert(args):
    """Execute convert command"""
    input_file = Path(args.input)
    output_file = Path(args.output) if args.output else None
    
    logger.info(f"Converting {input_file}...")
    csv_file, frame_count = convert_sonar_rsd_to_csv(input_file, output_file, stride=args.stride)
    
    print(f"✓ Conversion complete!")
    print(f"  Output: {csv_file}")
    print(f"  Frames extracted: {frame_count:,}")
    print(f"  File size: {csv_file.stat().st_size / 1024 / 1024:.1f} MB")

    if args.maps:
        formats = ['ply', 'geojson', 'kml', 'gpx'] if 'all' in args.maps else args.maps
        logger.info(f"Generating exports: {formats}")
        
        for fmt in formats:
            if fmt == 'ply':
                MapGenerator.create_ply(csv_file)
                print(f"✓ PLY 3D point cloud generated")
            elif fmt == 'geojson':
                MapGenerator.create_geojson(csv_file)
                print(f"✓ GeoJSON generated")
            elif fmt == 'kml':
                MapGenerator.create_kml(csv_file)
                print(f"✓ KML generated")
            elif fmt == 'gpx':
                MapGenerator.create_gpx(csv_file)
                print(f"✓ GPX generated")

    return 0


def cmd_analyze(args):
    """Execute analyze command"""
    csv_file = Path(args.input)
    
    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return 1
    
    logger.info(f"Analyzing {csv_file}...")
    
    # Analyze CSV
    depths = []
    temps = []
    frequencies = []
    lats = []
    lons = []
    total_rows = 0
    
    try:
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_rows += 1
                
                try:
                    if row.get('depth_m') and row['depth_m'] != '':
                        depths.append(float(row['depth_m']))
                    if row.get('water_temp_c') and row['water_temp_c'] != '':
                        temps.append(float(row['water_temp_c']))
                    if row.get('sonar_frequency_khz') and row['sonar_frequency_khz'] != '':
                        frequencies.append(float(row['sonar_frequency_khz']))
                    if row.get('latitude') and row['latitude'] != '':
                        lats.append(float(row['latitude']))
                    if row.get('longitude') and row['longitude'] != '':
                        lons.append(float(row['longitude']))
                except (ValueError, TypeError):
                    continue
        
        print("\n=== Sonar Survey Analysis ===")
        print(f"Total Frames: {total_rows:,}")
        print(f"File Size: {csv_file.stat().st_size / 1024 / 1024:.1f} MB")
        
        print(f"\nDepth Data:")
        print(f"  Records: {len(depths):,}")
        if depths:
            print(f"  Range: {min(depths):.1f}m - {max(depths):.1f}m")
            print(f"  Average: {sum(depths)/len(depths):.1f}m")
            print(f"  Median: {sorted(depths)[len(depths)//2]:.1f}m")
        
        print(f"\nWater Temperature:")
        print(f"  Records: {len(temps):,}")
        if temps:
            print(f"  Range: {min(temps):.1f}°C - {max(temps):.1f}°C")
            print(f"  Average: {sum(temps)/len(temps):.1f}°C")
        
        print(f"\nSonar Frequency:")
        print(f"  Records: {len(frequencies):,}")
        if frequencies:
            freq_set = set(round(f) for f in frequencies)
            print(f"  Unique values: {len(freq_set)}")
            print(f"  Range: {min(frequencies):.0f} - {max(frequencies):.0f} kHz")
        
        print(f"\nGPS Coverage:")
        print(f"  Latitude records: {len(lats):,}")
        print(f"  Longitude records: {len(lons):,}")
        if lats:
            print(f"  Lat range: {min(lats):.6f} - {max(lats):.6f}")
        if lons:
            print(f"  Lon range: {min(lons):.6f} - {max(lons):.6f}")
        
    except Exception as e:
        logger.error(f"Error analyzing CSV: {e}")
        return 1
    
    return 0


def cmd_heatmap(args):
    """Execute heatmap command"""
    csv_file = Path(args.input)
    
    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return 1
    
    print(f"✓ Generating heatmaps from {csv_file}...")
    
    outputs = []
    
    if args.all or args.intensity:
        output = HeatmapGenerator.create_intensity_heatmap(csv_file, grid_size=args.grid_size)
        outputs.append(output)
        print(f"  ✓ Intensity heatmap: {output}")
    
    if args.all or args.depth:
        output = HeatmapGenerator.create_depth_heatmap(csv_file)
        outputs.append(output)
        print(f"  ✓ Depth heatmap: {output}")
    
    if args.all or args.temperature:
        output = HeatmapGenerator.create_temperature_heatmap(csv_file)
        outputs.append(output)
        print(f"  ✓ Temperature heatmap: {output}")
    
    if not outputs:
        print("  ⚠ No heatmap type specified. Use --all or --intensity/--depth/--temperature")
    
    return 0


def cmd_fish(args):
    """Execute fish detection command"""
    if not args.fish_command:
        print("Fish command requires subcommand: detect")
        return 1
    
    if args.fish_command == 'detect':
        csv_file = Path(args.input)
        
        if not csv_file.exists():
            logger.error(f"File not found: {csv_file}")
            return 1
        
        print(f"🐟 Detecting fish from {csv_file}...")
        
        output_file, detections = FishDetector.detect_fish(
            csv_file,
            min_intensity=args.min_intensity,
            max_intensity=args.max_intensity
        )
        
        print(f"\n✓ Fish detection complete!")
        print(f"  Total detections: {len(detections):,}")
        print(f"  Output: {output_file}")
        
        return 0
    
    return 0


def cmd_health(args):
    """Execute population health command"""
    detection_file = Path(args.input)
    
    if not detection_file.exists():
        logger.error(f"File not found: {detection_file}")
        return 1
    
    print(f"📊 Analyzing population health from {detection_file}...")
    
    metrics = PopulationHealthAnalytics.analyze_population_metrics(detection_file)
    
    print(f"\n✓ Population analysis complete!")
    print(f"  Total detections: {metrics.get('total_detections', 0):,}")
    
    health = metrics.get('health_indicators', {})
    print(f"  Overall Health: {health.get('overall_status', 'Unknown')} ({health.get('overall_health_score', 0)}/100)")
    
    if args.report:
        report_file = PopulationHealthAnalytics.generate_public_report(
            metrics,
            location_name=args.location
        )
        print(f"  Report: {report_file}")
    
    return 0


def cmd_dashboard(args):
    """Execute dashboard command"""
    csv_file = Path(args.csv_file)
    
    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return 1
    
    detections_file = Path(args.detections) if args.detections else None
    
    if detections_file and not detections_file.exists():
        print(f"⚠ Warning: Detections file not found: {detections_file}")
        detections_file = None
    
    # If no detections provided, generate them
    if not detections_file:
        print("📍 Generating fish detections...")
        detections_file, _ = FishDetector.detect_fish(csv_file)
    
    # Analyze population
    print("📊 Analyzing population health...")
    metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
    
    # Create dashboard
    print("🌐 Creating web dashboard...")
    dashboard_file = WebVisualizer.create_dashboard(
        detections_file,
        metrics,
        location_name=args.location
    )
    
    print(f"\n✓ Dashboard created!")
    print(f"  Open in browser: file://{dashboard_file.absolute()}")
    
    return 0


def cmd_pipeline(args):
    """Execute full analysis pipeline"""
    input_file = Path(args.input)
    
    print("🚀 Starting full analysis pipeline...\n")
    
    # Step 1: Convert RSD to CSV
    print("Step 1: Converting RSD to CSV...")
    csv_file, frame_count = convert_sonar_rsd_to_csv(input_file, stride=args.stride)
    print(f"  ✓ CSV created: {csv_file}")
    print(f"  ✓ Frames: {frame_count:,}\n")
    
    # Step 2: Generate visualizations
    print("Step 2: Generating map visualizations...")
    ply_file = MapGenerator.create_ply(csv_file)
    print(f"  ✓ 3D PLY: {ply_file}")
    geojson_file = MapGenerator.create_geojson(csv_file)
    print(f"  ✓ GeoJSON: {geojson_file}\n")
    
    # Step 3: Generate heatmaps
    print("Step 3: Generating heatmaps...")
    intensity_hm = HeatmapGenerator.create_intensity_heatmap(csv_file)
    print(f"  ✓ Intensity: {intensity_hm}")
    depth_hm = HeatmapGenerator.create_depth_heatmap(csv_file)
    print(f"  ✓ Depth: {depth_hm}\n")
    
    # Step 4: Detect fish
    print("Step 4: Detecting fish populations...")
    detections_file, detections = FishDetector.detect_fish(csv_file)
    print(f"  ✓ Detections: {len(detections):,}")
    print(f"  ✓ File: {detections_file}\n")
    
    # Step 5: Analyze population health
    print("Step 5: Analyzing population health...")
    metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
    health = metrics.get('health_indicators', {})
    print(f"  ✓ Health Score: {health.get('overall_health_score', 0)}/100")
    print(f"  ✓ Status: {health.get('overall_status', 'Unknown')}\n")
    
    # Step 6: Generate reports
    print("Step 6: Generating reports...")
    report_file = PopulationHealthAnalytics.generate_public_report(
        metrics,
        location_name=args.location
    )
    print(f"  ✓ Public Report: {report_file}\n")
    
    # Step 7: Create web dashboard
    print("Step 7: Creating web dashboard...")
    dashboard_file = WebVisualizer.create_dashboard(
        detections_file,
        metrics,
        location_name=args.location
    )
    print(f"  ✓ Dashboard: {dashboard_file}\n")
    
    print("=" * 60)
    print("✅ PIPELINE COMPLETE!")
    print("=" * 60)
    print("\nGenerated Files:")
    print(f"  CSV Data: {csv_file}")
    print(f"  3D Visualization: {ply_file}")
    print(f"  Interactive Maps: {geojson_file}")
    print(f"  Intensity Heatmap: {intensity_hm}")
    print(f"  Depth Heatmap: {depth_hm}")
    print(f"  Fish Detections: {detections_file}")
    print(f"  Health Report: {report_file}")
    print(f"  Web Dashboard: {dashboard_file}")
    print(f"\nOpen dashboard in browser: file://{dashboard_file.absolute()}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
