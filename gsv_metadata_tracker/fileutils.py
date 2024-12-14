import os, re
import logging
import zipfile
from typing import Tuple, Optional
import pandas as pd
from pathlib import Path
import platform
import subprocess
import webbrowser

logger = logging.getLogger(__name__)

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