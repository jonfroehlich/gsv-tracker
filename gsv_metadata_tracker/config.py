import logging
import os
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Standard metadata schema for GSV download files
METADATA_DTYPES = {
    "query_lat": np.float64,
    "query_lon": np.float64,
    "query_timestamp": str,  # initially read as a str; stored in (ISO 8601 with timezone)
    "pano_lat": pd.Float64Dtype(),  # nullable float
    "pano_lon": pd.Float64Dtype(),  # nullable float
    "pano_id": pd.StringDtype(),  # nullable string
    "capture_date": str,  # initially read as a str; stored in ISO 8601 format (YYYY-MM-DD)
    "copyright_info": pd.StringDtype(),  # nullable string
    "status": str,  # status is never null
}


def load_config(provider: str = "gsv") -> dict[str, Any]:
    """
    Load the API credential for the given provider from the environment.

    gsv requires GMAPS_API_KEY; mapillary requires MAPILLARY_ACCESS_TOKEN.
    Only the requested provider's credential is required, so a machine can
    run one provider without the other's key.
    """
    if provider == "gsv":
        config = {
            "api_key": os.environ.get("GMAPS_API_KEY"),
        }
        if not config["api_key"]:
            raise ValueError(
                "GMAPS_API_KEY not found in environment variables.\n\n"
                "Option 1: Create a .env file in your project root:\n"
                "  GMAPS_API_KEY=YOUR_API_KEY\n\n"
                "Option 2: Set it as an environment variable:\n"
                "  macOS/Linux:\n"
                "    > export GMAPS_API_KEY=YOUR_API_KEY\n"
                "  Windows (Command Prompt):\n"
                "    > set GMAPS_API_KEY=YOUR_API_KEY\n"
                "  Windows (PowerShell):\n"
                "    > $env:GMAPS_API_KEY='YOUR_API_KEY'\n\n"
                "If you do not have a Google Maps API key, you can create one at "
                "https://console.cloud.google.com/apis/credentials\n"
                "You will need to enable the Street View Static API for the key."
            )
        return config

    if provider == "mapillary":
        config = {
            "access_token": os.environ.get("MAPILLARY_ACCESS_TOKEN"),
        }
        if not config["access_token"]:
            raise ValueError(
                "MAPILLARY_ACCESS_TOKEN not found in environment variables.\n\n"
                "Option 1: Add it to the .env file in your project root:\n"
                "  MAPILLARY_ACCESS_TOKEN=MLY|YOUR|TOKEN\n\n"
                "Option 2: Set it as an environment variable:\n"
                "  macOS/Linux:\n"
                "    > export MAPILLARY_ACCESS_TOKEN='MLY|YOUR|TOKEN'\n\n"
                "Create a (free) client token by registering an application at "
                "https://www.mapillary.com/dashboard/developers"
            )
        return config

    raise ValueError(f"Unknown provider {provider!r} (known: gsv, mapillary)")
