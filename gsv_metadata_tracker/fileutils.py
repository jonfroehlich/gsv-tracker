import os, re
import logging
import zipfile
from typing import Tuple, Optional
import pandas as pd

logger = logging.getLogger(__name__)


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

def compress_csv(csv_path: str) -> str:
    """Compress a CSV file into a ZIP archive."""
    zip_path = csv_path.rsplit('.', 1)[0] + '.zip'
    csv_name = os.path.basename(csv_path)
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(csv_path, csv_name)
        
        os.remove(csv_path)
        logger.info(f"Successfully compressed {csv_path} to {zip_path}")
        return zip_path
    except Exception as e:
        logger.error(f"Failed to compress {csv_path}: {str(e)}")
        raise

def load_data(
    city_name: str,
    width: float,
    height: float,
    step: float,
    base_path: str
) -> Optional[pd.DataFrame]:
    """Load GSV metadata from either ZIP or CSV file."""
    csv_path, temp_path, zip_path = get_data_file_paths(
        city_name, width, height, step, base_path
    )
    
    if os.path.exists(zip_path):
        logger.info(f"Loading data from ZIP file: {zip_path}")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            with zf.open(zf.namelist()[0]) as f:
                return pd.read_csv(f, parse_dates=['capture_date'])
    
    elif os.path.exists(csv_path):
        logger.info(f"Loading data from CSV file: {csv_path}")
        df = pd.read_csv(csv_path, parse_dates=['capture_date'])
        compress_csv(csv_path)
        return df
    
    elif os.path.exists(temp_path):
        logger.info(f"Found incomplete download: {temp_path}")
        return pd.read_csv(temp_path, parse_dates=['capture_date'])
    
    return None

def save_data(
    df: pd.DataFrame,
    city_name: str,
    width: float,
    height: float,
    step: float,
    base_path: str,
    is_final: bool = False
) -> None:
    """Save GSV metadata to file."""
    csv_path, temp_path, zip_path = get_data_file_paths(
        city_name, width, height, step, base_path
    )
    
    if not is_final:
        df.to_csv(temp_path, index=False)
        logger.info(f"Saved intermediate data to: {temp_path}")
    else:
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved final data to: {csv_path}")
        
        compress_csv(csv_path)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)