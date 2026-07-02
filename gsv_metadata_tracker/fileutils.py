import os, glob
import logging
from typing import Tuple, Optional, List
import pandas as pd
from pathlib import Path
import platform
import subprocess
import webbrowser
from .config import METADATA_DTYPES
from .paths import get_default_data_dir, get_default_vis_dir
# Filename helpers live in naming.py; re-exported here for backward compatibility.
from .naming import (
    ParsedFilename,
    generate_base_filename,
    generate_run_filename,
    parse_filename,
    sanitize_city_query_str,
)
from . import geoutils

logger = logging.getLogger(__name__)

def get_list_of_city_csv_files(data_dir = None) -> List[str]:
    if data_dir is None:
        data_dir = get_default_data_dir()

    csv_files = glob.glob(os.path.join(data_dir, "**/*.csv.gz"), recursive=True)
    return csv_files

def does_city_csv_file_exist(data_dir: str, city_query_str: str,     
                             grid_width: float, grid_height: float,
                             step_length: float) -> str | None:
    """
    Check if a city CSV file exists by trying different name permutations.
    Uses location data to generate various possible filenames based on city, state, and country.
    
    Args:
        data_dir: Directory to search for CSV files
        city_query_str: Query string that may contain city, state, and/or country
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Step size in meters
        
    Returns:
        str | None: Full path to the matching file if found, None if no matching file exists
        
    Examples:
        >>> does_city_csv_file_exist("/data", "Paris, France", 1000, 1000, 20)
        '/data/paris--france_width_1000_height_1000_step_20.csv.gz'  # If file exists
        >>> does_city_csv_file_exist("/data", "Springfield, IL, USA", 1000, 1000, 20)
        '/data/springfield--il--usa_width_1000_height_1000_step_20.csv.gz'  # If file exists
        >>> does_city_csv_file_exist("/data", "NonexistentCity", 1000, 1000, 20)
        None  # If no matching file exists
    """

    # Get location data to help with name permutations
    location = geoutils.get_city_location_data(city_query_str)
    if not location:
        logger.warning(f"Could not get location data for {city_query_str}")
        # Try just the raw query string as a fallback
        base_filename = generate_base_filename(city_query_str, grid_width, grid_height, step_length)
        full_path = os.path.join(data_dir, f"{base_filename}.csv.gz")
        return full_path if os.path.exists(full_path) else None

    # Generate possible name permutations based on available location data
    name_permutations = []
    
    city = location.city
    state_code = location.state_code
    state = location.state
    country_code = location.country_code
    country = location.country

    if not city:
        logger.warning(f"No city name found in location data for {city_query_str}")
        return None

    # Build permutations from most specific to least specific
    if city and state_code and country_code:
        name_permutations.append(f"{city}, {state_code}, {country_code}")
    if city and state and country_code:
        name_permutations.append(f"{city}, {state}, {country_code}")
    if city and state_code and country:
        name_permutations.append(f"{city}, {state_code}, {country}")
    if city and state and country:
        name_permutations.append(f"{city}, {state}, {country}")
    if city and state_code:
        name_permutations.append(f"{city}, {state_code}")
    if city and state:
        name_permutations.append(f"{city}, {state}")
    if city and country_code:
        name_permutations.append(f"{city}, {country_code}")
    if city and country:
        name_permutations.append(f"{city}, {country}")
    if city:
        name_permutations.append(city)

    # Try each permutation
    for city_query_str_to_test in name_permutations:
        base_filename = generate_base_filename(city_query_str_to_test, grid_width, grid_height, step_length)
        full_path = os.path.join(data_dir, f"{base_filename}.csv.gz")
        logger.debug(f"Checking for file: {full_path}")
        if os.path.exists(full_path):
            logger.info(f"Found matching file: {full_path}")
            return full_path

    logger.info(f"No matching file found for {city_query_str} with any permutation")
    return None

def load_city_csv_file(csv_path: str) -> pd.DataFrame:
    """
    Read a CSV file into a DataFrame, automatically detecting if it's gzipped based on file extension.
    Handles YYYY-MM format (most common) and YYYY-MM-DD format for capture_date.
    Uses modern pandas datetime parsing methods.
    
    Args:
        csv_path: Path to the CSV file (can be either .csv or .csv.gz)
    
    Returns:
        pd.DataFrame: Loaded and processed DataFrame
    
    Raises:
        ValueError: If the file extension is neither .csv nor .csv.gz
        FileNotFoundError: If the specified file doesn't exist
    """
    logger.debug(f"Loading CSV file: {csv_path}")

    file_path = Path(csv_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {csv_path}")
    
    # Determine compression based on file extension
    if file_path.suffix == '.gz' or str(file_path).endswith('.csv.gz'):
        compression = 'gzip'
    elif file_path.suffix == '.csv':
        compression = None
    else:
        raise ValueError(f"Unsupported file format. Expected .csv or .csv.gz, got: {file_path.suffix}")
    
    try:
        logger.debug(f"Reading CSV file with compression: {compression}")

        # Read CSV with query_timestamp as object type first
        df = pd.read_csv(
            csv_path,
            dtype=METADATA_DTYPES,
            compression=compression,
        )
        
        # Convert query_timestamp (ISO 8601 with timezone)
        df['query_timestamp'] = pd.to_datetime(df['query_timestamp'], format='ISO8601')
        
        # Convert capture_date (YYYY-MM-DD)
        df['capture_date'] = pd.to_datetime(df['capture_date'], format='%Y-%m-%d', errors='coerce')
    
        
        logger.debug(f"Loaded {len(df)} rows from {csv_path}")
        logger.debug(f"The DataFrame has columns: {df.columns} with dtypes: {df.dtypes}")

        # Print out dtypes to verify
        logger.debug("\nDataFrame dtypes after conversion:")
        for col, dtype in df.dtypes.items():
            logger.debug(f"  {col:15} {dtype}")

        return df
        
    except pd.errors.EmptyDataError:
        raise ValueError(f"The file {csv_path} is empty")
    except pd.errors.ParserError as e:
        raise ValueError(f"Error parsing file {csv_path}: {str(e)}")

def try_open_with_system_command(file_path: str) -> bool:
    """
    Attempt to open file using system-specific commands as fallback.
    
    Args:
        file_path: Path to the file to open
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        system = platform.system().lower()
        if system == 'darwin':  # macOS
            subprocess.run(['open', file_path], check=True)
        elif system == 'windows':
            subprocess.run(['start', file_path], shell=True, check=True)
        elif system == 'linux':
            subprocess.run(['xdg-open', file_path], check=True)
        else:
            return False
        return True
    except subprocess.SubprocessError:
        return False

def open_in_browser(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Open a file in the default web browser with error handling and fallback options.
    
    Args:
        file_path: Path to the file to open
    
    Returns:
        Tuple[bool, Optional[str]]: (Success status, Error message if any)
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        return False, f"File not found: {file_path}"
    
    try:
        # Convert to proper file URI based on platform
        if platform.system() == 'Windows':
            uri = path.as_uri()
        else:
            uri = f'file://{path}'
        
        # Try primary method: webbrowser module
        if webbrowser.open(uri, new=2):
            return True, None
            
        # First fallback: Try specific browsers
        for browser in ['google-chrome', 'firefox', 'safari', 'edge']:
            try:
                browser_ctrl = webbrowser.get(browser)
                if browser_ctrl.open(uri, new=2):
                    return True, None
            except webbrowser.Error:
                continue
                
        # Second fallback: system-specific commands
        if try_open_with_system_command(str(path)):
            return True, None
            
        return False, "Failed to open browser using all available methods"
        
    except Exception as e:
        return False, f"Error opening browser: {str(e)}"