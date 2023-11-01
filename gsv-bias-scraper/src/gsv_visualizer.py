import matplotlib.pyplot as plt
import pandas as pd
import folium
import os
import numpy as np
import datetime
from geopy.geocoders import Nominatim
import argparse

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

def make_hist(df, output_file_path):
    """
    Plot a histogram representing the distribution of Google Street View data over time.

    Args:
    - df (pd.DataFrame): Dataframe containing Google Street View data with a 'date' column in 'YYYY-MM' format.
    - output_file_path (str): Path that stores the data

    Output:
    - A histogram showing GSV data distribution over time, including mean, median, and standard deviation, in output_file_path.
    """

    df_copy = df.copy()

    df_copy = df_copy[df_copy['date'].notna() & (df_copy['date'] != 'None')]
    df_copy['date'] = pd.to_datetime(df_copy['date'], format='%Y-%m', errors='coerce')
    df_copy = df_copy[df_copy['date'].notna()]

    plt.figure(figsize=(12, 7))
    plt.hist(df_copy['date'], bins=50, edgecolor='black', alpha=0.7)

    mean_value = df_copy['date'].mean()
    median_value = df_copy['date'].median()
    std_value = df_copy['date'].std()

    plt.text(0.02, 0.80, f'Mean: {mean_value}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.75, f'Median: {median_value}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.70, f'Standard Deviation: {std_value}', transform=plt.gca().transAxes, verticalalignment='top')

    plt.xlabel('Date')
    plt.ylabel('Frequency')
    plt.title('Distribution of Data Over Time')
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plt.xticks(rotation=45)

    plt.savefig(output_file_path)


def make_geo_graph(df, years, height, width, output_file_path):
    """
    Plot a scatter plot representing the distribution of Google Street View data in a specified region with colors indicating years.

    Args:
    - df (pd.DataFrame): Dataframe containing Google Street View data with a 'date' column in 'YYYY-MM' format.
    - years (list, optional): A list of years you want to consider for the scatter plot. Defaults to None, which considers all unique years in the df.
    - height (int, optional): Height of the bounding box from the center in meters. Defaults to 1000.
    - width (int, optional): Width of the bounding box from the center in meters. Defaults equal to value of `height`.
    - output_file_path (str): Path that stores the data

    Output:
    - A colored map visualizing the spatial distribution of GSV data in the city's bounding area, each color indicating different years, in output_file_path.
    """

    df['date'].fillna('1900-01', inplace=True)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year

    colors = {2023: '#000000', 2022: '#006400', 2021: '#009900', 2020: '#00be00', 2019: '#00e300', 2018: '#00ff00', 2017: '#33ff33', 2016: '#66ff66',
        2015: '#99ff99', 2014: '#b3ffb3', 2013: '#ccffcc', 2012: '#d9f7b1', 2011: '#e6ef99', 2010: '#f3e780', 2009: '#ffd966', 2008: '#ffc03f',
        2007: '#ffaa00', 2006: '#ff8c00', 2005: '#ff6600', 1900: '#FF4500'}

    distinct_years = df['year'].unique()
    unique_colors = [colors[year] for year in distinct_years]
    value_to_color = {value: color for value, color in zip(distinct_years, unique_colors)}
    df['color'] = df['year'].map(value_to_color)

    sorted_df = df.sort_values(by='year', ascending=False)

    def specified_years(arr):
        unique_years = sorted_df['year'].unique()

        plt.figure(figsize=(width / 50, height / 50))

        for year in unique_years:
            if year not in arr:
                continue
            year_data = df[df['year'] == year]
            plt.scatter(year_data['lon'], year_data['lat'], color=year_data['color'], label=f'Year {year}', alpha = 0.7, s = 100)

        none_data = df[df['year'] == 1900]
        plt.scatter(none_data['lon'], none_data['lat'], color=none_data['color'], label=f'None', alpha = 0.7, s = 100)

        plt.xlabel('Longitude')
        plt.ylabel('Latitude')
        plt.title('Coordinate Data with Year-based Colors')
        plt.legend(loc="upper left", markerscale=2)
        plt.grid(True)
        plt.savefig(output_file_path)

    specified_years(years)


def make_folium_map(df, years, city_center, output_file_path):
    """
    Create a Folium map displaying Google Street View data with colors indicating years.

    Args:
    - df (pd.DataFrame): DataFrame containing Google Street View data with a 'date' column.
    - year_span (list): A list of years to consider for the scatter plot.
    - city_center (tuple): Tuple of latitude and longitude representing the center of the map.
    - output_file_path (str): Path that stores the data

    Output:
    - An interactive folium map that put the colored map on top of the city's real street map, in output_file_path.
    """

    df['date'].fillna('1900-01', inplace=True)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year

    colors = {2023: '#000000', 2022: '#006400', 2021: '#009900', 2020: '#00be00', 2019: '#00e300', 2018: '#00ff00', 2017: '#33ff33', 2016: '#66ff66',
        2015: '#99ff99', 2014: '#b3ffb3', 2013: '#ccffcc', 2012: '#d9f7b1', 2011: '#e6ef99', 2010: '#f3e780', 2009: '#ffd966', 2008: '#ffc03f',
        2007: '#ffaa00', 2006: '#ff8c00', 2005: '#ff6600', 1900: '#FF4500'}

    distinct_years = df['year'].unique()
    unique_colors = [colors[year] for year in distinct_years]
    value_to_color = {value: color for value, color in zip(distinct_years, unique_colors)}
    df['color'] = df['year'].map(value_to_color)

    sorted_df = df.sort_values(by='year', ascending=False)

    m = folium.Map(location=city_center, zoom_start=12)
    for index, row in df.iterrows():
        if row['year'] != 1900 and row['year'] not in years:
            continue
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=0.01,
            color=row['color'],
            fill=True,
            fill_color=row['color'],
        ).add_to(m)

    m.save(output_file_path)

def visualize(city, output=os.getcwd(), years=np.arange(2007, datetime.datetime.now().year + 2), grid_height=1000, grid_width=-1, cell_size=30):
    """
    Visualize Google Street View (GSV) data availability in a specified city's bounding area.

    Parameters:
    - `city_name` (`str`): Name of the city you want to make visualizations.
    - `output` (`str`): Relative path to store all visualizations, CWD by default, should be the same as the path to `city_name` directory that contains the data CSV.
    - `years` (a set of `int`): Years to consider for visualization, by default from 2007 to now.
    - `height` (`int`): Half of height of the bounding box to visualize data, by default 1000 meters.
    - `width` (`int`): Half of width of the bounding box to visualize data, by default equals to `lat_radius_meter`.
    - `skipped` (`int`): Should be the same as the `skipped` of data CSV the user wants to make visualization on, by default 30 meters.

    Outputs:
    1. A histogram showing GSV data distribution over time, including mean, median, and standard deviation.
    2. A colored map visualizing the spatial distribution of GSV data in the city's bounding area, each color indicating different years.
    3. An interactive folium map that put the colored map on top of the city's real street map.
    """
    city_center = get_coordinates(city)
    if not city_center:
        print(f"Could not find coordinates for {city}. Please try another city")
        return

    if grid_width == -1:
        grid_width = grid_height
    half_lat_radius = grid_height / 2 * 0.00000899
    half_lon_radius = grid_width / 2 * 0.00001141

    if city_center[0] < 0:
        half_lat_radius = -half_lat_radius
    if city_center[1] < 0:
        half_lon_radius = -half_lon_radius

    ymin = city_center[0] - half_lat_radius
    ymax = city_center[0] + half_lat_radius
    xmin = city_center[1] - half_lon_radius
    xmax = city_center[1] + half_lon_radius

    cwd_city = output + f'/{city}'
    if not os.path.exists(cwd_city):
        print("please specify output as the directory where the scraped data is stored.")
        return
    if not os.path.exists(cwd_city + f'/{city}_{cell_size}_coords.csv'):
        print("The city with the specified cell size has not been scrapped yet.")
        return
    
    df = pd.read_csv(cwd_city + f'/{city}_{cell_size}_coords.csv', header=None, names=['lat', 'lon', 'date'])
    in_range_data = []
    for index, row in df.iterrows():
        if row['lat'] < min(ymin, ymax) or row['lat'] > max(ymin, ymax) or row['lon'] < min(xmin, xmax) or row['lon'] > max(xmin, xmax):
            continue
        if not pd.isna(row['date']) and int(row['date'][:4]) < 2005:
            continue
        in_range_data.append(row)
    in_range_df = pd.DataFrame(in_range_data)

    make_hist(in_range_df, cwd_city + f'/{city}_hist_{cell_size}_{years}_{grid_height}_{grid_width}.png')
    make_geo_graph(in_range_df, years, grid_height, grid_width, cwd_city + f'/{city}_colored_geo_{cell_size}_{years}_{grid_height}_{grid_width}.png')
    make_folium_map(in_range_df, years, city_center, cwd_city + f'/{city}_folium_{cell_size}_{years}_{grid_height}_{grid_width}.html')

def parse_arguments():
    parser = argparse.ArgumentParser(description="Visualize Google Street View (GSV) data availability in a specified city's bounding area.")
    parser.add_argument("city", type=str, help="Name of the city.")
    parser.add_argument("--output", type=str, default=os.getcwd(), help="Output path where the scraped data is stored.")
    parser.add_argument("--years", type=int, nargs="+", default=list(range(2007, datetime.datetime.now().year + 2)), help="Year range of the GSV data to visualize. Defaults to 2007 (year GSV was introduced) to current year.")
    parser.add_argument("--grid_height", type=int, default=1000, help="Height of the visualizaton area (from the city center), in meters. Defaults to 1000.")
    parser.add_argument("--grid_width", type=int, default=-1, help="Width the visualization area (from the city center), in meters. Defaults to value of height.")
    parser.add_argument("--cell_size", type=int, default=30, help="Cell size to scrape GSV data. Should be the same as the cell_sized used to scrape data.")
    return parser.parse_args()

def main():
    args = parse_arguments()
    visualize(args.city, args.output, args.years, args.grid_height, args.grid_width, args.cell_size)

if __name__ == "__main__":
    main()