import json
import gzip
import os
from tqdm import tqdm
import logging
from typing import Dict, Any
import pandas as pd
from pathlib import Path
import shutil

from gsv_metadata_tracker.fileutils import load_city_csv_file
from gsv_metadata_tracker.analysis import calculate_pano_stats

logger = logging.getLogger(__name__)

def update_city_json_with_daily_histograms(data_dir: str, dry_run: bool = True) -> None:
    """
    Update existing city JSON.gz files to add daily histogram statistics.
    
    Args:
        data_dir: Directory containing the JSON.gz and CSV.gz files
        dry_run: If True, only print what would be done without making changes
    """
    logger.info(f"Scanning {data_dir} for JSON.gz files to update...")
    
    # Find all JSON files except cities.json.gz
    json_files = [f for f in os.listdir(data_dir) 
                 if f.endswith('.json.gz') and f != 'cities.json.gz']
    
    logger.info(f"Found {len(json_files)} JSON.gz files to process")
    skipped_count = 0
    updated_count = 0
    
    for json_file in tqdm(json_files, desc="Processing city files"):
        json_path = os.path.join(data_dir, json_file)
        
        tqdm.write(f"Processing: {json_file}")  # This writes below the progress bar

        try:
            # Read existing JSON data
            with gzip.open(json_path, 'rt', encoding='utf-8') as f:
                city_data = json.load(f)

            # Check if histograms already exist
            if ('histogram_of_capture_dates' in city_data['all_panos'] and 
                'histogram_of_capture_dates' in city_data['google_panos']):
                logger.debug(f"Skipping {json_file} - histogram fields already exist")
                skipped_count += 1
                continue

            # Get the original creation timestamp
            original_timestamp = pd.to_datetime(city_data['timestamps']['json_file_created'])
            
            # Get corresponding CSV file path
            csv_filename = city_data['data_file']['filename']
            if not csv_filename.endswith('.csv.gz'):
                csv_filename += '.csv.gz'
            csv_path = os.path.join(data_dir, csv_filename)
            
            if not os.path.exists(csv_path):
                logger.warning(f"CSV file not found: {csv_path}")
                continue
                
            # Load CSV data and calculate new statistics
            df = load_city_csv_file(csv_path)
         
            
            # Calculate statistics for all panos and Google panos
            all_pano_stats = calculate_pano_stats(df, original_timestamp)
            google_pano_stats = calculate_pano_stats(df, original_timestamp, copyright_filter='Google')
            
            # Create backup filename
            backup_path = json_path + '.backup'
            
            if not dry_run:
                # Backup existing JSON file if backup doesn't exist
                if not os.path.exists(backup_path):
                    shutil.copy2(json_path, backup_path)
                    logger.debug(f"Created backup: {backup_path}")
                
                # Update the histograms in the city data
                city_data['all_panos'].update({
                    'histogram_of_capture_dates': all_pano_stats['daily_distribution']
                })
                city_data['google_panos'].update({
                    'histogram_of_capture_dates': google_pano_stats['daily_distribution']
                })
                
                # Save updated JSON
                with gzip.open(json_path, 'wt', encoding='utf-8') as f:
                    json.dump(city_data, f, indent=2)
                
                logger.debug(f"Updated {json_file} with new histogram data")
                updated_count += 1
            else:
                logger.info(f"Would update {json_file} (dry run)")
                updated_count += 1
                
        except Exception as e:
            logger.error(f"Error processing {json_file}: {str(e)}")
            continue
    
    logger.info(f"Processing complete:")
    logger.info(f"  Files skipped (already had histograms): {skipped_count}")
    logger.info(f"  Files {'would be' if dry_run else ''} updated: {updated_count}")

def main():
    """Command-line entry point for updating JSON files."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Update existing JSON metadata files with daily histogram data'
    )
    
    parser.add_argument(
        '--data-dir',
        type=str,
        default='./data',
        help='Directory containing GSV metadata files'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print what would be done without making changes'
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
    
    logger.info(f"Starting update with parameters: {args}")
    
    update_city_json_with_daily_histograms(args.data_dir, args.dry_run)

if __name__ == '__main__':
    main()