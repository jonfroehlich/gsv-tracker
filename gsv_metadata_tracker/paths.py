import os
from pathlib import Path

def get_project_root() -> str:
    """
    Get the project root directory.
    
    Returns:
        str: Path to the project root directory
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(current_dir)

def get_default_data_dir() -> str:
    """
    Get the default data directory for the current platform.
    
    Returns:
        str: Path to the default data directory
    """
    return os.path.join(get_project_root(), "data")

def get_default_vis_dir() -> str:
    """
    Get the default visualization directory for the current platform.
    
    Returns:
        str: Path to the default visualization directory
    """
    return os.path.join(get_project_root(), "vis")