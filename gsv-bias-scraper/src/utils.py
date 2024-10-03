import os # for get_default_data_dir
from geopy.geocoders import Nominatim # for getting coordinates from city name
import pandas as pd

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
    
def get_user_coordinates():
    lat_lower = float(input("Enter lattitude lower bound: "))
    lat_upper = float(input("Enter lattitude upper bound: "))
    lon_lower = float(input("Enter longitude lower bound: "))
    lon_upper = float(input("Enter longitude upper bound: "))

    #To make the scraper work properly, ymin needs to be the lattitude with smaller absolute value, same for xmin
    ymin = lat_lower if abs(lat_lower) < abs(lat_upper) else lat_upper
    ymax = lat_lower if abs(lat_lower) > abs(lat_upper) else lat_upper
    xmin = lon_lower if abs(lon_lower) < abs(lon_upper) else lon_upper
    xmax = lon_lower if abs(lon_lower) > abs(lon_upper) else lon_upper
    return ymin, ymax, xmin, xmax

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

def add_year_and_color_column(df):
    df['date'].fillna('1900-01', inplace=True) #'1900-01' represents no data 
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year

    colors = {2024: '#000000', 2023: '#000000', 2022: '#006400', 2021: '#009900', 2020: '#00be00', 2019: '#00e300', 2018: '#00ff00', 2017: '#33ff33', 2016: '#66ff66',
        2015: '#99ff99', 2014: '#b3ffb3', 2013: '#ccffcc', 2012: '#d9f7b1', 2011: '#e6ef99', 2010: '#f3e780', 2009: '#ffd966', 2008: '#ffc03f',
        2007: '#ffaa00', 2006: '#ff8c00', 2005: '#ff6600', 1900: '#D3D3D3'}

    distinct_years = df['year'].unique()
    unique_colors = [colors[year] for year in distinct_years]
    value_to_color = {value: color for value, color in zip(distinct_years, unique_colors)}
    df['color'] = df['year'].map(value_to_color)

    return df