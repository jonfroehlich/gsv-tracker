from datetime import datetime
import json, gzip, glob, os
from pathlib import Path
from collections import Counter
import numpy as np
from tqdm import tqdm
from typing import Tuple, Dict, Union, Optional, List  # Added List import
import logging
import pandas as pd

from gsv_metadata_tracker import parse_filename, get_city_location_data
from gsv_metadata_tracker import get_default_data_dir
from gsv_metadata_tracker import save_metadata_summary_as_json
from gsv_metadata_tracker.fileutils import load_city_csv_file, get_list_of_city_csv_files

logger = logging.getLogger(__name__)

def find_missing_json_files(data_dir: str) -> List[str]:
    """
    Find all csv.gz files that don't have corresponding JSON files.
    
    Args:
        data_dir: Directory to search for files
        
    Returns:
        List of paths to csv.gz files needing JSON metadata
    """
    csv_files = get_list_of_city_csv_files()
    
    missing_json = []
    for csv_file in csv_files:
        json_file = csv_file.rsplit('.csv.gz', 1)[0] + '.json'
        if not os.path.exists(json_file):
            missing_json.append(csv_file)
    
    return missing_json

def generate_missing_json_files(data_dir: str) -> None:
    """Generate missing JSON metadata files for all csv.gz files in directory."""
    logger.info(f"Scanning {data_dir} for csv.gz files missing JSON metadata...")
    
    all_csv_files = get_list_of_city_csv_files(data_dir)
    missing_files = find_missing_json_files(data_dir)
    
    if not missing_files:
        file_text = "file" if len(all_csv_files) == 1 else "files"
        logger.info(f"Found {len(all_csv_files)} csv.gz {file_text}. All csv.gz files already have a corresponding .json metadata file.")
        return
    
    file_text = "file" if len(missing_files) == 1 else "files"
    logger.info(f"Found {len(missing_files)} of {len(all_csv_files)} {file_text} needing a .json metadata file.")
    
    cnt_generated_json_files = 0
    for csv_path in tqdm(missing_files, desc="Generating metadata .json files"):
        try:
            params = parse_filename(csv_path)
            city_name = params['city_name']
            search_width = params['width_meters']
            search_height = params['height_meters']
            step = params['step_meters']
            
            df = load_city_csv_file(csv_path)

            center_lat = float(df['query_lat'].mean())
            center_lon = float(df['query_lon'].mean())
            
            # country_name = infer_country(city_name, center_lat, center_lon)
            location = get_city_location_data(city_name)
            country_name = location.raw['address']['country']

            save_metadata_summary_as_json(
                csv_gz_path=csv_path,
                df=df,
                city_name=city_name,
                country_name=country_name,
                grid_width=search_width,
                grid_height=search_height,
                step_length=step
            )
            
            logger.debug(f"Generated metadata for {csv_path} (Country: {country_name})")
            cnt_generated_json_files += 1
        except Exception as e:
            logger.error(f"Error processing {csv_path}: {str(e)}")
            continue
    
    logger.info(f"Metadata generation completed for {cnt_generated_json_files} file(s).")

def main():
    """Command-line entry point for metadata generation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate missing JSON metadata files for GSV data'
    )
    
    parser.add_argument(
        '--data-dir',
        type=str,
        default=get_default_data_dir(),
        help='Directory containing GSV metadata files (default: project data directory)'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Set the logging level (default: INFO)'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    if not os.path.exists(args.data_dir):
        print(f"Error: Directory {args.data_dir} does not exist")
        return 1
        
    generate_missing_json_files(args.data_dir)
    return 0

if __name__ == '__main__':
    main()