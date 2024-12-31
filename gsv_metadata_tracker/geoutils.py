import pycountry # for ISO country codes
import us  # for US states

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

def get_state_abbreviation(state_name: Optional[str]) -> Optional[str]:
    """
    Get the standard two-letter abbreviation for a US state.
    Returns original string if no abbreviation is found.
    
    Args:
        state_name: Full name of the US state
        
    Returns:
        Two-letter state abbreviation, original string if not found, or None if input is None
    """
    if not state_name:
        return None
        
    try:
        state = us.states.lookup(state_name)
        return state.abbr if state else state_name
    except AttributeError:
        return state_name

def get_country_code(country_name: Optional[str]) -> Optional[str]:
    """
    Get the standard two-letter ISO country code.
    Returns original string if no code is found.
    
    Args:
        country_name: Full name of the country
        
    Returns:
        Two-letter ISO country code, original string if not found, or None if input is None
    """
    if not country_name:
        return None
        
    # Handle common variations in country names
    name_variations = {
        'United States': 'USA',
        'United States of America': 'USA',
        'USA': 'USA',
        'UK': 'United Kingdom',
        'Great Britain': 'United Kingdom',
        'Russia': 'Russian Federation',
        'South Korea': 'Korea, Republic of',
        'North Korea': "Korea, Democratic People's Republic of",
        'Taiwan': 'Taiwan, Province of China',
    }
    
    # Normalize the country name
    normalized_name = name_variations.get(country_name, country_name)
    
    try:
        # First try direct lookup
        country = pycountry.countries.get(name=normalized_name)
        if country:
            return country.alpha_2
            
        # Try fuzzy matching if direct lookup fails
        matches = pycountry.countries.search_fuzzy(normalized_name)
        if matches:
            return matches[0].alpha_2
            
    except (LookupError, AttributeError):
        pass
        
    return country_name

class EnhancedLocation:
    """
    A wrapper class for geopy Location objects that adds convenient access to country and state information.
    
    This class uses the delegation pattern to wrap the original Location object while adding new properties
    for easier access to commonly needed address components. It maintains all original Location functionality
    through delegation while providing cleaner access to country and state data that would normally require 
    multiple dictionary lookups.

    https://geopy.readthedocs.io/en/stable/index.html?highlight=location#geopy.location.Location

    Attributes:
        _location: The wrapped geopy Location object
        _country: Cached country name extracted from location.raw['address']
        _state: Cached state/region name extracted from location.raw['address']
        
    Properties:
        country: The country name, or None if not available
        state: The state/region name, or None if not available
        
    All other attributes are delegated to the wrapped Location object, so this class can be used
    as a drop-in replacement for the original Location class.
    """
    def __init__(self, location):
        """
        Initialize the enhanced location wrapper.

        Args:
            location: A geopy Location object to be wrapped

        The constructor extracts and caches country and state information from the location's
        raw address data if available. For state/region information, it checks multiple possible
        field names to account for different naming conventions across countries:
        - state: Used in US, Australia, etc.
        - county: Used in UK
        - state_district: Used in some European countries
        - region: Generic fallback used in various countries
        """
        self._location = location
        self._country = None
        self._state = None
        self._city = None
        self._country_code = None
        self._state_code = None


        logger.debug(f"EnhancedLocation created for {location}")
        
        if hasattr(location, 'raw'):
            address_data = location.raw.get('address', {})
            logger.debug(f"EnhancedLocation address_data {address_data}")

            self._country = address_data.get('country')
            self._country_code = get_country_code(self._country)
            logger.debug(f"EnhancedLocation country {self._country} and code {self._country_code} extracted from {address_data}")
            
            # Try different possible state field names
            for field in ['state', 'county', 'state_district', 'region']:
                if field in address_data:
                    self._state = address_data.get(field)
                    logger.debug(f"EnhancedLocation state {self._state} found with field {field}")
                    self._state_code = get_state_abbreviation(self._state)
                    logger.debug(f"EnhancedLocation state code {self._state_code} found with field {field}")
                    break

            # Try different possible city field names
            for field in ['city', 'town', 'village', 'municipality', 'suburb']:
                if field in address_data:
                    self._city = address_data.get(field)
                    logger.debug(f"EnhancedLocation state {self._city} found with field {field}")
                    break
            
            
    @property
    def country_code(self) -> Optional[str]:
        """
        Get the two-letter ISO country code.
        
        Returns:
            str or None: The ISO 3166-1 alpha-2 country code if available, None otherwise
        """
        return self._country_code
        
    @property
    def state_code(self) -> Optional[str]:
        """
        Get the state/region abbreviation (currently supports US states).
        
        Returns:
            str or None: The state abbreviation if available (e.g., 'CA' for California),
            None otherwise
        """
        return self._state_code
    
    @property
    def country(self) -> Optional[str]:
        """
        Get the country name.
        
        Returns:
            str or None: The country name if available, None otherwise
        """
        return self._country
        
    @property
    def state(self) -> Optional[str]:
        """
        Get the state/region name.
        
        Returns:
            str or None: The state or region name if available, None otherwise.
            This could be a state (US), county (UK), or other regional division
            depending on the country.
        """
        return self._state
    
    @property
    def city(self) -> Optional[str]:
        """
        Get the city name.
        
        Returns:
            str or None: The city name if available, None otherwise.
            This could come from various fields in the raw data:
            - city: Most common for cities
            - town: Used for smaller municipalities
            - village: Used for very small municipalities
            - municipality: Used in some countries
            - suburb: Used for city subdivisions in some areas
        """
        return self._city
        
    def __getattr__(self, name):
        """
        Delegate any unknown attribute access to the wrapped Location object.
        
        This allows the EnhancedLocation to be used anywhere a Location object
        would be used, maintaining backward compatibility while adding new features.

        Args:
            name: The name of the attribute being accessed

        Returns:
            The value of the attribute from the wrapped Location object

        Raises:
            AttributeError: If the attribute doesn't exist on the wrapped Location object
        """
        return getattr(self._location, name)

@lru_cache(maxsize=128)
def get_city_location_data(
    city_name: str, 
    center_lat: Optional[float] = None, 
    center_lng: Optional[float] = None
) -> Optional[EnhancedLocation]:
    """
    Get location information for a city including coordinates, country, and bounding box.
    If center coordinates are provided, uses them to help disambiguate common city names.
    Uses caching to avoid repeated lookups.

    If you supply center_lat and center_lng, the function will attempt to find the closest
    matching city. For example:

    # Will find Springfield, Illinois
    location = get_city_location_data("Springfield", 39.7817, -89.6501)

    # Will find Springfield, Massachusetts
    location = get_city_location_data("Springfield", 42.1015, -72.5898)
    
    Args:
        city_name: Name of the city to look up
        center_lat: Optional latitude to help disambiguate city location
        center_lng: Optional longitude to help disambiguate city location
        
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
        >>> # Basic usage
        >>> location = get_city_location_data("Paris")
        >>> 
        >>> # With disambiguation coordinates (e.g., for Springfield, IL)
        >>> location = get_city_location_data("Springfield", 39.7817, -89.6501)
        >>> if location:
        >>>     print(location.latitude, location.longitude)
        >>>     print(location.address)
        >>>     print(location.raw['address']['country'])
        >>>     bbox = location.raw['boundingbox']
        >>>     print(f"City bounds: N:{bbox[1]} S:{bbox[0]} E:{bbox[3]} W:{bbox[2]}")
    """
    if not city_name or not city_name.strip():
        logging.error("City name cannot be empty")
        return None
        
    try:
        geolocator = Nominatim(
            user_agent=NOMINATIM_USER_AGENT,
            timeout=10
        )
        
        # If center coordinates provided, use them for disambiguation
        found_loc = None
        if center_lat is not None and center_lng is not None:
            # Get multiple location results
            locations = geolocator.geocode(
                city_name,
                language="en",
                addressdetails=True,
                exactly_one=False
            )
            
            if locations:
                # Find closest location to provided coordinates
                center_point = (center_lat, center_lng)
                closest_location = min(
                    locations,
                    key=lambda loc: geodesic(
                        center_point, 
                        (loc.latitude, loc.longitude)
                    ).kilometers
                )
                logging.info(
                    f"Found closest match for {city_name} near ({center_lat}, {center_lng}): "
                    f"{closest_location.latitude}, {closest_location.longitude}"
                )
                found_loc = closest_location

        if not found_loc:    
            # If no center coordinates or no results found, fall back to basic search
            found_loc = geolocator.geocode(
                city_name,
                language="en",
                addressdetails=True
            )
        
        if found_loc is not None:
            logging.info(f"Found coordinates for {city_name}: {found_loc.latitude}, {found_loc.longitude}")
            
            print(found_loc.latitude, found_loc.longitude)
            print(found_loc.address)

            return EnhancedLocation(found_loc)
        else:
            logging.warning(f"Could not find coordinates for {city_name}")
            return None
            
    except GeocoderTimedOut:
        logging.error(f"Timeout looking up coordinates for {city_name}")
        return None
    except GeocoderUnavailable:
        logging.error(f"Geocoding service unavailable for {city_name}")
        return None
    except Exception as e:
        logging.error(f"Error looking up coordinates for {city_name}: {str(e)}")
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