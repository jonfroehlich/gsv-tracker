import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def load_config() -> Dict[str, Any]:
    """Load configuration from conda environment variables."""
    # Get the project root directory (two levels up from this file)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    data_dir = os.path.join(project_root, "data")
 
    config = {
        'api_key': os.environ.get('GMAPS_API_KEY'),
        'download_path': os.environ.get('GSV_DOWNLOAD_PATH')
    }

    if not config['api_key']:
        raise ValueError(
            "GMAPS_API_KEY not found in environment variables.\n\n"
            "1. Please set the API key using:\n"
            "  > conda env config vars set GMAPS_API_KEY=YOUR_API_KEY\n"
            "2. You will then need to reactivate your environment for the changes to take effect.\n"
            "  > conda activate gsv-tracker\n"
            "3. To check the current environment variables, use:\n"
            "  > conda env config vars list\n"
            "\nIf you do not have a Google Maps API key, you can create one at https://console.cloud.google.com/apis/credentials\n"
            "You will need to enable the Street View Static API for the key."
        )
    
    if not config['download_path']:
        logger.info(f"FYI: The GSV_DOWNLOAD_PATH not set as an environment variable, using default path: {data_dir}")
        config['download_path'] = data_dir

    # Create the data directory if it doesn't exist
    os.makedirs(config['download_path'], exist_ok=True)
    logger.info(f"Using data directory: {config['download_path']}")
    
    return config