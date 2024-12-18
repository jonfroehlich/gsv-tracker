import pandas as pd
import requests
import time
from datetime import datetime
import logging
from typing import Dict, Any, List, Tuple, Optional
from tqdm import tqdm
import geopy.distance
import os
import gzip
import shutil
import asyncio
import aiohttp
from filelock import FileLock
from pathlib import Path
import backoff

from .geoutils import get_city_location_data
from .fileutils import generate_base_filename, load_city_csv_file
from .json_summarizer import generate_aggregate_summary_as_json
from .config import METADATA_DTYPES

logger = logging.getLogger(__name__)

class DownloadError(Exception):
    """Custom exception for download-related errors."""
    pass

@backoff.on_exception(
    backoff.expo,
    (asyncio.TimeoutError, aiohttp.ClientError),
    max_tries=3,
    max_time=60
)
async def fetch_gsv_pano_metadata_async(
    lat: float,
    lon: float,
    api_key: str,
    session: aiohttp.ClientSession,
    timeout: aiohttp.ClientTimeout
) -> Dict[str, Any]:
    """
    Get the closest pano data from Google Street View API using aiohttp with retry logic.
    
    Args:
        lat: Latitude coordinate
        lon: Longitude coordinate
        api_key: Google Street View API key
        session: aiohttp ClientSession for making requests
        timeout: Request timeout settings
    
    Returns:
        Dict containing the API response
    
    Raises:
        DownloadError: If the request fails or returns invalid data after all retries
    """
    url = f"https://maps.googleapis.com/maps/api/streetview/metadata?location={lat},{lon}&key={api_key}"
    try:
        async with session.get(url, timeout=timeout) as response:
            if response.status != 200:
                raise DownloadError(f"HTTP {response.status}: {await response.text()}")
            return await response.json()
    except (asyncio.TimeoutError, aiohttp.ClientError) as e:
        logger.warning(f"Attempt failed for coordinates {lat},{lon}: {str(e)}, retrying...")
        raise  # Let backoff handle the retry
    except Exception as e:
        raise DownloadError(f"Error fetching data for coordinates {lat},{lon}: {str(e)}")

def generate_grid_points(
    origin: geopy.Point,
    width_steps: int,
    height_steps: int,
    step_length: float
) -> List[Tuple[float, float, int, int]]:
    """
    Generate all grid points for the search area with progress bar.
    
    Args:
        origin: Center point of the grid
        width_steps: Number of steps in width direction
        height_steps: Number of steps in height direction
        step_length: Distance between points in meters
    
    Returns:
        List of tuples containing (latitude, longitude, i, j) for each point
    """
    points = []
    total_points = (width_steps + 1) * (height_steps + 1)
    
    with tqdm(total=total_points, desc="Generating search grid points") as pbar:
        for i in range(-height_steps // 2, height_steps // 2 + 1):
            for j in range(-width_steps // 2, width_steps // 2 + 1):
                north_point = geopy.distance.distance(meters=i * step_length).destination(origin, 0)
                point = geopy.distance.distance(meters=j * step_length).destination(north_point, 90)
                points.append((point.latitude, point.longitude, i, j))
                pbar.update(1)
    
    return points

def get_processed_points(file_path: str) -> set:
    """
    Get set of already processed points from existing download file.
    
    Args:
        file_path: Path to the intermediate download file
    
    Returns:
        Set of (latitude, longitude) tuples for processed points
    """
    if not os.path.exists(file_path):
        return set()
    
    try:
        df = pd.read_csv(
            file_path,
            dtype=METADATA_DTYPES,
            parse_dates=['capture_date']
        )
        return {(row['query_lat'], row['query_lon']) for _, row in df.iterrows()}
    except Exception as e:
        logger.error(f"Error reading existing file: {str(e)}")
        return set()

async def process_batch_async(
    points: List[Tuple[float, float, int, int]],
    api_key: str,
    progress_queue: asyncio.Queue,
    base_file_path: str,
    write_header: bool,
    timeout: aiohttp.ClientTimeout,
    connection_limit: int,
    failed_points_queue: asyncio.Queue
) -> List[Dict]:
    """
    Process a batch of points asynchronously and save results safely.
    """
    results = []
    batch_id = int(time.time() * 1000)
    temp_file = f"{base_file_path}.batch_{batch_id}.tmp"
    lock_file = f"{base_file_path}.lock"
    
    try:
        # Create connection-limited session
        connector = aiohttp.TCPConnector(limit=connection_limit)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for lat, lon, i, j in points:
                task = fetch_gsv_pano_metadata_async(lat, lon, api_key, session, timeout)
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            batch_results = []
            for (lat, lon, i, j), response in zip(points, responses):
                if isinstance(response, Exception):
                    logger.error(f"Error processing point ({lat}, {lon}): {str(response)}")
                    await failed_points_queue.put((lat, lon, i, j))
                    continue
                
                query_timestamp = datetime.now().astimezone().isoformat()
                
                status = response['status']
                result = {
                    'query_lat': lat,
                    'query_lon': lon,
                    'query_timestamp': query_timestamp,
                    'pano_lat': None,
                    'pano_lon': None,
                    'pano_id': None,
                    'capture_date': None,
                    'copyright_info': None,
                    'status': status
                }
                
                if status == 'OK':
                    result.update({
                        'pano_lat': response['location']['lat'],
                        'pano_lon': response['location']['lng'],
                        'pano_id': response['pano_id'],
                        'copyright_info': response.get('copyright', None),
                        'capture_date': response.get('date', None)
                    })
                    if not result['capture_date']:
                        result['status'] = 'NO_DATE'
                
                batch_results.append(result)
                await progress_queue.put(1)
        
        # Save batch results to temporary file
        df_batch = pd.DataFrame(batch_results)  # First create the DataFrame
        df_batch = df_batch.astype(METADATA_DTYPES)  # Then apply the dtypes
        df_batch.to_csv(temp_file, index=False)
        
        # Create a proper lock file with content
        lock = FileLock(lock_file)
        try:
            # Add a small delay to ensure lock file is properly created
            lock.acquire(timeout=10)
            
            # Write process information to lock file
            with open(lock_file, 'w') as f:
                f.write(f"Process ID: {os.getpid()}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Batch ID: {batch_id}\n")
            
            # Perform the file operations
            if os.path.exists(base_file_path):
                df_batch.to_csv(base_file_path, mode='a', header=False, index=False)
            else:
                df_batch.to_csv(base_file_path, index=False)
                
        finally:
            # Ensure lock is released and lock file is removed
            if lock.is_locked:
                lock.release()
            try:
                os.remove(lock_file)
            except FileNotFoundError:
                pass
        
        # Clean up temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)
        
        results.extend(batch_results)
        
    except Exception as e:
        # Clean up temporary files in case of error
        for file in [temp_file, lock_file]:
            try:
                if os.path.exists(file):
                    os.remove(file)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up {file}: {cleanup_error}")
        raise DownloadError(f"Error processing batch: {str(e)}")
    
    return results

async def download_gsv_metadata_async(
    city_name: str,
    center_lat: float,
    center_lon: float,
    grid_width: float,
    grid_height: float,
    step_length: float,
    api_key: str,
    download_path: str,
    batch_size: int = 50,
    connection_limit: int = 50,
    request_timeout: float = 30.0,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Fetch GSV metadata for a city using async/await pattern with safe intermediate file saving.
    
    Args:
        city_name: Name of the city
        center_lat: Center latitude
        center_lon: Center longitude
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Distance between sample points in meters
        api_key: Google Street View API key
        download_path: Path to save data files
        batch_size: Number of requests to prepare and queue at once
        connection_limit: Maximum number of concurrent connections to the API
        request_timeout: Timeout for each request in seconds
        max_retries: Maximum number of retry attempts for failed points
    
    Returns:
        DataFrame containing the GSV metadata
    """
    start_time = time.time()
    
    logger.info(f"Examining street view data for {city_name} centered at {center_lat},{center_lon}" +
                f" with a grid of {grid_width/1000:.1f}km x {grid_height/1000:.1f}km and step_length={step_length} meters")
    logger.info(f"Using batch_size={batch_size}, connection_limit={connection_limit}")
    
    # Set up timeout
    timeout = aiohttp.ClientTimeout(total=request_timeout)
    
    # Create download directory if it doesn't exist
    Path(download_path).mkdir(parents=True, exist_ok=True)
    
    # Define file names using base filename
    base_filename = generate_base_filename(city_name, grid_width, grid_height, step_length)
    file_name = base_filename + ".csv"
    file_name_downloading = file_name + ".downloading"
    file_name_compressed = file_name + ".gz"
    file_name_with_path = os.path.join(download_path, file_name)
    file_name_downloading_with_path = os.path.join(download_path, file_name_downloading)
    file_name_compressed_with_path = os.path.join(download_path, file_name_compressed)
    failed_points_file = os.path.join(download_path, f"{base_filename}_failed_points.csv")

    try:
        # Check if compressed file exists. If it does, read it in and return the df
        if os.path.exists(file_name_compressed_with_path):
            logger.info(f"Found completed compressed file: {file_name_compressed_with_path}")
            df = load_city_csv_file(file_name_compressed_with_path)
            return {
                "df": df,
                "filename_with_path": file_name_compressed_with_path
            }

        # Calculate grid dimensions
        width_steps = int(grid_width / step_length)
        height_steps = int(grid_height / step_length)
        
        # Generate all points
        origin = geopy.Point(center_lat, center_lon)
        all_points = generate_grid_points(origin, width_steps, height_steps, step_length)
        
        # Get already processed points
        processed_points = get_processed_points(file_name_downloading_with_path)
        
        # Filter out already processed points
        remaining_points = [
            point for point in all_points 
            if (point[0], point[1]) not in processed_points
        ]
     
        print(f"Found {len(processed_points)} already processed points. {len(remaining_points)} points remaining.")
        logger.info(f"Found {len(processed_points)} already processed points. {len(remaining_points)} points remaining.")
        
        if len(remaining_points) == 0:
            logger.info("All points already processed.")
            os.rename(file_name_downloading_with_path, file_name_with_path)
        else:
            # Initialize queues
            progress_queue = asyncio.Queue()
            failed_points_queue = asyncio.Queue()
            
            # Create progress bar
            progress_bar = tqdm(
                total=len(all_points), 
                initial=len(processed_points),
                desc=f"Downloading GSV pano data for {city_name}")
            
            # Process initial points in batches
            write_header = not os.path.exists(file_name_downloading_with_path)
            for i in range(0, len(remaining_points), batch_size):
                batch_points = remaining_points[i:i + batch_size]
                await process_batch_async(
                    batch_points, 
                    api_key, 
                    progress_queue, 
                    file_name_downloading_with_path,
                    write_header,
                    timeout,
                    connection_limit,
                    failed_points_queue
                )
                write_header = False
                
                # Update progress bar
                while not progress_queue.empty():
                    await progress_queue.get()
                    progress_bar.update(1)
            
            # Process failed points with retries
            retry_count = 0
            while not failed_points_queue.empty() and retry_count < max_retries:
                retry_count += 1
                logger.info(f"Starting retry attempt {retry_count} for failed points")
                
                # Collect all failed points for this retry attempt
                failed_points = []
                while not failed_points_queue.empty():
                    failed_points.append(await failed_points_queue.get())
                
                if failed_points:
                    logger.info(f"Retrying {len(failed_points)} failed points")
                    for i in range(0, len(failed_points), batch_size):
                        batch_points = failed_points[i:i + batch_size]
                        await process_batch_async(
                            batch_points,
                            api_key,
                            progress_queue,
                            file_name_downloading_with_path,
                            False,  # Never need header for retries
                            timeout,
                            connection_limit,
                            failed_points_queue
                        )
                
                # Wait a bit before next retry
                if retry_count < max_retries and not failed_points_queue.empty():
                    await asyncio.sleep(5 * retry_count)  # Increasing delay between retries

            # Log any permanently failed points
            remaining_failed = []
            while not failed_points_queue.empty():
                point = await failed_points_queue.get()
                remaining_failed.append(point)
            
            if remaining_failed:
                logger.error(f"Failed to download data for {len(remaining_failed)} points after all retries")
                with open(failed_points_file, 'w') as f:
                    f.write("lat,lon,i,j\n")  # Write header
                    for lat, lon, i, j in remaining_failed:
                        f.write(f"{lat},{lon},{i},{j}\n")
            
            progress_bar.close()

            # Rename the downloading file to final csv
            os.rename(file_name_downloading_with_path, file_name_with_path)
        
        # Compress the final CSV file
        with open(file_name_with_path, 'rb') as f_in:
            with gzip.open(file_name_compressed_with_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove the uncompressed CSV file
        os.remove(file_name_with_path)
        
        # Read the final compressed file
        df = load_city_csv_file(file_name_compressed_with_path)
 
        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.info(f"Downloaded {len(df)} rows in {elapsed_time:.2f} seconds")
        logger.info(f"Data compressed and saved to {file_name_compressed_with_path}")
        
        return {
                "df": df,
                "filename_with_path": file_name_compressed_with_path
            }
        
    except Exception as e:
        raise DownloadError(f"Download failed: {str(e)}")