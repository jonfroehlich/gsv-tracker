import json
import gzip
from datetime import datetime
import pandas as pd
import numpy as np
import os
from tqdm import tqdm
from typing import Optional, Dict, Any, List, Union
import logging
from dataclasses import asdict
from .fileutils import load_city_csv_file, get_list_of_city_csv_files, parse_filename
from .geoutils import get_city_location_data, get_state_abbreviation, get_country_code
from .analysis import (
    calculate_pano_stats,
    calculate_age_stats,
    calculate_coverage_stats,
)

logger = logging.getLogger(__name__)

# Define constants for age statistics structure
EMPTY_AGE_STATS = {
    "count": 0,
    "oldest_pano_date": None,
    "newest_pano_date": None,
    "avg_pano_age_years": None,
    "median_pano_age_years": None,
    "stdev_pano_age_years": None,
    "age_percentiles_years": None,
    "valid_dates_count": 0,
    "invalid_dates_count": 0
}

EMPTY_PERCENTILES = {
    "p10": None,
    "p25": None,
    "p75": None,
    "p90": None
}
    
def find_missing_json_files(data_dir: str) -> List[str]:
    """
    Find all csv.gz files that don't have corresponding JSON.gz files.
    
    Args:
        data_dir: Directory to search for files
        
    Returns:
        List of paths to csv.gz files needing JSON metadata
    """
    csv_files = get_list_of_city_csv_files()
    
    missing_json = []
    for csv_file in csv_files:
        json_file = csv_file.rsplit('.csv.gz', 1)[0] + '.json.gz'
        if not os.path.exists(json_file):
            missing_json.append(csv_file)
    
    return missing_json

def generate_missing_city_json_files(data_dir: str) -> None:
    """
    Generate missing JSON metadata files for all csv.gz files in directory.
    
    This is useful if a .json file was never created for a given city or if
    the .json file needs to be recreated due to changes in analysis code.
    """
    logger.info(f"Scanning {data_dir} for csv.gz files missing JSON metadata...")
    
    all_csv_files = get_list_of_city_csv_files(data_dir)
    missing_json_files = find_missing_json_files(data_dir)
    
    if not missing_json_files:
        file_text = "file" if len(all_csv_files) == 1 else "files"
        logger.info(f"Found {len(all_csv_files)} csv.gz {file_text}. All csv.gz files already have a corresponding .json metadata file.")
        return
    
    file_text = "file" if len(missing_json_files) == 1 else "files"
    logger.info(f"Found {len(missing_json_files)} of {len(all_csv_files)} {file_text} needing a .json metadata file.")
    
    cnt_generated_json_files = 0
    for csv_path in tqdm(missing_json_files, desc="Generating metadata .json files"):
        try:
            params = parse_filename(csv_path)
            city_query_str = params['city_query_str']
            search_width = params['width_meters']
            search_height = params['height_meters']
            step = params['step_meters']

            logger.debug(f"Parsed filename into city: {city_query_str}, width: {search_width}, height: {search_height}, step: {step}")
            
            df = load_city_csv_file(csv_path)

            center_lat = float(df['query_lat'].mean())
            center_lon = float(df['query_lon'].mean())
            
            # Reverse geocode city name with lat,lng as hints
            city_loc_data = get_city_location_data(city_query_str, center_lat, center_lon)

            logger.debug(f"Generating .json metadata for {csv_path} at {city_loc_data.city}, {city_loc_data.state}, {city_loc_data.country}")

            generate_city_metadata_summary_as_json(
                csv_gz_path=csv_path,
                df=df,
                city_name=city_loc_data.city,
                state_name=city_loc_data.state,
                country_name=city_loc_data.country,
                grid_width=search_width,
                grid_height=search_height,
                step_length=step
            )
            
            logger.debug(f"Generated .json metadata for {csv_path} at {city_loc_data.city}, {city_loc_data.state}, {city_loc_data.country}")
            cnt_generated_json_files += 1
        except Exception as e:
            logger.error(f"Error processing {csv_path}: {str(e)}")
            continue
    
    logger.info(f"Metadata generation completed for {cnt_generated_json_files} file(s).")

def merge_capture_date_histograms(cities_data: List[Dict]) -> Dict[str, Dict[Union[int, str], int]]:
    """
    Merge yearly and daily histograms from multiple cities.
    
    Args:
        cities_data: List of city data dictionaries
        
    Returns:
        Dictionary containing merged histograms for all panos and google panos.
        Yearly histograms use integer years as keys, daily histograms use ISO date strings.
    """
    logger.debug(f"Merging capture date histograms for {len(cities_data)} cities")

    all_panos_yearly = {}
    google_panos_yearly = {}
    all_panos_daily = {}
    google_panos_daily = {}
    
    for city_data in cities_data:
        logger.debug(f"Merging histograms for {city_data['city']['name']}, {city_data['city']['state']['name']}, {city_data['city']['country']['name']}")
        
        # Handle all panos yearly data
        yearly_data = city_data["all_panos"]["histogram_of_capture_dates_by_year"]
        if isinstance(yearly_data, dict) and "counts" in yearly_data:
            for year, count in yearly_data["counts"].items():
                try:
                    year_int = int(year) if isinstance(year, str) else year
                    all_panos_yearly[year_int] = all_panos_yearly.get(year_int, 0) + count
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error converting year '{year}' to integer: {str(e)}")
        else:
            for year, count in yearly_data.items():
                try:
                    year_int = int(year) if isinstance(year, str) else year
                    all_panos_yearly[year_int] = all_panos_yearly.get(year_int, 0) + count
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error converting year '{year}' to integer: {str(e)}")
            
        # Handle google panos yearly data
        yearly_data = city_data["google_panos"]["histogram_of_capture_dates_by_year"]
        if isinstance(yearly_data, dict) and "counts" in yearly_data:
            for year, count in yearly_data["counts"].items():
                try:
                    year_int = int(year) if isinstance(year, str) else year
                    google_panos_yearly[year_int] = google_panos_yearly.get(year_int, 0) + count
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error converting year '{year}' to integer: {str(e)}")
        else:
            for year, count in yearly_data.items():
                try:
                    year_int = int(year) if isinstance(year, str) else year
                    google_panos_yearly[year_int] = google_panos_yearly.get(year_int, 0) + count
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error converting year '{year}' to integer: {str(e)}")
            
        # Handle all panos daily data
        daily_data = city_data["all_panos"]["histogram_of_capture_dates"]
        if isinstance(daily_data, dict) and "counts" in daily_data:
            for date, count in daily_data["counts"].items():
                all_panos_daily[date] = all_panos_daily.get(date, 0) + count
        else:
            for date, count in daily_data.items():
                all_panos_daily[date] = all_panos_daily.get(date, 0) + count
            
        # Handle google panos daily data
        daily_data = city_data["google_panos"]["histogram_of_capture_dates"]
        if isinstance(daily_data, dict) and "counts" in daily_data:
            for date, count in daily_data["counts"].items():
                google_panos_daily[date] = google_panos_daily.get(date, 0) + count
        else:
            for date, count in daily_data.items():
                google_panos_daily[date] = google_panos_daily.get(date, 0) + count
    
    # Sort all histograms
    return {
        "all_panos_yearly": dict(sorted(all_panos_yearly.items())),
        "google_panos_yearly": dict(sorted(google_panos_yearly.items())),
        "all_panos_daily": dict(sorted(all_panos_daily.items())),
        "google_panos_daily": dict(sorted(google_panos_daily.items()))
    }

def generate_city_metadata_summary_as_json(
    csv_gz_path: str,
    df: pd.DataFrame,
    city_name: str,
    state_name: str,
    country_name: str,
    grid_width: float,
    grid_height: float,
    step_length: float,
    force_recreate_file: bool = False
) -> str:
    """
    Generate and save download statistics for an individual city to a JSON file (compressed).

    Returns the .json.gz filename with path
    
    Args:
        csv_gz_path: Full path to the compressed CSV file (including filename)
        df: DataFrame containing the GSV data
        city_name: Name of the city
        state_name: Name of the state (if one exists)
        country_name: Name of the country
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Distance between sample points in meters
        force_recreate_file: forces the recreation of the .json file (defaults False)
    """
    logger.debug(f"Generating metadata summary for {city_name}, {state_name}, {country_name} from {csv_gz_path}")

    # Generate JSON.gz path by replacing .csv.gz extension with .json.gz
    json_filename_with_path = csv_gz_path.rsplit('.csv.gz', 1)[0] + '.json.gz'

    if os.path.exists(json_filename_with_path) and not force_recreate_file:
        logger.info(f"JSON.gz file already exists: {json_filename_with_path}; returning...")
        return json_filename_with_path
    
    # Calculate center coordinates from query points
    center_lat = float(df['query_lat'].mean())
    center_lon = float(df['query_lon'].mean())

    # Calculate ranges to verify grid dimensions
    diagonal_meters = np.sqrt(grid_width**2 + grid_height**2)
    
    # Calculate extents
    query_bounds = {
        "min_lat": float(df['query_lat'].min()),
        "max_lat": float(df['query_lat'].max()),
        "min_lon": float(df['query_lon'].min()),
        "max_lon": float(df['query_lon'].max())
    }

    # Get start and end times from query_timestamp
    df['query_timestamp_converted'] = pd.to_datetime(df['query_timestamp'], errors='coerce')
    problematic_timestamps = df[df['query_timestamp_converted'].isna()]

    if len(problematic_timestamps) > 0:
        logger.warning(f"\nFound {len(problematic_timestamps)} problematic timestamps:")
        logger.warning("\nOriginal problematic values:")
        for idx, row in problematic_timestamps.iterrows():
            logger.warning(f"Row {idx}: {row['query_timestamp']}")
    else:
        logger.debug(f"All timestamps converted successfully in {csv_gz_path}!")

    start_time = df['query_timestamp_converted'].min()
    end_time = df['query_timestamp_converted'].max()

    try:
        duration = end_time - start_time
        duration_seconds = duration.total_seconds()
        logger.debug(f"Duration: {duration_seconds:.2f} seconds")
    except Exception as e:
        logger.error(f"Error calculating duration: {str(e)}")
        duration_seconds = None

    # Use the analysis module for statistics calculations
    now = pd.Timestamp.now()
    
    # Calculate all pano statistics
    all_pano_stats = calculate_pano_stats(df, now)
    google_pano_stats = calculate_pano_stats(df, now, copyright_filter='Google')
    
    # Calculate coverage statistics
    coverage_stats = calculate_coverage_stats(df)

    top_10_photographers = dict(sorted(
        all_pano_stats.photographer_stats.photographer_counts.items(), 
        key=lambda x: x[1], reverse=True)[:10])

    metadata = {
        "data_file": {
            "filename": os.path.basename(csv_gz_path),
            "format": "csv.gz",
            "rows": len(df),
            "size_bytes": os.path.getsize(csv_gz_path)
        },
        "city": {
            "name": city_name,
            "state": {
                "name": state_name,
                "code": get_state_abbreviation(state_name)
            },
            "country": {
                "name": country_name,
                "code": get_country_code(country_name)
            },
            "center": {
                "latitude": center_lat,
                "longitude": center_lon
            },
            "bounds": query_bounds
        },
        "search_grid": {
            "width_meters": grid_width,
            "height_meters": grid_height,
            "step_length_meters": step_length,
            "diagonal_meters": diagonal_meters,
            "total_search_points": len(df),
            "area_km2": (grid_width * grid_height) / 1_000_000
        },
        "download": {
            "start_time": start_time.isoformat() if start_time is not None else None,
            "end_time": end_time.isoformat() if end_time is not None else None,
            "duration_seconds": duration_seconds,
        },
        "coverage": asdict(coverage_stats),
        "all_panos": {
            "duplicate_stats": asdict(all_pano_stats.duplicate_stats),
            "age_stats": asdict(all_pano_stats.age_stats),
            "histogram_of_capture_dates_by_year": asdict(all_pano_stats.yearly_distribution),
            "histogram_of_capture_dates": asdict(all_pano_stats.daily_distribution),
            "top_10_photographers": top_10_photographers,
        },
        "google_panos": {
            "duplicate_stats": asdict(google_pano_stats.duplicate_stats),
            "age_stats": asdict(google_pano_stats.age_stats),
            "histogram_of_capture_dates_by_year": asdict(google_pano_stats.yearly_distribution),
            "histogram_of_capture_dates": asdict(google_pano_stats.daily_distribution)
        },
    }
    
    # Save compressed JSON
    with gzip.open(json_filename_with_path, 'wt', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Saved compressed JSON to: {json_filename_with_path}")
    return json_filename_with_path

def generate_aggregate_summary_as_json(json_dir: str) -> Dict[str, Any]:
    """
    Generate and save a summary of all city JSON files in the specified directory.
    
    Args:
        json_path: Path to directory containing city JSON files
        
    Returns:
        Dictionary containing aggregated city summaries
    """
    logger.debug(f"Generating aggregate summary cities.json file for all city JSON files in {json_dir}")

    cities_data = []
    raw_city_data = []  # Store complete city data for histogram merging
    
    # Find all JSON files in directory except the cities.json file
    json_files = [f for f in os.listdir(json_dir) 
                 if f.endswith('.json.gz') and f != 'cities.json.gz']
    logger.info(f"Found {len(json_files)} JSON.gz files in {json_dir}")

    for json_file in tqdm(json_files, desc="Processing city files", unit="file"):
        file_path = os.path.join(json_dir, json_file)
        
        try:
            logger.debug(f"Opening {file_path}...")
            with gzip.open(file_path, 'rt', encoding='utf-8') as f:
                city_data = json.load(f)
            
            raw_city_data.append(city_data)  # Store complete data for histogram merging

            # Extract relevant information
            city_summary = {
                # Basic information
                "city": city_data["city"]["name"],
                "state": {
                    "name": city_data["city"]["state"]["name"],
                    "code": city_data["city"]["state"]["code"]
                },
                "country": {
                    "name": city_data["city"]["country"]["name"],
                    "code": city_data["city"]["country"]["code"]
                },
                
                # Location information
                "center": {
                    "latitude": city_data["city"]["center"]["latitude"],
                    "longitude": city_data["city"]["center"]["longitude"]
                },
                "bounds": city_data["city"]["bounds"],
                
                # File information
                "data_file": {
                    "filename": city_data["data_file"]["filename"],
                    "size_bytes": city_data["data_file"]["size_bytes"]
                },
                
                # Coverage information
                "search_area_km2": city_data["search_grid"]["area_km2"],
                "coverage_rate_percent": city_data["coverage"]["coverage_rate"],
                
                # Panorama counts
                "panorama_counts": {
                    "unique_panos": city_data["all_panos"]["duplicate_stats"]["total_unique_panos"],
                    "unique_google_panos": city_data["google_panos"]["duplicate_stats"]["total_unique_panos"]
                },
                
                # Age statistics for unique panoramas
                "all_panos_age_stats": city_data["all_panos"]["age_stats"],
                "google_panos_age_stats": city_data["google_panos"]["age_stats"],
                
                # Collection metadata
                "collection_info": {
                    "start_time": city_data["download"]["start_time"],
                    "end_time": city_data["download"]["end_time"],
                    "duration_seconds": city_data["download"]["duration_seconds"]
                },

                # Add city-specific histograms
                "histogram_of_capture_dates_by_year": {
                    "all_panos": city_data["all_panos"]["histogram_of_capture_dates_by_year"],
                    "google_panos": city_data["google_panos"]["histogram_of_capture_dates_by_year"]
                }
            }
            
            cities_data.append(city_summary)
            
        except Exception as e:
            import traceback
            logger.error(f"Error processing {json_file}: {str(e)}")
            logger.error("Full traceback:")
            logger.error(traceback.format_exc())

    # Merge histograms from all cities
    merged_histograms = merge_capture_date_histograms(raw_city_data)
    
    # Create the final summary
    summary = {
        "cities_count": len(cities_data),
        "creation_timestamp": pd.Timestamp.now().isoformat(),
        "histogram_of_capture_dates": merged_histograms,
        "cities": cities_data
    }
    
    # Save the aggregate summary as compressed JSON
    output_path = os.path.join(json_dir, 'cities.json.gz')
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    return summary