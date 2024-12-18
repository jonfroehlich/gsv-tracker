import json
from datetime import datetime
import pandas as pd
import numpy as np
import os
from tqdm import tqdm
from typing import Optional, Dict, Any, List
import logging
from .fileutils import load_city_csv_file, get_list_of_city_csv_files, parse_filename
from .geoutils import get_city_location_data

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

def calculate_age_stats(df: pd.DataFrame, now: pd.Timestamp) -> Dict[str, Any]:
    """Helper function to calculate age statistics for panoramas with valid dates."""
    if len(df) == 0:
        return {**EMPTY_AGE_STATS, "age_percentiles_years": EMPTY_PERCENTILES}
    
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        return {
            **EMPTY_AGE_STATS,
            "count": len(df),
            "error": "capture_date is not in datetime format",
            "age_percentiles_years": EMPTY_PERCENTILES
        }
    
    valid_dates_mask = df['capture_date'].notna()
    df_with_dates = df[valid_dates_mask]
    
    if len(df_with_dates) == 0:
        return {
            **EMPTY_AGE_STATS,
            "count": len(df),
            "valid_dates_count": 0,
            "invalid_dates_count": len(df),
            "age_percentiles_years": EMPTY_PERCENTILES
        }
    
    ages = (now - df_with_dates['capture_date']).dt.total_seconds() / (365.25 * 24 * 3600)
    oldest_date = df_with_dates['capture_date'].min()
    newest_date = df_with_dates['capture_date'].max()
    
    return {
        "count": len(df),
        "valid_dates_count": len(df_with_dates),
        "invalid_dates_count": len(df) - len(df_with_dates),
        "oldest_pano_date": oldest_date.isoformat() if oldest_date is not None else None,
        "newest_pano_date": newest_date.isoformat() if newest_date is not None else None,
        "avg_pano_age_years": float(ages.mean()) if len(ages) > 0 else None,
        "median_pano_age_years": float(ages.median()) if len(ages) > 0 else None,
        "stdev_pano_age_years": float(ages.std()) if len(ages) > 0 else None,
        "age_percentiles_years": {
            "p10": float(ages.quantile(0.1)) if len(ages) > 0 else None,
            "p25": float(ages.quantile(0.25)) if len(ages) > 0 else None,
            "p75": float(ages.quantile(0.75)) if len(ages) > 0 else None,
            "p90": float(ages.quantile(0.9)) if len(ages) > 0 else None
        }
    }

def calculate_pano_stats(df: pd.DataFrame, copyright_filter_condition: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate statistics for panoramas, optionally filtered by condition.
    
    Args:
        df: DataFrame containing panorama data
        copyright_filter_condition: Optional string to filter copyright info (e.g., 'Google')
    
    Returns:
        Dictionary containing panorama statistics including status breakdown and age statistics
        for successful panoramas
    """
    # Apply copyright filter if specified
    filtered_df = df[df['copyright_info'].str.contains(copyright_filter_condition, na=False)] if copyright_filter_condition else df
    
    # Get status breakdown for all entries
    status_counts = filtered_df['status'].value_counts().to_dict()
    total_entries = len(filtered_df)
    
    # Calculate status percentages
    status_breakdown = {
        status: {
            "count": count,
            "percentage": (count / total_entries * 100) if total_entries > 0 else 0
        }
        for status, count in status_counts.items()
    }

    # Filter to successful panoramas
    ok_panos = filtered_df[filtered_df['status'] == 'OK']
    
    # Calculate duplicate pano stats
    pano_id_counts = ok_panos['pano_id'].value_counts()
    duplicate_stats = {
        "total_unique_panos": len(pano_id_counts),
        "total_pano_references": len(ok_panos),
        "duplicate_reference_count": len(ok_panos) - len(pano_id_counts),
        "most_referenced_count": int(pano_id_counts.max()) if not pano_id_counts.empty else 0,
        "panos_with_multiple_refs": int((pano_id_counts > 1).sum()),
        "average_references_per_pano": float(len(ok_panos) / len(pano_id_counts)) if len(pano_id_counts) > 0 else 0
    }

    try:
        # Get unique panoramas by taking the first occurrence of each pano_id
        unique_panos = ok_panos.drop_duplicates(subset=['pano_id'])
        
        # Calculate age stats for unique panoramas
        age_stats = calculate_age_stats(unique_panos, pd.Timestamp.now())
        
        return {
            "total_entries": total_entries,
            "status_breakdown": status_breakdown,
            "duplicate_stats": duplicate_stats,
            "age_stats": age_stats
        }
        
    except Exception as e:
        return {
            "total_entries": total_entries,
            "status_breakdown": status_breakdown,
            "duplicate_stats": duplicate_stats,
            "age_stats": {
                **EMPTY_AGE_STATS,
                "count": len(ok_panos),
                "error": str(e),
                "age_percentiles_years": EMPTY_PERCENTILES
            }
        }
    
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

def generate_missing_city_json_files(data_dir: str) -> None:
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
            
            # Reverse geocode city name with lat,lng as hints
            city_loc_data = get_city_location_data(city_name, center_lat, center_lon)

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
    Generate and save download statistics and metadata to a JSON file.

    Returns the .json filename with path
    
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

    # Generate JSON path by replacing .csv.gz extension with .json
    json_filename_with_path = csv_gz_path.rsplit('.csv.gz', 1)[0] + '.json'

    if os.path.exists(json_filename_with_path) and not force_recreate_file:
        print(f"JSON file already exists: {json_filename_with_path}; returning...")
        return json_filename_with_path
  
    # Check for any problematic conversions
    missing_dates = df[(df['status'] == 'OK') & (df['capture_date'].isna())]
    if len(missing_dates) > 0:
        print(f"Warning: Found {len(missing_dates)} rows with invalid capture dates")
        print("Sample of problematic values:")
        print(missing_dates[['status', 'capture_date']].head())

    # Calculate center coordinates from query points
    center_lat = float(df['query_lat'].mean())
    center_lon = float(df['query_lon'].mean())

    # Calculate ranges to verify grid dimensions
    lat_range = df['query_lat'].max() - df['query_lat'].min()
    lon_range = df['query_lon'].max() - df['query_lon'].min()
    diagonal_meters = np.sqrt(grid_width**2 + grid_height**2)
    
    # Calculate extents
    query_bounds = {
        "min_lat": float(df['query_lat'].min()),
        "max_lat": float(df['query_lat'].max()),
        "min_lon": float(df['query_lon'].min()),
        "max_lon": float(df['query_lon'].max())
    }
    
    # Calculate total points and success/failure counts
    total_points = len(df)
    points_with_panos = len(df[df['status'] == 'OK'])
    points_without_panos = len(df[df['status'] == 'ZERO_RESULTS'])
    points_with_errors = len(df[df['status'].isin(['ERROR', 'REQUEST_DENIED', 'INVALID_REQUEST'])])
    
    # Get start and end times from query_timestamp with error checking
    print("\nChecking timestamp formats...")

    # Convert timestamps once and store in the DataFrame
    df['query_timestamp_converted'] = pd.to_datetime(df['query_timestamp'], errors='coerce')
    problematic_timestamps = df[df['query_timestamp_converted'].isna()]

    if len(problematic_timestamps) > 0:
        print(f"\nFound {len(problematic_timestamps)} problematic timestamps:")
        print("\nOriginal problematic values:")
        for idx, row in problematic_timestamps.iterrows():
            print(f"Row {idx}: {row['query_timestamp']}")
    else:
        print("All timestamps converted successfully!")

    # Print unique timestamp formats to help identify patterns
    print("\nSample of unique timestamp formats in the data:")
    unique_formats = df['query_timestamp'].unique()
    print(unique_formats[:10])  # Show first 10 unique formats

    # Use the converted timestamps for all operations
    start_time = df['query_timestamp_converted'].min()
    end_time = df['query_timestamp_converted'].max()
    
    print(f"\nType of start_time: {type(start_time)}")
    print(f"Type of end_time: {type(end_time)}")
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}")

    try:
        duration = end_time - start_time
        duration_seconds = duration.total_seconds()
        print(f"Duration: {duration_seconds:.2f} seconds")
    except Exception as e:
        print(f"Error calculating duration: {str(e)}")
        duration_seconds = None
    
    # Calculate distance statistics for successful panos
    successful_df = df[df['status'] == 'OK'].copy()
    if len(successful_df) > 0:
        successful_df['distance_to_query'] = np.sqrt(
            (successful_df['query_lat'] - successful_df['pano_lat'])**2 +
            (successful_df['query_lon'] - successful_df['pano_lon'])**2
        ) * 111000  # Approximate conversion to meters
        
        distance_stats = {
            "min_meters": float(successful_df['distance_to_query'].min()),
            "max_meters": float(successful_df['distance_to_query'].max()),
            "avg_meters": float(successful_df['distance_to_query'].mean()),
            "median_meters": float(successful_df['distance_to_query'].median()),
            "stdev_meters": float(successful_df['distance_to_query'].std())
        }
    else:
        distance_stats = None

    metadata = {
        "data_file": {
            "filename": os.path.basename(csv_gz_path),
            "format": "csv.gz",
            "rows": len(df),
            "size_bytes": os.path.getsize(csv_gz_path)
        },
        "city": {
            "name": city_name,
            "state": state_name,
            "country": country_name,
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
            "total_search_points": total_points,
            "area_km2": (grid_width * grid_height) / 1_000_000
        },
        "download": {
            "start_time": start_time.isoformat() if start_time is not None else None,
            "end_time": end_time.isoformat() if end_time is not None else None,
            "duration_seconds": duration_seconds,
        },
        "coverage": {
            "points_with_panos": points_with_panos,
            "points_without_panos": points_without_panos,
            "points_with_errors": points_with_errors,
            "coverage_rate": (points_with_panos / total_points) * 100 if total_points > 0 else 0,
            "pano_distance_stats": distance_stats
        },
        "all_panos": calculate_pano_stats(df),
        "google_panos": calculate_pano_stats(df, copyright_filter_condition='Google'),
        "timestamps": {
            "json_file_created": datetime.now().isoformat(),
            "timezone": datetime.now().astimezone().tzinfo.tzname(None)
        }
    }
    
    with open(json_filename_with_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    return json_filename_with_path

def generate_aggregate_summary_as_json(json_dir: str) -> Dict[str, Any]:
    """
    Generate and save a summary of all city JSON files in the specified directory.
    
    Args:
        json_path: Path to directory containing city JSON files
        
    Returns:
        Dictionary containing aggregated city summaries
    """
    
    cities_data = []
    
    # Find all JSON files in directory
    json_files = [f for f in os.listdir(json_dir) if f.endswith('.json') and f != 'cities.json']
    print(f"Found {len(json_files)} JSON files in {json_dir}")

    for json_file in tqdm(json_files, desc="Processing city files", unit="file"):
        file_path = os.path.join(json_dir, json_file)
        
        try:
            with open(file_path, 'r') as f:
                city_data = json.load(f)
                
            # Extract relevant information
            city_summary = {
                # Basic information
                "city": city_data["city"]["name"],
                "state": city_data["city"]["state"],
                "country": city_data["city"]["country"],
                
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
                "all_panos_age_stats": {
                    "avg_age_years": city_data["all_panos"]["age_stats"]["avg_pano_age_years"],
                    "median_age_years": city_data["all_panos"]["age_stats"]["median_pano_age_years"],
                    "oldest_date": city_data["all_panos"]["age_stats"]["oldest_pano_date"],
                    "newest_date": city_data["all_panos"]["age_stats"]["newest_pano_date"],
                    "stdev_age_years": city_data["all_panos"]["age_stats"]["stdev_pano_age_years"],
                },

                "google_panos_age_stats": {
                    "avg_age_years": city_data["google_panos"]["age_stats"]["avg_pano_age_years"],
                    "median_age_years": city_data["google_panos"]["age_stats"]["median_pano_age_years"],
                    "oldest_date": city_data["google_panos"]["age_stats"]["oldest_pano_date"],
                    "newest_date": city_data["google_panos"]["age_stats"]["newest_pano_date"],
                    "stdev_age_years": city_data["google_panos"]["age_stats"]["stdev_pano_age_years"],
                },
                
                # Collection metadata
                "collection_info": {
                    "start_time": city_data["download"]["start_time"],
                    "end_time": city_data["download"]["end_time"],
                    "duration_seconds": city_data["download"]["duration_seconds"]
                },
            }
            
            cities_data.append(city_summary)
            
        except Exception as e:
            print(f"Error processing {json_file}: {str(e)}")
    
    # Create the final summary
    summary = {
        "cities_count": len(cities_data),
        "creation_timestamp": pd.Timestamp.now().isoformat(),
        "cities": cities_data
    }
    
    # Save to cities.json
    output_path = os.path.join(json_dir, 'cities.json')
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    return summary