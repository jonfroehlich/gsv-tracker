import os
import numpy as np
import folium
from tqdm import tqdm
import matplotlib.pyplot as plt
import pandas as pd
from geopy.geocoders import Nominatim
import datetime
import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
import nest_asyncio
import argparse


Jingfeng_API_KEY = "AIzaSyAKPZf-Z4LNIOTan3XrTD-WPrdXPNddGnI"


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


nest_asyncio.apply()


@retry(stop=stop_after_attempt(3), wait=wait_fixed(0.1))  # Shorter wait due to higher rate limit
async def send_maps_request(async_client, i, combined_df, pbar, sem):
    """
    Send an asynchronous request to Google Maps API to retrieve metadata for specified coordinates.

    Args:
    - async_client (httpx.AsyncClient): An asynchronous HTTP client.
    - i (int): Index for accessing coordinates in the DataFrame.
    - combined_df (pd.DataFrame): DataFrame containing latitude and longitude coordinates.
    - pbar (tqdm.tqdm): Progress bar for tracking the progress of requests.
    - sem (asyncio.Semaphore): Semaphore for controlling concurrency.

    Returns:
    - dict: Dictionary containing latitude, longitude, and date retrieved from the API.
    """

    y = combined_df.loc[i]["lat"]
    x = combined_df.loc[i]["lon"]
    location_coords = f"{y},{x}"

    base_url = 'https://maps.googleapis.com/maps/api/streetview/metadata'
    params = {
        'location': location_coords,
        'key': Jingfeng_API_KEY,
        'source': 'outdoor'
    }

    async with sem:  # Use the semaphore here
        try:
            response = await async_client.get(base_url, params=params, timeout=60.0)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            print(f"Error with request {exc.request.url!r}: {exc}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise

    pbar.update(1)
    
    metadata = response.json()
    if not metadata.get('location', None):
        return {'lat': y, 'lon': x, 'date': "None"}
    else:
        return {'lat': metadata.get('location').get('lat'), 'lon': metadata.get('location').get('lng'), 'date': metadata.get('date')}



async def get_dates(combined_df, max_concurrent_requests=500):
    """
    Asynchronously fetch Google Street View dates for a DataFrame of coordinates.

    Args:
    - combined_df (pd.DataFrame): DataFrame containing latitude and longitude coordinates.
    - max_concurrent_requests (int, optional): Maximum concurrent requests. Defaults to 500.

    Returns:
    - list: A list of rows, each row contains a lat, a lon, a date.
    """

    limits = httpx.Limits(max_connections=max_concurrent_requests, max_keepalive_connections=max_concurrent_requests)
    timeout = httpx.Timeout(5.0, connect=5.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as async_client:
        with tqdm(total=len(combined_df), desc="Fetching dates") as pbar:
            sem = asyncio.Semaphore(max_concurrent_requests)
            rows = await asyncio.gather(*(send_maps_request(async_client, i, combined_df, pbar, sem) for i in range(len(combined_df))))
    return rows


def scrap(lats, lons, output_file_path):
    """
    Scrap Google Street View data for a given city within specified coordinates.

    Args:
    - lats, lons (list): Lists containing latitude and longitude coordinates.
    - output_file_path (str): Path to save the results.

    Returns:
    - None: write a csv file in output_file_path
    """

    if os.path.isfile(output_file_path):
        prev_df = pd.read_csv(output_file_path, header=None, names=['lat', 'lon', 'date'])
        lower_bound_lon = prev_df['lon'].min()
        upper_bound_lon = prev_df['lon'].max()
        lower_bound_lat = prev_df['lat'].min()
        upper_bound_lat = prev_df['lat'].max()

    columns = ['lat', 'lon']
    combined_df = pd.DataFrame(columns=columns)

    for x in lons:
        for y in lats:
            if os.path.isfile(output_file_path) and lower_bound_lon < x < upper_bound_lon and lower_bound_lat < y < upper_bound_lat:
                continue
            new_row = {'lat': y, 'lon': x}
            combined_df.loc[len(combined_df)] = new_row        
    combined_df.reset_index(drop=True, inplace=True)

    rows = asyncio.run(get_dates(combined_df))

    final_df = pd.DataFrame(rows)

    if os.path.isfile(output_file_path):
        final_df.to_csv(output_file_path, mode='a', header=False, index=False)
    else:
        final_df.to_csv(output_file_path, header=False, index=False)


def make_hist(df, output_file_path):
    """
    Plot a histogram representing the distribution of Google Street View data over time.

    Args:
    - df (pd.DataFrame): Dataframe containing Google Street View data with a 'date' column in 'YYYY-MM' format.
    - output_file_path

    Returns:
    - None: Displays a histogram.
    """
    df_copy = df.copy()

    none_count = len(df_copy[df_copy['date'] == 'None'])
    not_none_count = len(df_copy) - none_count

    df_copy = df_copy[df_copy['date'].notna() & (df_copy['date'] != 'None')]
    df_copy['date'] = pd.to_datetime(df_copy['date'], format='%Y-%m', errors='coerce')
    df_copy = df_copy[df_copy['date'].notna()]

    plt.figure(figsize=(12, 7))
    plt.hist(df_copy['date'], bins=50, edgecolor='black', alpha=0.7)

    plt.text(0.02, 0.95, f'Total: {none_count + not_none_count}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.90, f'None Count: {none_count}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.85, f'Not None Count: {not_none_count}', transform=plt.gca().transAxes, verticalalignment='top')

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
    - output_file_path

    Returns:
    - None: Displays a scatter plot.
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
            plt.scatter(year_data['lon'], year_data['lat'], color=year_data['color'], label=f'Year {year}', alpha = 0.7, s = 50)

        none_data = df[df['year'] == 1900]
        plt.scatter(none_data['lon'], none_data['lat'], color=none_data['color'], label=f'None', alpha = 0.7, s = 50)

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
    - output_file_path

    Returns:
    - None: Displays a Folium map.
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


def GSVBias(city, output=os.getcwd(), years=np.arange(2007, datetime.datetime.now().year + 2), height=1000, width = -1, skipped=30):
    """
    Visualize Google Street View (GSV) data availability in a specified city's bounding area.

    Parameters:
    - city (str): Name of the city (double quotation mark).
    - output ()
    - years (list, optional): Year range of the GSV data to visualize. Defaults to 2007 (year GSV was introduced) to current year.
    - height (int, optional): Height of the bounding box from the center, in meters. Defaults to 1000.
    - width (int, optional): Width of the bounding box from the center, in meters. Defaults to value of `height`.
    - skipped (int, optional): Skipped meters to scrape GSV data. Defaults to 30 meters.

    Outputs:
    1. A histogram showing the availability of GSV data in the specified bounding area of the city, with mean, median, and std.
    2. A colored map visualizing the availability of GSV data.

    Returns:
    - None: The function visualizes data but does not return a value.
    """

    city_center = get_coordinates(city)
    if not city_center:
        print(f"Could not find coordinates for {city}. Please try another city")
        return

    if width == -1:
        width = height
    lat_radius = height * 0.00000899
    lon_radius = width * 0.00001141
    skipped_lon = skipped * 0.00001141
    skipped_lat = skipped * 0.00000899

    if city_center[0] < 0:
        lat_radius = -lat_radius
        skipped_lat = -skipped_lat
    if city_center[1] < 0:
        lon_radius = -lon_radius
        skipped_lon = -skipped_lon

    ymin = city_center[0] - lat_radius
    ymax = city_center[0] + lat_radius
    xmin = city_center[1] - lon_radius
    xmax = city_center[1] + lon_radius

    lons = list(np.arange(xmin, xmax, skipped_lon))
    lats = list(np.arange(ymin, ymax, skipped_lat))


    cwd_city = output + f'/{city}'
    if not os.path.exists(cwd_city):
        os.makedirs(cwd_city)

    scrap(lats, lons, cwd_city + f'/{city}_coords.csv')

    df = pd.read_csv(cwd_city + f'/{city}_coords.csv', header=None, names=['lat', 'lon', 'date'])
    in_range_data = []
    for index, row in df.iterrows():
        if row['lat'] < min(ymin, ymax) or row['lat'] > max(ymin, ymax) or row['lon'] < min(xmin, xmax) or row['lon'] > max(xmin, xmax):
            continue
        if not pd.isna(row['date']) and int(row['date'][:4]) < 2005:
            continue
        in_range_data.append(row)
    in_range_df = pd.DataFrame(in_range_data)

    make_hist(in_range_df, cwd_city + f'/{city}_hist_{years}_{height}_{width}_{skipped}.png')
    make_geo_graph(in_range_df, years, height, width, cwd_city + f'/{city}_colored_geo_{years}_{height}_{width}_{skipped}.png')
    make_folium_map(in_range_df, years, city_center, cwd_city + f'/{city}_folium_{years}_{height}_{width}_{skipped}.html')


def parse_arguments():
    parser = argparse.ArgumentParser(description="Visualize Google Street View (GSV) data availability in a specified city's bounding area.")
    parser.add_argument("city", type=str, help="Name of the city (double quotation mark).")
    parser.add_argument("--output", type=str, default=os.getcwd(), help="Output path where the GSV availability data will be stored.")
    parser.add_argument("--years", type=int, nargs="+", default=list(range(2007, datetime.datetime.now().year + 2)), help="Year range of the GSV data to visualize. Defaults to 2007 (year GSV was introduced) to current year.")
    parser.add_argument("--height", type=int, default=1000, help="Height of half the bounding box from the center, in meters. Defaults to 1000.")
    parser.add_argument("--width", type=int, default=-1, help="Width of the half bounding box from the center, in meters. Defaults to value of height.")
    parser.add_argument("--skipped", type=int, default=30, help="Skipped meters to scrape GSV data. Defaults to 30 meters.")
    return parser.parse_args()

def main():
    args = parse_arguments()
    GSVBias(args.city, args.output, args.years, args.height, args.width, args.skipped)

if __name__ == "__main__":
    main()