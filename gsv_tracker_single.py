#!/usr/bin/env python3
"""
Google Street View Metadata Tracker (Single-threaded Version)

This script downloads and processes Google Street View metadata for a specified city 
using a single-threaded approach. It creates a grid of sampling points around the 
city center and queries the GSV API for each point, saving the results and 
optionally generating a visualization.

Key features:
- Grid-based sampling with configurable dimensions and resolution
- Automatic city coordinate lookup
- Progress tracking with detailed logging
- Resumable downloads
- Optional interactive map visualization
- Compressed data storage (.gz format)

Usage:
    python gsv_tracker_single.py "City, State" [options]

Arguments:
    city              Name of the city to analyze (e.g., "Seattle, WA")
    --width METERS    Width of search grid in meters (default: 1000)
    --height METERS   Height of search grid in meters (default: 1000)
    --step METERS     Distance between sample points (default: 20)
    --no-visual      Skip generating visualization map
    --log-level      Set logging verbosity (default: WARNING)

Example:
    python gsv_tracker_single.py "Portland, OR" --width 2000 --height 2000 --step 30 --log-level INFO

Notes:
    This single-threaded version is ideal for:
    - Testing and debugging
    - Small geographic areas
    - Systems with limited resources
    - Baseline comparison with async version

Output:
    - Compressed CSV file with GSV metadata
    - Interactive HTML map (unless --no-visual is specified)
    - Progress information and logs
"""

import argparse
import sys
import logging
import os
from typing import Optional
from . import (
    load_config,
    get_city_coordinates,
    get_search_dimensions,
    create_visualization_map,
    download_gsv_metadata  # single-threaded version
)
from .fileutils import generate_base_filename

def parse_args():
    """
    Parse and validate command line arguments for the simple single-threaded version.
    
    This function sets up the following arguments:
    - city: Required positional argument for the city name
    - width: Optional grid width in meters (default: 1000)
    - height: Optional grid height in meters (default: 1000)
    - step: Optional step size between points in meters (default: 20)
    - no-visual: Optional flag to skip visualization
    - log-level: Optional logging level selection
    
    Returns:
        argparse.Namespace: Parsed command line arguments object containing:
            - city (str): Name of the city to analyze
            - width (float): Grid width in meters
            - height (float): Grid height in meters
            - step (float): Distance between sample points
            - no_visual (bool): Whether to skip visualization
            - log_level (str): Logging level to use
    """
    parser = argparse.ArgumentParser(
        description='GSV Metadata Tracker (Single-threaded version)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Required positional argument for city name
    parser.add_argument(
        'city', 
        help='City name to analyze (e.g., "Seattle, WA")'
    )
    
    # Optional grid dimension arguments
    parser.add_argument(
        '--width', 
        type=float, 
        default=1000,
        help='Search grid width in meters. Larger values cover more area but take longer.'
    )
    
    parser.add_argument(
        '--height', 
        type=float, 
        default=1000,
        help='Search grid height in meters. Larger values cover more area but take longer.'
    )
    
    parser.add_argument(
        '--step', 
        type=float, 
        default=20,
        help='Step size in meters between sample points in the grid. Smaller values provide higher resolution but take longer.'
    )
    
    # Visualization control
    parser.add_argument(
        '--no-visual',
        action='store_true',
        help='Skip generating visualizations of the results. Useful for batch processing.'
    )

    # Add new boundary check argument
    parser.add_argument(
        '--check-boundary',
        action='store_true',
        help='Generate visualization of search area without downloading data. '
             'Useful for verifying the area before starting a download.'
    )
    
    # Logging configuration
    parser.add_argument(
        '--log-level',
        type=str,
        default='WARNING',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set the logging level for output messages'
    )
    
    return parser.parse_args()

def main():
    """
    Entry point for the simple single-threaded version of GSV Metadata Tracker.
    
    This function:
    1. Parses command line arguments
    2. Sets up logging based on specified level
    3. Loads configuration (API key, paths)
    4. Gets city coordinates from name
    5. Downloads GSV metadata using single-threaded approach
    6. Optionally generates visualization
    
    The single-threaded version is simpler but slower than the async version.
    It's useful for:
    - Testing and debugging
    - Small areas where async overhead isn't worth it
    - Systems with limited resources
    - Comparing results with the async version
    
    Returns:
        int: Exit code (0 for success, 1 for handled errors, 2 for unhandled errors)
    """
    # Parse command line arguments
    args = parse_args()
    
    # Configure logging system
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    try:
        # Load configuration (API key, paths, etc.)
        config = load_config()
        
        # Get coordinates for the specified city
        location = get_city_coordinates(args.city)
        if not location:
            logging.error(f"Could not find coordinates for {args.city}")
            return 1
        
        # If checking boundaries, create and save visualization then exit
        if args.check_boundary:
            base_name = generate_base_filename(args.city, args.width, args.height, args.step)
            preview_path = os.path.join(config['download_path'], f"{base_name}_preview.html")
            
            # Create preview map using your display_search_area function
            preview_map = display_search_area(
                args.city,
                location.latitude,
                location.longitude,
                args.width,
                args.height,
                args.step
            )
            preview_map.save(preview_path)
            
            print(f"\nSearch area preview saved to: {preview_path}")
            print("Review the visualization and adjust parameters if needed.")
            print("\nTo download data with these parameters, run the same command without --check-boundary")
            return 0
            
        # Download GSV metadata using single-threaded approach
        df = download_gsv_metadata(
            city_name=args.city,
            center_lat=location.latitude,
            center_lon=location.longitude,
            grid_width=args.width,
            grid_height=args.height,
            step_length=args.step,
            api_key=config['api_key'],
            download_path=config['download_path']
        )
        
        # Generate visualization if not disabled
        if not args.no_visual:
            base_name = generate_base_filename(args.city, args.width, args.height, args.step)
            map_path = os.path.join(config['download_path'], f"{base_name}.html")
            
            map_obj = create_visualization_map(df, args.city)
            map_obj.save(map_path)
            logging.info(f"Map visualization saved to {map_path}")
            
        return 0
            
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(main())