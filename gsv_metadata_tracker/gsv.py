import pandas as pd
import requests
import time
from datetime import datetime
import pytz
import logging
from typing import Dict, Any
from tqdm import tqdm
import geopy.distance
import os
import gzip
import shutil
from .fileutils import generate_base_filename

logger = logging.getLogger(__name__)

def fetch_gsv_pano_metadata(lat: float, lon: float, api_key: str) -> Dict[str, Any]:
    """Get the closest pano data from Google Street View API."""
    url = f"https://maps.googleapis.com/maps/api/streetview/metadata?location={lat},{lon}&key={api_key}"
    response = requests.get(url)
    return response.json()

def download_gsv_metadata(
    city_name: str,
    center_lat: float,
    center_lon: float,
    grid_width: float,
    grid_height: float,
    step_length: float,
    api_key: str,
    download_path: str
) -> pd.DataFrame:
    """
    Fetch GSV metadata for a city, with support for resuming downloads.
    
    Args:
        city_name: Name of the city
        center_lat: Center latitude
        center_lon: Center longitude
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Distance between sample points in meters
        api_key: Google Street View API key
        download_path: Path to save data files
    
    Returns:
        DataFrame containing the GSV metadata
    """
    start_time = time.time()
    timezone = pytz.timezone('America/Los_Angeles')
    
    logger.info(f"Examining street view data for {city_name} centered at {center_lat},{center_lon}" +
                f" with a grid of {grid_width/1000:.1f}km x {grid_height/1000:.1f}km and step_length={step_length} meters")

    # Define file names
    file_name = generate_base_filename(city_name, grid_width, grid_height, step_length) + ".csv"
    file_name_downloading = file_name + ".downloading"
    file_name_compressed = file_name + ".gz"
    file_name_with_path = os.path.join(download_path, file_name)
    file_name_downloading_with_path = os.path.join(download_path, file_name_downloading)
    file_name_compressed_with_path = os.path.join(download_path, file_name_compressed)

    write_file_mode = 'a'
    write_file_header = True
    
    # Check if compressed file exists
    if os.path.exists(file_name_compressed_with_path):
        logger.info(f"Found completed compressed file: {file_name_compressed_with_path}")
        end_time = time.time()
        elapsed_time = end_time - start_time
        # Read directly from gzipped file
        df = pd.read_csv(file_name_compressed_with_path, compression='gzip', parse_dates=['capture_date'])
        logger.info(f"Loaded {len(df)} rows in {elapsed_time:.2f} seconds")
        return df

    # Calculate grid dimensions
    width_steps = int(grid_width / step_length)
    height_steps = int(grid_height / step_length)
    total_points = (width_steps + 1) * (height_steps + 1)
    
    # Create origin point
    origin = geopy.Point(center_lat, center_lon)
    
    # Initialize DataFrame with correct column types
    df = pd.DataFrame({
        'query_lat': pd.Series(dtype='float'),
        'query_lon': pd.Series(dtype='float'),
        'query_timestamp': pd.Series(dtype='str'),
        'pano_lat': pd.Series(dtype='float'),
        'pano_lon': pd.Series(dtype='float'),
        'pano_id': pd.Series(dtype='str'),
        'capture_date': pd.Series(dtype='datetime64[ns]'),
        'copyright_info': pd.Series(dtype='str'),
        'status': pd.Series(dtype='str'),
    })

    # Handle resuming from existing file
    start_i = -height_steps // 2
    start_j = -width_steps // 2
    
    if os.path.exists(file_name_downloading_with_path):
        logger.info(f"Found in-progress download: {file_name_downloading_with_path}")
        try:
            df = pd.read_csv(file_name_downloading_with_path)
            if len(df) > 0:
                last_point = df.iloc[-1]
                last_lat, last_lon = last_point['query_lat'], last_point['query_lon']
                
                # Calculate approximate grid indices for the last point
                last_north_dist = geopy.distance.distance(
                    (origin.latitude, origin.longitude),
                    (last_lat, origin.longitude)
                ).meters
                last_east_dist = geopy.distance.distance(
                    (origin.latitude, origin.longitude),
                    (origin.latitude, last_lon)
                ).meters
                
                start_i = int(round(last_north_dist / step_length)) * (-1 if last_lat < origin.latitude else 1)
                start_j = int(round(last_east_dist / step_length)) * (-1 if last_lon < origin.longitude else 1)
                
                # Move to next point
                if start_j == width_steps // 2:
                    start_i += 1
                    start_j = -width_steps // 2
                else:
                    start_j += 1
                
                write_file_header = False
                logger.info(f"Resuming from grid position i={start_i}, j={start_j}")
            
        except Exception as e:
            logger.error(f"Error reading existing file: {str(e)}")
            logger.info("Starting fresh download")
            df = pd.DataFrame(columns=df.columns)

    # Calculate initial progress
    initial = (start_i - (-height_steps // 2)) * (width_steps + 1) + (start_j - (-width_steps // 2))
    
    # Main download loop with progress bar
    with tqdm(total=total_points, initial=initial, desc=f"Downloading GSV pano data for {city_name}") as progress_bar:
        for i in range(start_i, height_steps // 2 + 1):
            j_start = start_j if i == start_i else -width_steps // 2
            
            for j in range(j_start, width_steps // 2 + 1):
                # Generate single grid point
                north_point = geopy.distance.distance(meters=i * step_length).destination(origin, 0)
                point = geopy.distance.distance(meters=j * step_length).destination(north_point, 90)
                query_lat, query_lon = point.latitude, point.longitude
                
                # Get current timestamp
                current_time = datetime.now(timezone)
                query_timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S %Z%z")
                
                # Fetch pano data
                pano_data = fetch_gsv_pano_metadata(query_lat, query_lon, api_key)
                status = pano_data['status']
                
                pano_lat = None
                pano_lon = None
                pano_id = None
                capture_date = None
                copyright_info = None
                
                if status == 'OK':
                    pano_lat = pano_data['location']['lat']
                    pano_lon = pano_data['location']['lng']
                    pano_id = pano_data['pano_id']
                    copyright_info = pano_data.get('copyright', None)
                    
                    if 'date' in pano_data:
                        capture_date = pano_data['date']
                    else:
                        status = 'NO_DATE'
                
                # Append to DataFrame and save
                df_to_append = pd.DataFrame([[query_lat, query_lon, query_timestamp,
                                           pano_lat, pano_lon, pano_id, capture_date,
                                           copyright_info, status]], columns=df.columns)
                
                df_to_append = df_to_append.astype(df.dtypes)
                df_to_append.to_csv(file_name_downloading_with_path,
                                  mode=write_file_mode,
                                  header=write_file_header,
                                  index=False)

                write_file_header = False
                df = pd.concat([df, df_to_append], ignore_index=True)
                
                progress_bar.set_postfix({"Status": status})
                progress_bar.update(1)
                
                # Add a small delay to avoid hitting API rate limits
                time.sleep(0.1)
    
    # Rename the downloading file to final csv
    os.rename(file_name_downloading_with_path, file_name_with_path)
    
    # Compress the final CSV file
    with open(file_name_with_path, 'rb') as f_in:
        with gzip.open(file_name_compressed_with_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    # Remove the uncompressed CSV file
    os.remove(file_name_with_path)
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    logger.info(f"Downloaded {len(df)} rows in {elapsed_time:.2f} seconds")
    logger.info(f"Data compressed and saved to {file_name_compressed_with_path}")
    
    return df