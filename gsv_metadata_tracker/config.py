import os
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any
from .paths import get_default_data_dir

logger = logging.getLogger(__name__)

# Standard metadata schema for GSV download files
METADATA_DTYPES = {
    'query_lat': np.float64,
    'query_lon': np.float64,
    'query_timestamp': str,            # initially read as a str; stored in (ISO 8601 with timezone) 
    'pano_lat': pd.Float64Dtype(),     # nullable float
    'pano_lon': pd.Float64Dtype(),     # nullable float
    'pano_id': pd.StringDtype(),       # nullable string
    'capture_date': str,               # initially read as a str; stored in ISO 8601 format (YYYY-MM-DD)
    'copyright_info': pd.StringDtype(), # nullable string
    'status': str # status is never null
}

def load_config() -> Dict[str, Any]:
    """Load configuration from conda environment variables."""
 
    config = {
        'api_key': os.environ.get('GMAPS_API_KEY'),
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
    
    return config