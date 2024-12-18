import os, re, glob
import logging
import zipfile
from typing import Tuple, Dict, Union, Optional, List
import pandas as pd
from pathlib import Path
import platform
import subprocess
import webbrowser
from .config import METADATA_DTYPES
from .paths import get_default_data_dir, get_default_vis_dir

logger = logging.getLogger(__name__)

def get_list_of_city_csv_files(data_dir = None) -> List[str]:
    if data_dir is None:
        data_dir = get_default_data_dir()

    csv_files = glob.glob(os.path.join(data_dir, "**/*.csv.gz"), recursive=True)
    return csv_files

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

def get_default_data_dir() -> str:
    """
    Get the default data directory for the current platform.
    
    Returns:
        str: Path to the default data directory
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    data_dir = os.path.join(project_root, "data")
    return data_dir

def get_default_vis_dir() -> str:
    """
    Get the default visualization directory for the current platform.
    
    Returns:
        str: Path to the default visualization directory
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    vis_dir = os.path.join(project_root, "vis")
    return vis_dir

def sanitize_city_name(city_name: str) -> str:
    """
    Sanitize city name for use in filenames.
    
    Args:
        city_name: Raw city name
    
    Returns:
        Sanitized city name safe for filenames
    """
    # Replace spaces with underscores
    sanitized = city_name.replace(' ', '_')
    # Remove any non-alphanumeric characters (except underscores)
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', sanitized)
    # Convert to lowercase
    sanitized = sanitized.lower()
    return sanitized

def parse_filename(filename: str) -> Dict[str, Union[str, float]]:
    """
    Parse a GSV metadata filename to extract parameters.
    Expected format: city_state_width_[num]_height_[num]_step_[num].csv.gz
    
    Args:
        filename: Name of the CSV file
        
    Returns:
        Dictionary containing:
            - city_name: Name of the city
            - location_code: State/country code (e.g., 'wa', 'nl', etc.)
            - width_meters: Width of the search grid in meters
            - height_meters: Height of the search grid in meters
            - step_meters: Step size in meters
        
    Raises:
        ValueError: If filename doesn't match expected format
    """
    base = os.path.basename(filename)
    # Remove the .csv.gz extension
    base = base.replace('.csv.gz', '')
    
    # Parse the components - matching city_state_width_X_height_Y_step_Z format
    match = re.match(r'(.+?)_([a-z]+)_width_(\d+)_height_(\d+)_step_(\d+)$', base)
    if not match:
        raise ValueError(f"Filename {filename} doesn't match expected format: city_state_width_X_height_Y_step_Z.csv.gz")
    
    # Handle special cases where location code might be multi-part (e.g., taiwan, switzerland)
    city_name = match.group(1)
    location_code = match.group(2)
    
    return {
        'city_name': city_name.replace('_', ' '),  # Convert underscores to spaces in city name
        'location_code': location_code,
        'width_meters': float(match.group(3)),
        'height_meters': float(match.group(4)),
        'step_meters': float(match.group(5))
    }

def generate_base_filename(
    city_name: str,
    grid_width: float,
    grid_height: float,
    step_length: float
) -> str:
    """
    Generate base filename for GSV metadata files.
    
    Args:
        city_name: Name of the city
        grid_width: Width of search grid in meters
        grid_height: Height of search grid in meters
        step_length: Distance between sample points in meters
        
    Returns:
        Base filename without extension
    """
    safe_city_name = sanitize_city_name(city_name)
    return f"{safe_city_name}_width_{int(grid_width)}_height_{int(grid_height)}_step_{step_length}"

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