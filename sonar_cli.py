#!/usr/bin/env python3
"""
CLI tool for Garmin Sonar RSD conversion and analysis.

Entry point for all user-facing workflows. Conversion delegates to PINGVerter
(via pingverter_adapter / sonar_converter_streaming); downstream commands
(heatmap, fish, dashboard, merge, compare) operate on normalized CSV.

Run ``python sonar_cli.py --help`` or see README.md for the full command list.
"""

import argparse
import sys
import logging
import csv
from pathlib import Path

from sonar_converter_streaming import convert_sonar_rsd_to_csv, validate_rsd_file, format_validation_report
from analysis_tools import MapGenerator
from heatmap_generator import HeatmapGenerator
from fish_detection import FishDetector
from population_health import PopulationHealthAnalytics
from web_visualizer import WebVisualizer
from survey_tools import merge_csv_files, compare_surveys, compute_track_quality, format_quality_report
from export_tools import generate_map_exports
from sonar_playback import generate_playback
from batch_processor import (
    batch_convert,
    batch_pipeline,
    discover_rsd_files,
    format_batch_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _resolve_nchunk(args) -> int:
    """Resolve PINGVerter nchunk from CLI args (--stride is deprecated alias)."""
    stride = getattr(args, 'stride', None)
    if stride is not None:
        return stride
    nchunk = getattr(args, 'nchunk', None)
    if nchunk is not None:
        return nchunk
    return 500


def main():
    parser = argparse.ArgumentParser(
        description='Convert Garmin Sonar RSD files and generate maps, heatmaps, and reports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Convert sonar file to CSV
  python sonar_cli.py convert Sonar000.RSD
  
  # Convert and generate all map exports
  python sonar_cli.py convert Sonar000.RSD --maps all

  # Generate heatmaps from an existing CSV
  python sonar_cli.py heatmap sonar_data.csv --all

  # Detect fish signatures and create a health report
  python sonar_cli.py fish detect sonar_data.csv
  python sonar_cli.py fish schools sonar_data.csv
  python sonar_cli.py fish aggregate sonar_data.csv --grid-size 0.01

  # Merge surveys or compare bathymetry changes
  python sonar_cli.py merge survey_a.csv survey_b.csv -o combined.csv
  python sonar_cli.py compare before.csv after.csv

  # Validate RSD before converting
  python sonar_cli.py convert Sonar000.RSD --validate

  # Export GeoTIFF bathymetry or LAS point cloud
  python sonar_cli.py convert Sonar000.RSD --maps geotiff las
  python sonar_cli.py heatmap sonar_data.csv --depth --contours --interval 1.0

  # Interactive seabed + fish survey map
  python sonar_cli.py map sonar_data.csv --location "Lake Survey"

  # Bulk convert every RSD in a folder
  python sonar_cli.py batch convert ./recordings --output-dir ./exports --maps all

  # Bulk full pipeline on multiple files
  python sonar_cli.py batch pipeline Sonar001.RSD Sonar002.RSD --location "Lake Survey"

  # Web upload UI (drag-and-drop, multiple files)
  python sonar_cli.py upload

  # Live-style sonar playback video or HTML player
  python sonar_cli.py playback Sonar000.RSD --output sonar.mp4
  python sonar_cli.py playback Sonar000.RSD --format html --output sonar.html
        '''
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Convert command
    convert_cmd = subparsers.add_parser('convert', help='Convert Sonar RSD to CSV')
    convert_cmd.add_argument(
        'input', nargs='+',
        help='One or more RSD files, directories, or glob patterns (e.g. *.RSD)',
    )
    convert_cmd.add_argument('-o', '--output', help='Output CSV file (single input only)')
    convert_cmd.add_argument(
        '--output-dir', type=Path,
        help='Output directory when converting multiple files or a folder',
    )
    convert_cmd.add_argument(
        '--no-recursive', action='store_true',
        help='When input is a directory, do not search subfolders',
    )
    convert_cmd.add_argument('--stride', type=int, default=None,
                           help='Deprecated alias for --nchunk')
    convert_cmd.add_argument('--nchunk', type=int, default=500,
                           help='PINGVerter chunk size (default: 500)')
    convert_cmd.add_argument(
        '--validate', action='store_true',
        help='Scan RSD file and report field validity without converting',
    )
    convert_cmd.add_argument('--maps', nargs='+',
                           choices=['ply', 'geojson', 'kml', 'gpx', 'geotiff', 'tif', 'las', 'laz', 'all'],
                           help='Generate map export formats')
    
    # Analyze command
    analyze_cmd = subparsers.add_parser('analyze', help='Analyze CSV file')
    analyze_cmd.add_argument('input', help='Input CSV file')
    analyze_cmd.add_argument(
        '--quality', action='store_true',
        help='Include GPS track quality score and warnings',
    )

    # Heatmap command
    heatmap_cmd = subparsers.add_parser('heatmap', help='Generate heatmaps from CSV')
    heatmap_cmd.add_argument('input', help='Input CSV file')
    heatmap_cmd.add_argument('--intensity', action='store_true', help='Generate intensity heatmap')
    heatmap_cmd.add_argument('--depth', action='store_true', help='Generate depth heatmap')
    heatmap_cmd.add_argument('--temperature', action='store_true', help='Generate temperature heatmap')
    heatmap_cmd.add_argument('--all', action='store_true', help='Generate all heatmaps')
    heatmap_cmd.add_argument('--contours', action='store_true', help='Generate depth contour lines (GeoJSON)')
    heatmap_cmd.add_argument('--interval', type=float, default=1.0,
                            help='Contour interval in meters (default: 1.0)')
    heatmap_cmd.add_argument('--grid-size', type=float, default=0.01,
                            help='Grid cell size in degrees for all heatmap types (default: 0.01)')

    # Fish detection command
    fish_cmd = subparsers.add_parser('fish', help='Fish detection and analysis')
    fish_sub = fish_cmd.add_subparsers(dest='fish_command')
    detect_cmd = fish_sub.add_parser('detect', help='Detect fish from sonar data')
    detect_cmd.add_argument('input', help='Input CSV file')
    detect_cmd.add_argument('--min-intensity', type=int, default=40,
                           help='Minimum sonar intensity (default: 40)')
    detect_cmd.add_argument('--max-intensity', type=int, default=200,
                           help='Maximum sonar intensity (default: 200)')

    schools_cmd = fish_sub.add_parser('schools', help='Identify and export fish schools')
    schools_cmd.add_argument('input', help='Input CSV file')
    schools_cmd.add_argument('-o', '--output', help='Output GeoJSON file')
    schools_cmd.add_argument('--proximity', type=float, default=0.01,
                            help='Cluster proximity in degrees (default: 0.01)')
    schools_cmd.add_argument('--min-intensity', type=int, default=40)
    schools_cmd.add_argument('--max-intensity', type=int, default=200)

    aggregate_cmd = fish_sub.add_parser('aggregate', help='Aggregate fish detections by grid cell')
    aggregate_cmd.add_argument('input', help='Input CSV file')
    aggregate_cmd.add_argument('-o', '--output', help='Output GeoJSON file')
    aggregate_cmd.add_argument('--grid-size', type=float, default=0.01,
                              help='Grid cell size in degrees (default: 0.01)')
    aggregate_cmd.add_argument('--min-intensity', type=int, default=40)
    aggregate_cmd.add_argument('--max-intensity', type=int, default=200)

    # Population health command
    health_cmd = subparsers.add_parser('health', help='Population health analysis')
    health_cmd.add_argument('input', help='Fish detections GeoJSON file')
    health_cmd.add_argument('--location', default='Fishing Area',
                           help='Location name (default: Fishing Area)')
    health_cmd.add_argument('--report', action='store_true',
                           help='Generate markdown report')

    # Dashboard command
    dashboard_cmd = subparsers.add_parser('dashboard', help='Create an HTML dashboard')
    dashboard_cmd.add_argument('csv_file', help='Input sonar CSV file')
    dashboard_cmd.add_argument('--detections', help='Optional fish detections GeoJSON file')
    dashboard_cmd.add_argument('--location', default='Fishing Survey Area',
                              help='Location name')
    dashboard_cmd.add_argument('--depth-heatmap',
                              help='Optional seabed/bathymetry GeoJSON (auto-generated from CSV if omitted)')
    dashboard_cmd.add_argument('--grid-size', type=float, default=0.01,
                              help='Grid size for auto-generated depth heatmap (default: 0.01)')

    # Survey map command (seabed + fish focused HTML)
    map_cmd = subparsers.add_parser('map', help='Create seabed + fish survey map HTML')
    map_cmd.add_argument('csv_file', help='Input sonar CSV file')
    map_cmd.add_argument('--detections', help='Optional fish detections GeoJSON')
    map_cmd.add_argument('--depth-heatmap', help='Optional depth/bathymetry GeoJSON')
    map_cmd.add_argument('--location', default='Sonar Survey', help='Location name')
    map_cmd.add_argument('--grid-size', type=float, default=0.01,
                        help='Grid size for bathymetry layer (default: 0.01)')

    # Pipeline command
    pipeline_cmd = subparsers.add_parser('pipeline', help='Run the full sonar analysis workflow')
    pipeline_cmd.add_argument(
        'input', nargs='+',
        help='One or more RSD files, directories, or glob patterns',
    )
    pipeline_cmd.add_argument(
        '--location', default=None,
        help='Location name for reports (default: Survey Area, or file name in batch)',
    )
    pipeline_cmd.add_argument('--stride', type=int, default=None,
                             help='Deprecated alias for --nchunk')
    pipeline_cmd.add_argument('--nchunk', type=int, default=500,
                             help='PINGVerter chunk size (default: 500)')
    pipeline_cmd.add_argument(
        '--output-dir', type=Path,
        help='Write CSV and outputs into this directory (batch / multi-file)',
    )
    pipeline_cmd.add_argument(
        '--no-recursive', action='store_true',
        help='When input is a directory, do not search subfolders',
    )

    # Batch command (explicit bulk workflows)
    batch_cmd = subparsers.add_parser(
        'batch', help='Bulk convert or analyze multiple RSD files',
    )
    batch_sub = batch_cmd.add_subparsers(dest='batch_command')

    batch_convert_cmd = batch_sub.add_parser('convert', help='Bulk convert RSD files to CSV')
    batch_convert_cmd.add_argument(
        'sources', nargs='+',
        help='RSD files, directories, or glob patterns',
    )
    batch_convert_cmd.add_argument(
        '--output-dir', type=Path,
        help='Directory for CSV and map outputs (default: next to each RSD)',
    )
    batch_convert_cmd.add_argument('--stride', type=int, default=None,
                                   help='Deprecated alias for --nchunk')
    batch_convert_cmd.add_argument('--nchunk', type=int, default=500)
    batch_convert_cmd.add_argument(
        '--maps', nargs='+',
        choices=['ply', 'geojson', 'kml', 'gpx', 'geotiff', 'tif', 'las', 'laz', 'all'],
        help='Generate map exports for each file',
    )
    batch_convert_cmd.add_argument(
        '--no-recursive', action='store_true',
        help='Do not search subdirectories when a source is a folder',
    )
    batch_convert_cmd.add_argument(
        '--fail-fast', action='store_true',
        help='Stop on first conversion error',
    )

    batch_pipeline_cmd = batch_sub.add_parser(
        'pipeline', help='Run full pipeline on each RSD file',
    )
    batch_pipeline_cmd.add_argument('sources', nargs='+')
    batch_pipeline_cmd.add_argument('--output-dir', type=Path)
    batch_pipeline_cmd.add_argument('--location', default=None)
    batch_pipeline_cmd.add_argument('--stride', type=int, default=None)
    batch_pipeline_cmd.add_argument('--nchunk', type=int, default=500)
    batch_pipeline_cmd.add_argument('--no-recursive', action='store_true')
    batch_pipeline_cmd.add_argument('--fail-fast', action='store_true')

    batch_list_cmd = batch_sub.add_parser('list', help='List RSD files that would be processed')
    batch_list_cmd.add_argument('sources', nargs='+')
    batch_list_cmd.add_argument('--no-recursive', action='store_true')

    merge_cmd = subparsers.add_parser('merge', help='Merge multiple sonar CSV files')
    merge_cmd.add_argument('inputs', nargs='+', help='CSV files to merge')
    merge_cmd.add_argument('-o', '--output', help='Output merged CSV path')

    compare_cmd = subparsers.add_parser(
        'compare', help='Compare bathymetry between two survey CSV files',
    )
    compare_cmd.add_argument('survey_a', help='Baseline survey CSV')
    compare_cmd.add_argument('survey_b', help='Comparison survey CSV')
    compare_cmd.add_argument('-o', '--output', help='Output GeoJSON diff file')
    compare_cmd.add_argument('--grid-size', type=float, default=0.01,
                            help='Grid cell size in degrees (default: 0.01)')

    # Sonar playback (live-style scrolling echogram)
    playback_cmd = subparsers.add_parser(
        'playback', help='Render live-style scrolling sonar playback (MP4, GIF, or HTML)',
    )
    playback_cmd.add_argument('input', type=str, help='Input RSD file')
    playback_cmd.add_argument('-o', '--output', type=str, help='Output file (.mp4, .gif, or .html)')
    playback_cmd.add_argument(
        '--format', choices=['auto', 'mp4', 'gif', 'html'], default='auto',
        help='Output format (default: auto from extension or ffmpeg availability)',
    )
    playback_cmd.add_argument('--channel', type=int, default=None, help='RSD channel id (default: best down-looking beam)')
    playback_cmd.add_argument('--nchunk', type=int, default=500, help='PINGVerter chunk size')
    playback_cmd.add_argument('--fps', type=float, default=10.0, help='Video/GIF frame rate')
    playback_cmd.add_argument('--width', type=int, default=960, help='Frame width in pixels')
    playback_cmd.add_argument('--height', type=int, default=540, help='Frame height in pixels')
    playback_cmd.add_argument(
        '--window', type=int, default=400, dest='window_pings',
        help='Number of pings visible in the scrolling window',
    )
    playback_cmd.add_argument(
        '--frame-step', type=int, default=1,
        help='Advance this many pings per video frame (speeds up long recordings)',
    )
    playback_cmd.add_argument(
        '--max-pings', type=int, default=None,
        help='Limit pings loaded (useful for HTML preview of large files)',
    )
    playback_cmd.add_argument('--no-hud', action='store_true', help='Hide telemetry overlay in video/GIF')
    playback_cmd.add_argument('--no-bottom-line', action='store_true', help='Hide bottom depth track line')

    # Upload web UI
    upload_cmd = subparsers.add_parser(
        'upload', help='Start local web UI for drag-and-drop RSD upload',
    )
    upload_cmd.add_argument('--host', default='127.0.0.1')
    upload_cmd.add_argument('--port', type=int, default=8765)
    upload_cmd.add_argument('--uploads-dir', type=Path, default=Path('uploads'))
    upload_cmd.add_argument('--output-dir', type=Path, default=Path('output'))
    
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
        elif args.command == 'map':
            return cmd_map(args)
        elif args.command == 'pipeline':
            return cmd_pipeline(args)
        elif args.command == 'batch':
            return cmd_batch(args)
        elif args.command == 'merge':
            return cmd_merge(args)
        elif args.command == 'compare':
            return cmd_compare(args)
        elif args.command == 'upload':
            return cmd_upload(args)
        elif args.command == 'playback':
            return cmd_playback(args)
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    
    return 0


def cmd_convert(args):
    """Execute convert command (single or multiple RSD inputs)."""
    sources = args.input
    if len(sources) > 1 or Path(sources[0]).is_dir() or any('*' in s or '?' in s for s in sources):
        summary = batch_convert(
            sources,
            output_dir=getattr(args, 'output_dir', None),
            nchunk=_resolve_nchunk(args),
            map_formats=args.maps,
            recursive=not getattr(args, 'no_recursive', False),
        )
        print(format_batch_summary(summary))
        return 0 if summary.failed == 0 else 1

    input_file = Path(sources[0])

    if getattr(args, 'validate', False):
        report = validate_rsd_file(input_file, nchunk=_resolve_nchunk(args))
        print(format_validation_report(report))
        return 0 if report['overall_score'] >= 50 else 1

    logger.info(f"Converting {input_file}...")
    output_file = Path(args.output) if args.output else None
    csv_file, frame_count = convert_sonar_rsd_to_csv(
        input_file, output_file, nchunk=_resolve_nchunk(args),
    )

    print(f"✓ Conversion complete!")
    print(f"  Output: {csv_file}")
    print(f"  Frames extracted: {frame_count:,}")
    print(f"  File size: {csv_file.stat().st_size / 1024 / 1024:.1f} MB")

    if args.maps:
        _generate_map_exports(csv_file, args.maps)

    return 0


def _generate_map_exports(csv_file: Path, map_formats: list) -> None:
    """Generate requested map/point-cloud export formats from CSV."""
    for path in generate_map_exports(csv_file, map_formats):
        print(f"✓ Export: {path}")


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

        if getattr(args, 'quality', False):
            quality = compute_track_quality(csv_file)
            print(format_quality_report(quality))
        
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

    outputs = []

    if args.all or args.intensity:
        output = HeatmapGenerator.create_intensity_heatmap(csv_file, grid_size=args.grid_size)
        outputs.append(output)
        print(f"✓ Intensity heatmap: {output}")

    if args.all or args.depth:
        output = HeatmapGenerator.create_depth_heatmap(csv_file, grid_size=args.grid_size)
        outputs.append(output)
        print(f"✓ Depth heatmap: {output}")

    if args.all or args.temperature:
        output = HeatmapGenerator.create_temperature_heatmap(csv_file, grid_size=args.grid_size)
        outputs.append(output)
        print(f"✓ Temperature heatmap: {output}")

    if args.contours or args.all:
        output = HeatmapGenerator.create_depth_contours(
            csv_file,
            interval_m=args.interval,
            grid_size=args.grid_size,
        )
        outputs.append(output)
        print(f"✓ Depth contours: {output}")

    if not outputs:
        print("No heatmap type specified. Use --all or --intensity/--depth/--temperature.")

    return 0


def cmd_fish(args):
    """Execute fish detection command"""
    if not args.fish_command:
        print("Fish command requires a subcommand. Use: fish detect | schools | aggregate")
        return 1

    if args.fish_command == 'detect':
        csv_file = Path(args.input)

        if not csv_file.exists():
            logger.error(f"File not found: {csv_file}")
            return 1

        output_file, detections = FishDetector.detect_fish(
            csv_file,
            min_intensity=args.min_intensity,
            max_intensity=args.max_intensity,
        )

        print("✓ Fish detection complete!")
        print(f"  Total detections: {len(detections):,}")
        print(f"  Output: {output_file}")

    elif args.fish_command == 'schools':
        csv_file = Path(args.input)
        if not csv_file.exists():
            logger.error(f"File not found: {csv_file}")
            return 1

        _, detections = FishDetector.detect_fish(
            csv_file,
            min_intensity=args.min_intensity,
            max_intensity=args.max_intensity,
        )
        output = Path(args.output) if args.output else csv_file.with_name(
            f"{csv_file.stem}_fish_schools.geojson"
        )
        schools_file = FishDetector.export_fish_schools_geojson(
            detections, output, proximity_threshold=args.proximity,
        )
        schools = FishDetector.detect_fish_schools(detections, args.proximity)
        print("✓ Fish schools export complete!")
        print(f"  Schools identified: {len(schools):,}")
        print(f"  Output: {schools_file}")

    elif args.fish_command == 'aggregate':
        csv_file = Path(args.input)
        if not csv_file.exists():
            logger.error(f"File not found: {csv_file}")
            return 1

        _, detections = FishDetector.detect_fish(
            csv_file,
            min_intensity=args.min_intensity,
            max_intensity=args.max_intensity,
        )
        output = Path(args.output) if args.output else csv_file.with_name(
            f"{csv_file.stem}_fish_aggregate.geojson"
        )
        agg_file = FishDetector.export_fish_aggregate_geojson(
            detections, output, grid_size=args.grid_size,
        )
        aggregated = FishDetector.aggregate_fish_by_location(detections, args.grid_size)
        print("✓ Fish aggregate export complete!")
        print(f"  Grid cells: {len(aggregated):,}")
        print(f"  Output: {agg_file}")

    return 0


def cmd_health(args):
    """Execute population health command"""
    detection_file = Path(args.input)

    if not detection_file.exists():
        logger.error(f"File not found: {detection_file}")
        return 1

    metrics = PopulationHealthAnalytics.analyze_population_metrics(detection_file)

    print("✓ Population analysis complete!")
    print(f"  Total detections: {metrics.get('total_detections', 0):,}")

    health = metrics.get('health_indicators', {})
    print(f"  Overall Health: {health.get('overall_status', 'Unknown')} "
          f"({health.get('overall_health_score', 0)}/100)")

    if args.report:
        report_file = PopulationHealthAnalytics.generate_public_report(
            metrics,
            location_name=args.location,
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
        logger.warning(f"Detections file not found: {detections_file}; generating one")
        detections_file = None

    if not detections_file:
        detections_file, _ = FishDetector.detect_fish(csv_file)

    metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)

    depth_file = Path(args.depth_heatmap) if getattr(args, 'depth_heatmap', None) else None
    if depth_file is None or not depth_file.exists():
        depth_file = HeatmapGenerator.create_depth_heatmap(csv_file, grid_size=args.grid_size)
        print(f"✓ Seabed bathymetry layer: {depth_file}")
    seabed_3d = WebVisualizer.create_seabed_3d_chart(
        depth_file,
        location_name=args.location,
    )
    print(f"✓ 3D seabed chart: {seabed_3d}")

    dashboard_file = WebVisualizer.create_dashboard(
        detections_file,
        metrics,
        location_name=args.location,
        depth_geojson_file=depth_file,
        seabed_3d_file=seabed_3d,
    )

    print("✓ Dashboard created!")
    print(f"  Open in browser: file://{dashboard_file.absolute()}")

    return 0


def cmd_map(args):
    """Create standalone seabed + fish survey map HTML."""
    csv_file = Path(args.csv_file)

    if not csv_file.exists():
        logger.error(f"File not found: {csv_file}")
        return 1

    detections_file = Path(args.detections) if args.detections else None
    depth_file = Path(args.depth_heatmap) if args.depth_heatmap else None

    if depth_file is None or not depth_file.exists():
        depth_file = HeatmapGenerator.create_depth_heatmap(csv_file, grid_size=args.grid_size)
        print(f"✓ Seabed bathymetry layer: {depth_file}")

    map_file = WebVisualizer.create_survey_map_html(
        csv_file,
        detections_file=detections_file,
        depth_geojson_file=depth_file,
        location_name=args.location,
    )

    print("✓ Survey map created!")
    print(f"  Open in browser: file://{map_file.absolute()}")
    return 0


def cmd_pipeline(args):
    """Execute full analysis pipeline (single or multiple RSD inputs)."""
    sources = args.input
    if len(sources) > 1 or Path(sources[0]).is_dir() or any('*' in s or '?' in s for s in sources):
        summary = batch_pipeline(
            sources,
            output_dir=getattr(args, 'output_dir', None),
            nchunk=_resolve_nchunk(args),
            location=args.location,
            recursive=not getattr(args, 'no_recursive', False),
        )
        print(format_batch_summary(summary))
        return 0 if summary.failed == 0 else 1

    input_file = Path(sources[0])

    if not input_file.exists():
        logger.error(f"File not found: {input_file}")
        return 1

    print("Starting full analysis pipeline...")

    csv_file, frame_count = convert_sonar_rsd_to_csv(input_file, nchunk=_resolve_nchunk(args))
    print(f"✓ CSV created: {csv_file}")
    print(f"✓ Frames extracted: {frame_count:,}")

    ply_file = MapGenerator.create_ply(csv_file)
    geojson_file = MapGenerator.create_geojson(csv_file)
    kml_file = MapGenerator.create_kml(csv_file)
    gpx_file = MapGenerator.create_gpx(csv_file)
    print(f"✓ Map exports: {ply_file}, {geojson_file}, {kml_file}, {gpx_file}")

    intensity_hm = HeatmapGenerator.create_intensity_heatmap(csv_file)
    depth_hm = HeatmapGenerator.create_depth_heatmap(csv_file, grid_size=0.01)
    temperature_hm = HeatmapGenerator.create_temperature_heatmap(csv_file, grid_size=0.01)
    print(f"✓ Heatmaps: {intensity_hm}, {depth_hm}, {temperature_hm}")
    location_name = args.location or 'Survey Area'
    seabed_3d = WebVisualizer.create_seabed_3d_chart(
        depth_hm,
        location_name=location_name,
    )
    print(f"✓ 3D seabed chart: {seabed_3d}")

    detections_file, detections = FishDetector.detect_fish(csv_file)
    print(f"✓ Fish detections: {len(detections):,} ({detections_file})")

    metrics = PopulationHealthAnalytics.analyze_population_metrics(detections_file)
    report_file = PopulationHealthAnalytics.generate_public_report(
        metrics,
        location_name=location_name,
    )
    dashboard_file = WebVisualizer.create_dashboard(
        detections_file,
        metrics,
        location_name=location_name,
        depth_geojson_file=depth_hm,
        seabed_3d_file=seabed_3d,
    )

    print("Pipeline complete.")
    print(f"  Health report: {report_file}")
    print(f"  Dashboard: {dashboard_file}")

    return 0


def cmd_batch(args):
    """Execute batch subcommands."""
    if not args.batch_command:
        print("Batch command requires a subcommand: convert, pipeline, or list")
        return 1

    recursive = not args.no_recursive

    if args.batch_command == 'list':
        files = discover_rsd_files(args.sources, recursive=recursive)
        if not files:
            print("No RSD files found.")
            return 1
        print(f"Found {len(files)} RSD file(s):")
        for path in files:
            size_mb = path.stat().st_size / 1024 / 1024
            print(f"  {path} ({size_mb:.1f} MB)")
        return 0

    continue_on_error = not getattr(args, 'fail_fast', False)

    if args.batch_command == 'convert':
        summary = batch_convert(
            args.sources,
            output_dir=args.output_dir,
            nchunk=_resolve_nchunk(args),
            map_formats=args.maps,
            recursive=recursive,
            continue_on_error=continue_on_error,
        )
    elif args.batch_command == 'pipeline':
        summary = batch_pipeline(
            args.sources,
            output_dir=args.output_dir,
            nchunk=_resolve_nchunk(args),
            location=args.location,
            recursive=recursive,
            continue_on_error=continue_on_error,
        )
    else:
        return 1

    print(format_batch_summary(summary))
    return 0 if summary.failed == 0 else 1


def cmd_playback(args):
    """Render live-style scrolling sonar playback from an RSD file."""
    input_file = Path(args.input)
    if not input_file.exists():
        logger.error(f'File not found: {input_file}')
        return 1

    output_file = Path(args.output) if args.output else None
    logger.info(f'Rendering playback for {input_file}...')

    out_path = generate_playback(
        input_file,
        output_file=output_file,
        fmt=args.format,
        channel_id=args.channel,
        nchunk=args.nchunk,
        fps=args.fps,
        width=args.width,
        height=args.height,
        window_pings=args.window_pings,
        frame_step=args.frame_step,
        max_pings=args.max_pings,
        hud=not args.no_hud,
        bottom_line=not args.no_bottom_line,
    )

    print('✓ Sonar playback complete!')
    print(f'  Output: {out_path}')
    if out_path.suffix.lower() == '.html':
        print('  Open the HTML file in a browser for interactive play/pause and scrubbing.')
    elif out_path.suffix.lower() == '.mp4':
        print('  MP4 uses Garmin-style palette with scrolling time axis like live sonar.')
    return 0


def cmd_upload(args):
    """Start the local RSD upload web server."""
    from sonar_upload_server import run_server

    run_server(
        host=args.host,
        port=args.port,
        uploads_dir=args.uploads_dir,
        output_dir=args.output_dir,
    )
    return 0


def cmd_merge(args):
    """Merge multiple sonar CSV files."""
    csv_files = [Path(p) for p in args.inputs]
    for path in csv_files:
        if not path.exists():
            logger.error(f"File not found: {path}")
            return 1

    output = Path(args.output) if args.output else None
    merged = merge_csv_files(csv_files, output)
    print("✓ CSV merge complete!")
    print(f"  Input files: {len(csv_files)}")
    print(f"  Output: {merged}")
    return 0


def cmd_compare(args):
    """Compare bathymetry between two surveys."""
    survey_a = Path(args.survey_a)
    survey_b = Path(args.survey_b)
    for path in (survey_a, survey_b):
        if not path.exists():
            logger.error(f"File not found: {path}")
            return 1

    output = Path(args.output) if args.output else None
    diff_file = compare_surveys(survey_a, survey_b, args.grid_size, output)
    data = __import__('json').loads(diff_file.read_text(encoding='utf-8'))
    cells = data.get('properties', {}).get('cells_compared', len(data.get('features', [])))
    print("✓ Survey comparison complete!")
    print(f"  Baseline: {survey_a}")
    print(f"  Compare:  {survey_b}")
    print(f"  Cells compared: {cells}")
    print(f"  Output: {diff_file}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
