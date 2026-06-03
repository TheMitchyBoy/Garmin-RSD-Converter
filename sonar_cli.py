#!/usr/bin/env python3
"""
CLI tool for Garmin Sonar RSD conversion and analysis
"""

import argparse
import sys
import logging
import csv
from pathlib import Path

from sonar_converter_streaming import convert_sonar_rsd_to_csv
from analysis_tools import MapGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Convert Garmin Sonar RSD files to CSV and maps',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Convert sonar file to CSV
  python sonar_cli.py convert Sonar000.RSD
  
  # Convert with custom output
  python sonar_cli.py convert Sonar000.RSD -o sonar_data.csv
  
  # Convert and generate a 3D PLY point cloud
  python sonar_cli.py convert Sonar000.RSD --maps ply

  # Analyze existing CSV
  python sonar_cli.py analyze sonar_data.csv
        '''
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Convert command
    convert_cmd = subparsers.add_parser('convert', help='Convert Sonar RSD to CSV')
    convert_cmd.add_argument('input', help='Input Sonar RSD file')
    convert_cmd.add_argument('-o', '--output', help='Output CSV file')
    convert_cmd.add_argument('--stride', type=int, default=256,
                           help='Sample every N bytes (default: 256)')
    convert_cmd.add_argument('--maps', nargs='+', choices=['ply', 'all'],
                           help='Generate 3D export formats')
    
    # Analyze command
    analyze_cmd = subparsers.add_parser('analyze', help='Analyze CSV file')
    analyze_cmd.add_argument('input', help='Input CSV file')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    try:
        if args.command == 'convert':
            return cmd_convert(args)
        elif args.command == 'analyze':
            return cmd_analyze(args)
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
        formats = ['ply'] if 'all' in args.maps else args.maps
        logger.info(f"Generating 3D exports: {formats}")
        for fmt in formats:
            if fmt == 'ply':
                MapGenerator.create_ply(csv_file)
                print(f"✓ PLY 3D point cloud generated")

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


if __name__ == '__main__':
    sys.exit(main())
