from typing import Optional, Dict, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.location import Location
from geopy.distance import geodesic
import pandas as pd
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

NOMINATIM_USER_AGENT = "gsv_metadata_tracker"

@lru_cache(maxsize=128)
def get_city_location_data(city_name: str) -> Optional[Location]:
    """
    Get location information for a city including coordinates, country, and bounding box.
    Uses caching to avoid repeated lookups.
    
    Args:
        city_name: Name of the city to look up
        
    Returns:
        Location object with these key attributes:
            - latitude: float (e.g., 48.8566)
            - longitude: float (e.g., 2.3522)
            - address: str (full formatted address)
            - raw['address']: dict with components including:
                - city: str
                - country: str
                - state: str (if available)
            - raw['boundingbox']: list of [south, north, west, east] coordinates
                Example: ['48.8155755', '48.9021560', '2.2241989', '2.4697602']
        Returns None if city not found or on error
        
    Example:
        >>> location = get_city_location_data("Paris")
        >>> if location:
        >>>     # Access basic location info
        >>>     print(location.latitude, location.longitude)  # 48.8566, 2.3522
        >>>     print(location.address)  # "Paris, Île-de-France, France"
        >>>     print(location.raw['address']['country'])  # "France"
        >>>     
        >>>     # Access bounding box
        >>>     bbox = location.raw['boundingbox']
        >>>     print(f"City bounds: N:{bbox[1]} S:{bbox[0]} E:{bbox[3]} W:{bbox[2]}")
    """
    if not city_name or not city_name.strip():
        logger.error("City name cannot be empty")
        return None
        
    try:
        geolocator = Nominatim(
            user_agent=NOMINATIM_USER_AGENT,
            timeout=10
        )
        location = geolocator.geocode(
            city_name,
            language="en",
            addressdetails=True  # Get detailed address components
        )
        
        if location is not None:
            logger.info(f"Found coordinates for {city_name}: {location.latitude}, {location.longitude}")
            return location
        else:
            logger.warning(f"Could not find coordinates for {city_name}")
            return None
            
    except GeocoderTimedOut:
        logger.error(f"Timeout looking up coordinates for {city_name}")
        return None
    except GeocoderUnavailable:
        logger.error(f"Geocoding service unavailable for {city_name}")
        return None
    except Exception as e:
        logger.error(f"Error looking up coordinates for {city_name}: {str(e)}")
        return None

def get_bounding_box(df: pd.DataFrame) -> Dict[str, float]:
    """
    Get the bounding box coordinates from a DataFrame of points.
    
    Args:
        df: DataFrame with 'pano_lat' and 'pano_lon' columns
    
    Returns:
        Dictionary with 'south', 'west', 'north', and 'east' keys
    """
    return {
        'south': df['pano_lat'].min(),
        'west': df['pano_lon'].min(),
        'north': df['pano_lat'].max(),
        'east': df['pano_lon'].max()
    }

def get_bounding_box_size(df: pd.DataFrame) -> tuple[float, float]:
    """
    Calculate the width and height of a bounding box containing all points
    using geopy's geodesic calculations.
    
    Returns:
        tuple of (width_meters, height_meters)
    """
    # Get bounding box coordinates
    min_lat = df['pano_lat'].min()
    max_lat = df['pano_lat'].max()
    min_lon = df['pano_lon'].min()
    max_lon = df['pano_lon'].max()
    
    # Calculate width using the middle latitude
    mid_lat = (min_lat + max_lat) / 2
    width = geodesic((mid_lat, min_lon), (mid_lat, max_lon)).meters
    
    # Calculate height
    height = geodesic((min_lat, min_lon), (max_lat, min_lon)).meters
    
    return width, height

def get_search_dimensions(
    city_name: str, 
    default_width: float, 
    default_height: float, 
    force_size: bool
) -> tuple[float, float]:
    """
    Calculate the width and height dimensions for a city search area.
    
    This function attempts to determine appropriate search dimensions either by:
    1. Using the provided default dimensions if force_size is True
    2. Calculating dimensions based on the city's geographic boundaries using
       OpenStreetMap data if available
    3. Falling back to default dimensions if boundary data cannot be obtained
    
    The dimensions are calculated using geodesic distances:
    - Width is measured along the middle latitude of the bounding box
    - Height is measured along the western edge of the bounding box
    
    Args:
        city_name: Name of the city to look up boundaries for
        default_width: Default width in meters to use if forced or if lookup fails
        default_height: Default height in meters to use if forced or if lookup fails
        force_size: If True, uses default dimensions regardless of available boundary data
    
    Returns:
        tuple[float, float]: A tuple of (width_meters, height_meters) representing
        the search area dimensions
        
    Example:
        >>> width, height = get_search_dimensions("Paris", 5000, 5000, False)
        Using inferred city boundaries for Paris: 11532m x 8377m
        Search area for Paris: 96.6 square km
    """
    
    width, height = default_width, default_height
    
    if force_size:
        print(f"Using forced dimensions: {default_width}m x {default_height}m")
    else:
        try:
            location = get_city_location_data(city_name)
            if location and 'boundingbox' in location.raw:
                # boundingbox is [south, north, west, east]
                bbox = location.raw['boundingbox']
                # Convert string coordinates to float
                south, north, west, east = map(float, bbox)
                
                # Calculate width using middle latitude
                mid_lat = (north + south) / 2
                west_point = (mid_lat, west)
                east_point = (mid_lat, east)
                width = geodesic(west_point, east_point).meters
                
                # Calculate height
                sw_point = (south, west)
                nw_point = (north, west)
                height = geodesic(sw_point, nw_point).meters
                
                print(f"Using inferred city boundaries for {city_name}: {width:.0f}m x {height:.0f}m")
                logger.info(f"Using inferred city boundaries for {city_name}: {width:.0f}m x {height:.0f}m")
            else:
                print(f"Could not find boundary data for {city_name}, using defaults")
                logger.warning(f"Could not find boundary data for {city_name}, using defaults")
        except Exception as e:
            print(f"Failed to infer city boundaries: {str(e)}")
            logger.error(f"Failed to infer city boundaries: {str(e)}")
    
    area = (width * height) / 1000000.0  # Convert to square km
    print(f"Search area for {city_name}: {area:,.1f} square km")
    logger.info(f"Search area for {city_name}: {area:,.1f} square km")
    
    return width, height

def get_best_folium_zoom_level(search_grid_width_in_meters: float,
                             search_grid_height_in_meters: float) -> int:
    """
    Determine the optimal Folium map zoom level based on search area dimensions.
    
    Selects the most appropriate zoom level to ensure the entire search grid is
    visible while maintaining useful detail. Uses the larger dimension between
    width and height to determine zoom level. Zoom levels correspond to these
    approximate viewing scales:
    
    Zoom | Approximate Coverage | Typical Use Case
    -----|---------------------|------------------
    20   | 50m                 | Building level detail
    19   | 100m                | City block
    18   | 200m                | Multiple blocks
    17   | 400m                | Neighborhood
    16   | 800m                | Small district
    15   | 1.5km               | Large district
    14   | 3km                 | Small city
    13   | 6km                 | Medium city
    12   | 12km+               | Large city/region
    
    Args:
        search_grid_width_in_meters: Width of the search area in meters
        search_grid_height_in_meters: Height of the search area in meters
        
    Returns:
        int: Folium zoom level between 12 (most zoomed out) and 19 (most zoomed in)
        that best fits the search area dimensions
        
    Example:
        >>> zoom = get_best_folium_zoom_level(1200, 800)
        >>> print(zoom)  # Returns 15 since max dimension (1200m) fits in 1.5km scale
        15
    """
    max_dimension = max(search_grid_width_in_meters, search_grid_height_in_meters)
    if max_dimension <= 100:
        zoom_level = 19
    elif max_dimension <= 200:
        zoom_level = 18
    elif max_dimension <= 400:
        zoom_level = 17
    elif max_dimension <= 800:
        zoom_level = 16
    elif max_dimension <= 1500:
        zoom_level = 15
    elif max_dimension <= 3000:
        zoom_level = 14
    elif max_dimension <= 6000:
        zoom_level = 13
    else:
        zoom_level = 12
    
    return zoom_level