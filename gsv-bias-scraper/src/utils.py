import os # for get_default_data_dir
from geopy.geocoders import Nominatim # for getting coordinates from city name

def get_coordinates(city_name):
    """
    Get the latitude and longitude coordinates for a given city.

    Args:
    - city_name (str): The name of the city.

    Returns:
    - tuple: A tuple containing the latitude and longitude coordinates. Returns None if the city cannot be found.
    """
    geolocator = Nominatim(user_agent="city_coordinate_finder")
    location = geolocator.geocode(city_name)

    if location is not None:
        latitude, longitude = location.latitude, location.longitude
        return latitude, longitude
    else:
        return None

def get_bounding_box(city_center, grid_height, grid_width):
    half_lat_radius = grid_height / 2 * 0.00000899 # turn the unit of the height from meter to radius, and divide it by 2
    half_lon_radius = grid_width / 2 * 0.00001141 # turn the unit of the width from meter to radius, and divide it by 2

    if city_center[0] < 0:
        half_lat_radius = -half_lat_radius
    if city_center[1] < 0:
        half_lon_radius = -half_lon_radius

    ymin = city_center[0] - half_lat_radius
    ymax = city_center[0] + half_lat_radius
    xmin = city_center[1] - half_lon_radius
    xmax = city_center[1] + half_lon_radius

    return ymin, ymax, xmin, xmax

def get_default_data_dir(initial_path):
    """
    Get the default data directory for the project.
    """

    # Check if the current directory is "src"
    if os.path.basename(initial_path) == "src":
        # Get the parent directory of "src"
        parent_dir = os.path.dirname(initial_path)
        
        # Set the new directory to be the sub-directory of "data" under the parent directory
        base_output_dir = os.path.join(parent_dir, "data")    
    elif os.path.basename(initial_path) == "gsv-bias-scraper":
        base_output_dir = os.path.join(initial_path, "data")

    if not os.path.exists(base_output_dir):
        os.makedirs(base_output_dir)

    return base_output_dir

def get_filename_with_path(data_dir, city_name, grid_height, grid_width, cell_size):
    output_dir_for_city = os.path.join(data_dir, city_name)
    if not os.path.exists(output_dir_for_city):
        os.makedirs(output_dir_for_city)

    output_filename_for_city = f"{city_name}_{cell_size}_coords.csv"
    output_filename_with_path = os.path.join(output_dir_for_city, output_filename_for_city)

    return output_filename_with_path
