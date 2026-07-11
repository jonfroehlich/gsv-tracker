import asyncio
import gzip
import logging
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import backoff
import geopy.distance
import pandas as pd
from filelock import FileLock
from tqdm import tqdm

from .config import METADATA_DTYPES
from .download_common import (
    DownloadError,
    generate_grid_points,
    redact_credentials,
    standardize_capture_date,
)
from .fileutils import load_city_csv_file

logger = logging.getLogger(__name__)

__all__ = ["download_gsv_metadata_async", "fetch_gsv_pano_metadata_async"]


def create_helpful_permission_error(path: str) -> str:
    """Create a helpful error message for permission issues."""
    return (
        f"Permission denied when accessing: {path}\n"
        f"This typically occurs on Windows when:\n"
        f"1. The data directory is read-only\n"
        f"2. Another program has locked the directory\n"
        f"3. You need administrator privileges\n\n"
        f"To fix this:\n"
        f"- Run your terminal as administrator\n"
        f"- Check folder permissions in File Explorer\n"
        f"- Close any programs that might be accessing the directory\n"
        f"- Try setting the command line param download-dir to a different directory using:\n"
        f"  python streetscape_tracker.py CITY_NAME --download-dir NEW_DIRECTORY\n"
    )


@backoff.on_exception(
    backoff.expo, (asyncio.TimeoutError, aiohttp.ClientError), max_tries=3, max_time=60
)
async def fetch_gsv_pano_metadata_async(
    lat: float,
    lon: float,
    api_key: str,
    session: aiohttp.ClientSession,
    timeout: aiohttp.ClientTimeout,
) -> dict[str, Any]:
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
    # Google requires the key as a query parameter, so exception/response
    # text touching this URL must be scrubbed with redact_credentials()
    # before it is logged or re-raised.
    url = f"https://maps.googleapis.com/maps/api/streetview/metadata?location={lat},{lon}&key={api_key}"
    try:
        async with session.get(url, timeout=timeout) as response:
            if response.status != 200:
                raise DownloadError(
                    f"HTTP {response.status}: {redact_credentials(await response.text())}"
                )
            return await response.json()
    except (TimeoutError, aiohttp.ClientError) as e:
        logger.warning(
            f"Attempt failed for coordinates {lat},{lon}: {redact_credentials(e)}, retrying..."
        )
        raise  # Let backoff handle the retry
    except Exception as e:
        raise DownloadError(
            f"Error fetching data for coordinates {lat},{lon}: {redact_credentials(e)}"
        ) from e


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
        df = pd.read_csv(file_path, dtype=METADATA_DTYPES)
        return {(row["query_lat"], row["query_lon"]) for _, row in df.iterrows()}
    except Exception as e:
        logger.error(f"Error reading existing file: {str(e)}")
        return set()


async def process_batch_async(
    points: list[tuple[float, float, int, int]],
    api_key: str,
    progress_queue: asyncio.Queue,
    base_file_path: str,
    timeout: aiohttp.ClientTimeout,
    connection_limit: int,
    failed_points_queue: asyncio.Queue,
) -> list[dict]:
    """
    Process a batch of points asynchronously and append results to the
    in-progress CSV under a file lock (so a second process on the same city
    can't interleave writes).
    """
    results = []
    lock_file = f"{base_file_path}.lock"

    try:
        # Create connection-limited session
        connector = aiohttp.TCPConnector(limit=connection_limit)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for lat, lon, _i, _j in points:
                task = fetch_gsv_pano_metadata_async(lat, lon, api_key, session, timeout)
                tasks.append(task)

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            batch_results = []
            for (lat, lon, i, j), response in zip(points, responses, strict=False):
                if isinstance(response, Exception):
                    logger.error(
                        f"Error processing point ({lat}, {lon}): {redact_credentials(response)}"
                    )
                    await failed_points_queue.put((lat, lon, i, j))
                    continue

                # Get the current UTC datetime
                now_utc = datetime.now(UTC)

                # Format the datetime as ISO 8601
                query_timestamp = now_utc.isoformat()

                status = response["status"]
                result = {
                    "query_lat": lat,
                    "query_lon": lon,
                    "query_timestamp": query_timestamp,
                    "pano_lat": None,
                    "pano_lon": None,
                    "pano_id": None,
                    "capture_date": None,
                    "copyright_info": None,
                    "status": status,
                }

                if status == "OK":
                    # I have found that capture_date can be formatted in a variety of formats like format='%Y-%m' (most commonly) or format='%Y-%m-%d'.
                    # So, we should standardize the data format to make it consistent and easier for others to use once archived in a file
                    capture_date_raw = response.get(
                        "date", None
                    )  # Get the raw capture date from the API response
                    capture_date_standardized = standardize_capture_date(capture_date_raw)

                    result.update(
                        {
                            "pano_lat": response["location"]["lat"],
                            "pano_lon": response["location"]["lng"],
                            "pano_id": response["pano_id"],
                            "copyright_info": response.get("copyright", None),
                            "capture_date": capture_date_standardized,
                        }
                    )
                    if not result["capture_date"]:
                        result["status"] = "NO_DATE"

                batch_results.append(result)
                await progress_queue.put(1)

        # Append batch results to the in-progress CSV under a file lock
        df_batch = pd.DataFrame(batch_results)  # First create the DataFrame
        df_batch = df_batch.astype(METADATA_DTYPES)  # Then apply the dtypes

        lock = FileLock(lock_file, timeout=10)
        try:
            with lock:
                if os.path.exists(base_file_path):
                    df_batch.to_csv(base_file_path, mode="a", header=False, index=False)
                else:
                    df_batch.to_csv(base_file_path, index=False)
        except PermissionError as e:
            raise PermissionError(
                "FileLock failure: " + create_helpful_permission_error(base_file_path)
            ) from e
        finally:
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
            except FileNotFoundError:
                pass

        results.extend(batch_results)

    except Exception as e:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception as cleanup_error:
            logger.error(f"Error cleaning up {lock_file}: {cleanup_error}")
        raise DownloadError(f"Error processing batch: {str(e)}") from e

    return results


async def download_gsv_metadata_async(
    city_name: str,
    center_lat: float,
    center_lon: float,
    grid_width: float,
    grid_height: float,
    step_length: float,
    api_key: str,
    output_csv_gz_path: str,
    batch_size: int = 50,
    connection_limit: int = 50,
    request_timeout: float = 30.0,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    Fetch GSV metadata for a city using async/await pattern with safe intermediate file saving.

    The caller decides the output filename (run-skip policy and dated naming
    live in the CLI/scheduler layer, not here). If a partial download exists
    for the same output path (a sibling .downloading file), it is resumed.

    Args:
        city_name: Name of the city (for logging/progress display only)
        center_lat: Center latitude
        center_lon: Center longitude
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Distance between sample points in meters
        api_key: Google Street View API key
        output_csv_gz_path: Full path of the .csv.gz file to write
        batch_size: Number of requests to prepare and queue at once
        connection_limit: Maximum number of concurrent connections to the API
        request_timeout: Timeout for each request in seconds
        max_retries: Maximum number of retry attempts for failed points

    Returns:
        Dict with:
            df: DataFrame containing the GSV metadata
            filename_with_path: the written .csv.gz path
            api_requests: number of API requests actually issued this call
            started_at / finished_at: UTC ISO 8601 timestamps
    """
    start_time = time.time()
    started_at = datetime.now(UTC).isoformat()
    api_requests = 0

    logger.info(
        f"Examining street view data for {city_name} centered at {center_lat},{center_lon}"
        + f" with a grid of {grid_width / 1000:.1f}km x {grid_height / 1000:.1f}km and step_length={step_length} meters"
    )
    logger.info(f"Using batch_size={batch_size}, connection_limit={connection_limit}")

    # Set up timeout
    timeout = aiohttp.ClientTimeout(total=request_timeout)

    # Derive working file paths from the requested output path
    if not output_csv_gz_path.endswith(".csv.gz"):
        raise ValueError(f"output_csv_gz_path must end in .csv.gz, got: {output_csv_gz_path}")
    file_name_compressed_with_path = output_csv_gz_path
    file_name_with_path = output_csv_gz_path[: -len(".gz")]  # .csv
    file_name_downloading_with_path = file_name_with_path + ".downloading"
    failed_points_file = output_csv_gz_path[: -len(".csv.gz")] + "_failed_points.csv"

    Path(os.path.dirname(os.path.abspath(output_csv_gz_path))).mkdir(parents=True, exist_ok=True)

    try:
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
            point for point in all_points if (point[0], point[1]) not in processed_points
        ]

        if len(processed_points) > 0:
            logger.info(
                f"Found {len(processed_points)} already processed points. {len(remaining_points)} points remaining."
            )
        else:
            logger.info(
                f"No previous points processed. Processing all points ({len(remaining_points)} total)."
            )

        if len(remaining_points) == 0:
            logger.info("All points already processed.")
            if not os.path.exists(file_name_downloading_with_path):
                raise DownloadError(
                    f"Grid produced no points to download and no partial file "
                    f"exists (grid {grid_width}x{grid_height}m, step {step_length}m)"
                )
            os.rename(file_name_downloading_with_path, file_name_with_path)
        else:
            # Initialize queues
            progress_queue = asyncio.Queue()
            failed_points_queue = asyncio.Queue()

            # Create progress bar
            progress_bar = tqdm(
                total=len(all_points),
                initial=len(processed_points),
                desc=f"Downloading GSV pano data for {city_name}",
            )

            # Process initial points in batches
            for i in range(0, len(remaining_points), batch_size):
                batch_points = remaining_points[i : i + batch_size]
                api_requests += len(batch_points)
                await process_batch_async(
                    batch_points,
                    api_key,
                    progress_queue,
                    file_name_downloading_with_path,
                    timeout,
                    connection_limit,
                    failed_points_queue,
                )

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
                        batch_points = failed_points[i : i + batch_size]
                        api_requests += len(batch_points)
                        await process_batch_async(
                            batch_points,
                            api_key,
                            progress_queue,
                            file_name_downloading_with_path,
                            timeout,
                            connection_limit,
                            failed_points_queue,
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
                logger.error(
                    f"Failed to download data for {len(remaining_failed)} points after all retries"
                )
                with open(failed_points_file, "w") as f:
                    f.write("lat,lon,i,j\n")  # Write header
                    for lat, lon, i, j in remaining_failed:
                        f.write(f"{lat},{lon},{i},{j}\n")

            progress_bar.close()

            # Rename the downloading file to final csv
            os.rename(file_name_downloading_with_path, file_name_with_path)

        # Compress the final CSV file
        with open(file_name_with_path, "rb") as f_in:
            with gzip.open(file_name_compressed_with_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove the uncompressed CSV file
        os.remove(file_name_with_path)

        # Read the final compressed file
        df = load_city_csv_file(file_name_compressed_with_path)

        end_time = time.time()
        elapsed_time = end_time - start_time
        logger.info(
            f"Downloaded {len(df)} rows in {elapsed_time:.2f} seconds "
            f"({api_requests} API requests this session)"
        )
        logger.info(f"Data compressed and saved to {file_name_compressed_with_path}")

        return {
            "df": df,
            "filename_with_path": file_name_compressed_with_path,
            "api_requests": api_requests,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        raise DownloadError(f"Download failed: {str(e)}") from e
