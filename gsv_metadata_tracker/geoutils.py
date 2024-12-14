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
    
    width, height = default_width, default_height
    
    if force_size:
        print(f"Using forced dimensions: {default_width}m x {default_height}m")
    else:
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
                
                print(f"Using inferred city boundaries for {city_name}: {width:.0f}m x {height:.0f}m")
                logger.info(f"Using inferred city boundaries for {city_name}: {width:.0f}m x {height:.0f}m")
        except Exception as e:
            print(f"Failed to infer city boundaries: {str(e)}")
            logger.error(f"Failed to infer city boundaries: {str(e)}")
    
    area = (width * height) / 1000.0
    print(f"Search area for {city_name}: {area:,.1f} square km")
    logger.info(f"Search area for {city_name}: {area:,.1f} square km")
    
    return width, height

def get_best_folium_zoom_level(search_grid_width_in_meters: float,
                               search_grid_height_in_meters: float) -> int:
    # Calculate appropriate zoom level based on search area size
    # Folium zoom levels:
    # 20: Building level (~50m across)
    # 19: ~100m
    # 18: ~200m
    # 17: ~400m
    # 16: ~800m
    # 15: ~1.5km
    # 14: ~3km
    # 13: ~6km
    # 12: ~12km
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