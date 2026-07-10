"""Provider-agnostic download helpers shared across streetscape imagery
providers (Google Street View, Mapillary, …).

Grid generation, the common download exception, and capture-date normalization
live here so provider-specific downloaders (`download_gsv.py`,
`download_mapillary.py`, `download_gsv_history.py`) can share them without one
provider importing from another's module.
"""

from datetime import datetime

import geopy.distance
from tqdm import tqdm


class DownloadError(Exception):
    """Custom exception for download-related errors."""

    pass


def generate_grid_points(
    origin: geopy.Point, width_steps: int, height_steps: int, step_length: float
) -> list[tuple[float, float, int, int]]:
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


def standardize_capture_date(date_str: str | None) -> str | None:
    """Standardizes a capture date string to ISO 8601 format (YYYY-MM-DD).

    Providers return capture dates in various granularities (YYYY-MM-DD, YYYY-MM,
    or YYYY). This function attempts to parse the input date string using several
    common formats and converts it to a standard ISO 8601 date string.

    Args:
        date_str: The capture date string from the API response. Can be None.

    Returns:
        A string representing the date in ISO 8601 format (YYYY-MM-DD), or None if
        the input is None or if no matching format is found.
    """
    if not date_str:  # Handle None or empty strings
        return None

    formats_to_try = [
        "%Y-%m-%d",  # Most precise format (YYYY-MM-DD), try first
        "%Y-%m",  # Year and month (YYYY-MM)
        "%Y",  # Year only (YYYY)
    ]

    for fmt in formats_to_try:
        try:
            date_obj = datetime.strptime(date_str, fmt).date()  # Parse the date
            return date_obj.isoformat()  # Convert to ISO 8601 format (YYYY-MM-DD)
        except ValueError:
            continue  # If parsing fails, try the next format

    return None  # Return None if no format matches
