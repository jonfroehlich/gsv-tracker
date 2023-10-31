import os
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
import pandas as pd
from geopy.geocoders import Nominatim
import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
import nest_asyncio
import argparse

API_KEY = os.environ.get('api_key')

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
        'key': API_KEY,
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


def scrape(lats, lons, output_file_path):
    """
    Scrape Google Street View data for a given city within specified coordinates.

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

def GSVBias(city, output=os.getcwd(), height=1000, width = -1, skipped=30):
    """
    Visualize Google Street View (GSV) data availability in a specified city's bounding area.

    Parameters:
    - `city_name` (`str`): Name of the city to get coordinates for.
    - `output` (`str`): Relative path to store the data CSV, CWD by default.
    - `height` (`int`): Half of height of the bounding box to scrape data, by default 1000 meters.
    - `width` (`int`): Half of width of the bounding box to scrape data, by default equals to `lat_radius_meter`.
    - `skipped` (`int`): Distance between two intersections on the gird, by default 30 meters.

    Outputs:
    -A CSV containing all gsv availability data, stored in the directory called `city_name` in `output`, uniquely defined by city name and skipped meters.
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

    scrape(lats, lons, cwd_city + f'/{city}_{skipped}_coords.csv')


def parse_arguments():
    parser = argparse.ArgumentParser(description="Visualize Google Street View (GSV) data availability in a specified city's bounding area.")
    parser.add_argument("city", type=str, help="Name of the city.")
    parser.add_argument("--output", type=str, default=os.getcwd(), help="Output path where the GSV availability data will be stored.")
    parser.add_argument("--height", type=int, default=1000, help="Height of half the bounding box from the center, in meters. Defaults to 1000.")
    parser.add_argument("--width", type=int, default=-1, help="Width of the half bounding box from the center, in meters. Defaults to value of height.")
    parser.add_argument("--skipped", type=int, default=30, help="Skipped meters to scrape GSV data. Defaults to 30 meters.")
    return parser.parse_args()

def main():
    args = parse_arguments()
    GSVBias(args.city, args.output, args.height, args.width, args.skipped)

if __name__ == "__main__":
    main()