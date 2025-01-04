#!/usr/bin/env python3
"""
Multi-city runner for GSV Metadata Tracker.

This script provides a wrapper around the GSV Metadata Tracker to process multiple cities.
Each line in the input file represents a complete command line style configuration for a city.

Example cities.txt format:
    Seattle, WA --width 2000 --height 2000 --step 25 --force-size
    Portland, OR --width 1500 --height 1500
    Vancouver, BC
"""

import subprocess
import sys
import shlex
from typing import List, Optional, Dict
from pathlib import Path
import argparse
import logging
from datetime import datetime
from gsv_metadata_tracker.fileutils import get_default_data_dir

def parse_city_line(line: str) -> Optional[List[str]]:
    """
    Parse a line from the cities file into command line arguments.
    
    Each line should be formatted exactly as you would type it on the command line.
    The city name comes first, followed by any optional parameters.
    
    Args:
        line: A line from the cities file
        
    Returns:
        List[str] if valid line, None if comment or empty
        
    Examples:
        >>> parse_city_line("Seattle, WA --width 2000 --height 2000 --step 25 --force-size")
        ["Seattle, WA", "--width", "2000", "--height", "2000", "--step", "25", "--force-size"]
        >>> parse_city_line("Grand Marais, MN")
        ["Grand Marais, MN"]
        >>> parse_city_line("# This is a comment")
        None
    """
    # Skip comments and empty lines
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    
    # Use shlex to properly handle quoted strings and spaces
    return shlex.split(line)

def load_cities(file_path: str) -> List[List[str]]:
    """
    Load city configurations from file.
    
    Args:
        file_path: Path to file containing city configurations
        
    Returns:
        List[List[str]]: List of command line argument lists for each city
        
    Raises:
        FileNotFoundError: If cities file doesn't exist
    """
    cities = []
    
    with open(file_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                args = parse_city_line(line)
                if args:
                    cities.append(args)
            except ValueError as e:
                logging.warning(f"Invalid configuration at line {line_num}: {line.strip()}")
                logging.warning(f"Error: {str(e)}")
                continue
            
    return cities

def parse_args() -> argparse.Namespace:
    """
    Parse and validate command line arguments.
    
    Returns:
        argparse.Namespace: Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description='Run GSV Tracker for multiple cities',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples:
  python run_cities.py cities.txt
  python run_cities.py cities.txt --batch-size 200 --connection-limit 100
  python run_cities.py cities.txt --output-dir ./data --log-level DEBUG'''
    )
    
    parser.add_argument(
        'cities_file',
        type=str,
        help='Path to file containing city configurations (e.g., cities.txt)'
    )
    
    # Global execution parameters
    exec_group = parser.add_argument_group('Execution Parameters')
    exec_group.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of requests to prepare and queue at once'
    )
    exec_group.add_argument(
        '--connection-limit',
        type=int,
        default=50,
        help='Maximum number of concurrent connections'
    )
    exec_group.add_argument(
        '--no-visual',
        action='store_true',
        help='Skip generating visualizations'
    )
    exec_group.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Set logging level'
    )
    exec_group.add_argument(
        '--continue-on-error',
        action='store_true',
        help='Continue processing remaining cities if one fails'
    )
    exec_group.add_argument(
        '--download-dir',
        type=str,
        help='Dir to save downloaded data (defaults to ./data)',
        default=get_default_data_dir()
    )
    
    args = parser.parse_args()
    
    # Validate batch_size and connection_limit relationship
    if args.connection_limit > args.batch_size:
        parser.error("connection-limit cannot be larger than batch-size")
        
    return args

def setup_logging(args: argparse.Namespace) -> str:
    """
    Set up logging configuration.
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        str: Path to the log file
    """
    # Create output directory if specified
    if args.download_dir:
        Path(args.download_dir).mkdir(parents=True, exist_ok=True)
    
    # Create log filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = f'gsv_tracker_{timestamp}.log'
    if args.download_dir:
        log_path = Path(args.download_dir) / log_filename
    else:
        log_path = Path(log_filename)
        
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return str(log_path)

def run_gsv_tracker(city_args: List[str], global_args: argparse.Namespace) -> bool:
    """Run the GSV Metadata Tracker for a specific city."""
    # Base command with script name
    cmd = ["python", "gsv_tracker.py"]
    
    # Add city name - join all parts until we hit an argument starting with --
    city_name_parts = []
    other_args = []
    for arg in city_args:
        if arg.startswith('--'):
            other_args.extend([arg])
        else:
            if other_args:  # If we've already seen a --, this is a value for it
                other_args.extend([arg])
            else:  # Otherwise it's part of the city name
                city_name_parts.append(arg)
    
    # Add the city name as a single argument
    cmd.append(' '.join(city_name_parts))
    
    # Add any other city-specific args
    cmd.extend(other_args)
    
    # Add global execution args
    cmd.extend([
        '--batch-size', str(global_args.batch_size),
        '--connection-limit', str(global_args.connection_limit),
        '--log-level', global_args.log_level
    ])
    
    if global_args.no_visual:
        cmd.append('--no-visual')
    
    try:
        logging.info(f"Processing {cmd[2]}")
        logging.debug(f"Command: {' '.join(cmd)}")
        
        # Remove capture_output=True to allow output to pass through
        result = subprocess.run(
            cmd,
            check=True,
            text=True
        )
            
        return True
        
    except subprocess.CalledProcessError as e:
        logging.error(f"Error processing {cmd[2]}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error processing {cmd[2]}: {e}")
        return False

def main() -> int:
    """
    Main entry point for the multi-city GSV Metadata Tracker.
    
    Returns:
        int: Exit code (0 for success, 1 for errors)
    """
    args = parse_args()
    
    # Setup logging
    log_path = setup_logging(args)
    logging.info(f"Log file: {log_path}")
    
    try:
        cities = load_cities(args.cities_file)
    except FileNotFoundError:
        logging.error(f"Cities file '{args.cities_file}' not found")
        return 1
    except Exception as e:
        logging.error(f"Error reading cities file: {e}")
        return 1
    
    if not cities:
        logging.error("No valid cities found in input file")
        return 1
        
    logging.info(f"Found {len(cities)} cities to process")
    
    successful = []
    failed = []
    
    for i, city_args in enumerate(cities, 1):
        logging.info(f"\nProcessing city {i}/{len(cities)}")
        
        if run_gsv_tracker(city_args, args):
            successful.append(city_args[0])  # city name is first argument
        else:
            failed.append(city_args[0])
            if not args.continue_on_error:
                logging.error("\nStopping due to error. Use --continue-on-error to process remaining cities.")
                break
    
    # Print summary
    logging.info("\nProcessing complete!")
    logging.info(f"Successful: {len(successful)}/{len(cities)} cities")
    
    if failed:
        logging.error("\nFailed cities:")
        for city in failed:
            logging.error(f"- {city}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())