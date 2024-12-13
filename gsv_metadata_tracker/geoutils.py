from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.distance import geodesic
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def get_city_coordinates(city_name: str) -> Optional[Any]:
    """Get the latitude and longitude coordinates for a given city."""
    geolocator = Nominatim(user_agent="gsv_metadata_tracker")
    location = geolocator.geocode(city_name)
    
    if location is not None:
        logger.info(f"Found coordinates for {city_name}: {location.latitude}, {location.longitude}")
        return location
    else:
        logger.warning(f"Could not find coordinates for {city_name}")
        return None

def get_city_bounding_box(city_name: str) -> Optional[Dict[str, float]]:
    """Gets the bounding box coordinates for a given city using Nominatim."""
    geolocator = Nominatim(user_agent="gsv_metadata_tracker")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    location = geocode(city_name)
    
    if location and hasattr(location, 'raw') and 'boundingbox' in location.raw:
        bbox = location.raw['boundingbox']
        return {
            'south': float(bbox[0]),
            'west': float(bbox[2]),
            'north': float(bbox[1]),
            'east': float(bbox[3])
        }
    return None

def get_search_dimensions(
    city_name: str, 
    default_width: float, 
    default_height: float, 
    force_size: bool
) -> tuple[float, float]:
    """Get search dimensions either from city boundaries or default values."""
    
    if not force_size:
        try:
            city_bbox = get_city_bounding_box(city_name)
            if city_bbox:
                # Calculate width using middle latitude
                mid_lat = (city_bbox['north'] + city_bbox['south']) / 2
                west_point = (mid_lat, city_bbox['west'])
                east_point = (mid_lat, city_bbox['east'])
                width = geodesic(west_point, east_point).meters
                
                # Calculate height
                west_mid = (city_bbox['south'], city_bbox['west'])
                east_mid = (city_bbox['north'], city_bbox['west'])
                height = geodesic(west_mid, east_mid).meters
                
                print(f"Using inferred city boundaries: {width:.0f}m x {height:.0f}m")
                return width, height
        except Exception as e:
            print(f"Failed to infer city boundaries: {str(e)}")
    
    if force_size:
        print(f"Using forced dimensions: {default_width}m x {default_height}m")
    else:
        print(f"Using default dimensions: {default_width}m x {default_height}m")
        
    return default_width, default_height