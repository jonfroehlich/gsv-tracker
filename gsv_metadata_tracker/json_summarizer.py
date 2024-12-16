import json
from datetime import datetime
import pandas as pd
import numpy as np
import os
from typing import Optional, Dict, Any

def calculate_pano_stats(df: pd.DataFrame, copyright_filter_condition: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate statistics for panoramas, optionally filtered by condition.
    
    Args:
        df: DataFrame containing panorama data
        filter_condition: Optional string to filter copyright info (e.g., 'Google')
    
    Returns:
        Dictionary containing panorama statistics with ages in years
    """
    if copyright_filter_condition:
        df = df[df['copyright_info'].str.contains(copyright_filter_condition, na=False)]
    
    # Filter to successful panoramas
    df = df[df['status'] == 'OK']
    
    if len(df) == 0:
        return {
            "count": 0,
            "oldest_pano_date": None,
            "newest_pano_date": None,
            "avg_pano_age_years": None,
            "median_pano_age_years": None,
            "stdev_pano_age_years": None,
            "age_percentiles_years": None
        }

    # Calculate ages in years (using 365.25 days per year to account for leap years)
    now = pd.Timestamp.now()
    ages = (now - df['capture_date']).dt.total_seconds() / (365.25 * 24 * 3600)  # Convert to years
    
    return {
        "count": len(df),
        "oldest_pano_date": df['capture_date'].min().isoformat(),
        "newest_pano_date": df['capture_date'].max().isoformat(),
        "avg_pano_age_years": float(ages.mean()),
        "median_pano_age_years": float(ages.median()),
        "stdev_pano_age_years": float(ages.std()),
        "age_percentiles_years": {
            "p10": float(ages.quantile(0.1)),
            "p25": float(ages.quantile(0.25)),
            "p75": float(ages.quantile(0.75)),
            "p90": float(ages.quantile(0.9))
        }
    }

def save_download_stats(
    csv_gz_path: str,
    df: pd.DataFrame,
    city_name: str,
    country_name: str,
    grid_width: float,
    grid_height: float,
    step_length: float
) -> None:
    """
    Save download statistics and metadata to a JSON file.
    
    Args:
        csv_gz_path: Full path to the compressed CSV file (including filename)
        df: DataFrame containing the GSV data
        city_name: Name of the city
        country_name: Name of the country
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Distance between sample points in meters
    """
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
    
    # Get start and end times from query_timestamp
    timestamps = pd.to_datetime(df['query_timestamp'])
    start_time = timestamps.min()
    end_time = timestamps.max()
    duration_seconds = (end_time - start_time).total_seconds()
    
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
            "total_points": total_points,
            "area_km2": (grid_width * grid_height) / 1_000_000
        },
        "download": {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration_seconds,
            "points_with_panos": points_with_panos,
            "points_without_panos": points_without_panos,
            "points_with_errors": points_with_errors,
            "success_rate": (points_with_panos / total_points) * 100 if total_points > 0 else 0
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
            "metadata_created": datetime.now().isoformat(),
            "timezone": datetime.now().astimezone().tzinfo.tzname(None)
        }
    }
    
    # Generate JSON path by replacing .csv.gz extension with .json
    json_path = csv_gz_path.rsplit('.csv.gz', 1)[0] + '.json'
    
    with open(json_path, 'w') as f:
        json.dump(metadata, f, indent=2)