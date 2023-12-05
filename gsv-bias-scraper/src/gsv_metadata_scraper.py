import sys, os
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
import pandas as pd
import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed
import nest_asyncio
import argparse
from itertools import product
import logging
import csv
import json
from utils import get_coordinates, get_default_data_dir, get_filename_with_path, get_bounding_box, get_user_coordinates

METER_TO_LATTITUDE_CONST = 0.00000899 #refer to https://stackoverflow.com/questions/639695/how-to-convert-latitude-or-longitude-to-meters
METER_TO_LONGITUDE_CONST = 40075000
GOOGLE_API_KEY = os.environ.get('google_api_key')
nest_asyncio.apply()

@retry(stop=stop_after_attempt(3), wait=wait_fixed(0.1))  # Shorter wait due to higher rate limit
async def send_maps_request(async_client, y, x, pbar, sem, lower_bound_lon, upper_bound_lon, lower_bound_lat, upper_bound_lat, output_file_path):
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
    if lower_bound_lat < y < upper_bound_lat and lower_bound_lon < x < upper_bound_lon:
        pbar.update(1)
        return
    
    location_coords = f"{y},{x}"

    GOOGLE_MAPS_API_BASE_URL = 'https://maps.googleapis.com/maps/api/streetview/metadata'

    # The GSV API is here: 
    #   https://developers.google.com/maps/documentation/streetview/metadata#required-parameters-metadata
    # You must pass either a location or a pano id. Pano ids may change over time, so GSV docs 
    # recommend using location. You also need to include an API key.
    #
    # There are a number of optional parameters as wel:
    #   https://developers.google.com/maps/documentation/streetview/metadata#optional_parameters_for_metadata_requests
    # Currently, we limit the data to outdoor images only. 
    params = {
        'location': location_coords,
        'key': GOOGLE_API_KEY,
        'source': 'outdoor'
    }

    async with sem:  # Use the semaphore here
        try:
            response = await async_client.get(GOOGLE_MAPS_API_BASE_URL, params=params, timeout=60.0)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            print(f"Error with request {exc.request.url!r}: {exc}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise
    pbar.update(1)

    # The response is a JSON object. We want to extract the location, date, and pano id.
    metadata = response.json()
    if not metadata.get('location', None):
        data_row = [{'lat': y, 
                'lon': x, 
                'query_lat': y,
                'query_lon': x,
                'pano_id' : "None",
                'date': "None",
                'status': metadata.get('status')}] # Let's store the status returned by the api
    else:
        data_row = [{'lat': metadata.get('location').get('lat'), 
                'lon': metadata.get('location').get('lng'), 
                'query_lat': y,
                'query_lon': x,
                'pano_id' : metadata.get('pano_id'),
                'date': metadata.get('date')}]
        
    header = ['lat', 'lon', 'query_lat', 'query_lon', 'pano_id', 'date', 'status']
    with open(output_file_path, mode='a', newline='') as csv_file:
        # Create a CSV DictWriter
        writer = csv.DictWriter(csv_file, fieldnames=header)

        # Check to see if the file is new. If so, write the header
        if csv_file.tell() == 0:
            writer.writeheader()

        # Write each dictionary to the CSV file
        for data in data_row:
            writer.writerow(data)



async def get_gsv_metadata(xmin, xmax, cell_size_lon, ymin, ymax, cell_size_lat, lower_bound_lon, upper_bound_lon, lower_bound_lat, upper_bound_lat, output_file_path, max_concurrent_requests=500):
    """
    Asynchronously fetch Google Street View dates for a DataFrame of coordinates.

    Args:
    - combined_df (pd.DataFrame): DataFrame containing latitude and longitude coordinates.
    - max_concurrent_requests (int, optional): Maximum concurrent requests. Defaults to 500.

    Returns:
    - list: A list of rows, each row contains a lat, a lon, a date.
    """

    # TODO: please comment the decisions for all of these parameters
    limits = httpx.Limits(max_connections=max_concurrent_requests, max_keepalive_connections=max_concurrent_requests)
    timeout = httpx.Timeout(5.0, connect=5.0)

    class CoordinateIterator:
        def __init__(self, y_start, y_end, y_step, x_start, x_end, x_step):
            self.y = y_start
            self.y_end = y_end
            self.y_step = y_step
            self.x_start = x_start
            self.x = x_start
            self.x_end = x_end
            self.x_step = x_step
            self.cnt = 0

        def __iter__(self):
            return self

        def __next__(self):
            if abs(self.y) < abs(self.y_end):
                returned_y, returned_x = self.y, self.x
                if abs(self.x) < abs(self.x_end) and abs(self.y) < abs(self.y_end):
                    self.x += self.x_step
                elif abs(self.x) >= abs(self.x_end) and abs(self.y) < abs(self.y_end):
                    self.x = self.x_start
                    self.y += self.y_step
                return [returned_y, returned_x]
            else:
                raise StopIteration
            
    coordinate_iterator = CoordinateIterator(ymin, ymax, cell_size_lat, xmin, xmax, cell_size_lon)
    total_counts = int(((abs(xmin - xmax) // abs(cell_size_lon)) + 2) * ((abs(ymin - ymax) // abs(cell_size_lat)) + 1))

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as async_client:
        with tqdm(total=total_counts, desc="Fetching dates") as pbar:
            sem = asyncio.Semaphore(max_concurrent_requests)
            await asyncio.gather(*[send_maps_request(async_client, y, x, pbar, sem, lower_bound_lon, upper_bound_lon, lower_bound_lat, upper_bound_lat, output_file_path) 
                                 for y, x in coordinate_iterator])

def scrape(xmin, xmax, cell_size_lon, ymin, ymax, cell_size_lat, output_file_path):
    """
    Scrape Google Street View data for a given city within specified coordinates.

    Args:
    - lats, lons (list): Lists containing latitude and longitude coordinates.
    - output_file_path (str): Path to save the results.

    Returns:
    - None: write a csv file in output_file_path
    """
    lower_bound_lon, upper_bound_lon, lower_bound_lat, upper_bound_lat = sys.maxsize, -sys.maxsize - 1, sys.maxsize, -sys.maxsize - 1
    if os.path.isfile(output_file_path):
        print(f"We previously found a file at {output_file_path}, reading it in...")
        prev_df = pd.read_csv(output_file_path, header=None, names=['lat', 'lon', 'query_lat', 'query_lon', 'pano_id', 'date', 'status'])
        lower_bound_lon = prev_df['lon'].min()
        upper_bound_lon = prev_df['lon'].max()
        lower_bound_lat = prev_df['lat'].min()
        upper_bound_lat = prev_df['lat'].max()
    else:
        print(f"Saving contents to {output_file_path}...")

    asyncio.run(get_gsv_metadata(xmin, xmax, cell_size_lon, ymin, ymax, cell_size_lat, lower_bound_lon, upper_bound_lon, lower_bound_lat, upper_bound_lat, output_file_path))


def GSVBias(city_name, base_output_dir, grid_height=1000, grid_width = -1, cell_size=30):
    """
    Visualize Google Street View (GSV) data availability in a specified city's bounding area.

    Parameters:
    - `city_name` (`str`): Name of the city to get coordinates for.
    - `output` (`str`): Relative path to store the data CSV, CWD by default.
    - `height` (`int`): Height of the bounding box to scrape data, by default 1000 meters.
    - `width` (`int`): Width of the bounding box to scrape data, by default equals to height
    - `skipped` (`int`): Distance between two intersections on the gird, by default 30 meters.

    Outputs:
    -A CSV containing all gsv availability data, stored in the directory called `city_name` in `output`, uniquely defined by city name and skipped meters.
    """

    city_center = get_coordinates(city_name)
    if not city_center:
        # TODO: if we can't find the city, we should also support just passing a bounding box: Done
        print(f"Could not find coordinates for {city_name}. Please enter it manually")
        ymin, ymax, xmin, xmax = get_user_coordinates()
        city_center = [(ymax + ymin) / 2, (xmax + xmin) / 2]
        grid_height = int(abs(ymax - ymin) / METER_TO_LATTITUDE_CONST)
        grid_width = int(abs(xmax - xmin) / abs(1 / (METER_TO_LONGITUDE_CONST * (np.cos(city_center[0]) / 360))))

    else:
        print(f"Coordinates for {city_name} found: {city_center}")
        (ymin, ymax, xmin, xmax) = get_bounding_box(city_center, grid_height, grid_width)
        
    if grid_width == -1:
        grid_width = grid_height

    if grid_height > 1000000 or grid_width > 1000000:
        print(f"The bounding height {grid_height} meters, width {grid_width} meters is too large. Please scrape city by city.")
        return

    cell_size_lat = cell_size * METER_TO_LATTITUDE_CONST 
    cell_size_lon = abs(cell_size * (1 / (METER_TO_LONGITUDE_CONST * (np.cos(city_center[0]) / 360))))
    #refer to https://stackoverflow.com/questions/639695/how-to-convert-latitude-or-longitude-to-meters

    if city_center[0] < 0:
        cell_size_lat = -cell_size_lat
    if city_center[1] < 0:
        cell_size_lon = -cell_size_lon

    # TODO: add in bounding box printout in miles/meters as well: Done
    print(f"Bounding box for {city_name}: [{ymin, xmin}, {ymax, xmax}]")
    print(f"Bounding box height {grid_height} meters, width {grid_width} meters")

    print(f"Will query Google Street View every {cell_size:0.1f} meters for data")

    # TODO check the math on this: Done
    print(f"This will result in roughly {int(((abs(xmin - xmax) // abs(cell_size_lon)) + 2) * ((abs(ymin - ymax) // abs(cell_size_lat)) + 1))} queries")

    print("The base_output_dir is: ", base_output_dir)
          
    data = {"ymin": ymin, "ymax": ymax, "xmin": xmin, "xmax": xmax}
    
    output_filename_with_path = get_filename_with_path(base_output_dir, city_name, grid_height, grid_width, cell_size)
    with open(os.path.join(base_output_dir, f"{city_name}/bounding_box.json"), 'w') as json_file:
        json.dump(data, json_file)
    scrape(xmin, xmax, cell_size_lon, ymin, ymax, cell_size_lat, output_filename_with_path)

def parse_arguments():
    parser = argparse.ArgumentParser(description="""
        Downloads Google Street View (GSV) metadata in a specified city's bounding area.
                                     
        Example usage:
        python gsv_metadata_scraper.py "Seattle, WA" # Downloads GSV metadata for Seattle, WA w/defaults
        python gsv_metadata_scraper.py "Berkeley, CA" --grid_width 5000 --cell_size 50 # Downloads GSV metadata for Berkeley with 5km x 5km bounding box and 50m resolution
        """, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("city", type=str, help="Name of the city.")
    parser.add_argument("--output", type=str, default=None, help="Output path where the GSV availability data will be stored.")
    parser.add_argument("--grid_height", type=int, default=1000, help="Height of the bounding box from the center, in meters. Defaults to 1000.")
    parser.add_argument("--grid_width", type=int, default=-1, help="Width of the bounding box from the center, in meters. Defaults to value of height.")
    parser.add_argument("--cell_size", type=int, default=30, help="Skipped meters to scrape GSV data. Defaults to 30 meters.")
    return parser.parse_args()

def main():
    if not GOOGLE_API_KEY:
        print(f"\nThe Google Maps API key appears not to be set!\n")
        print(f"Please set your API key as an environment variable named 'google_api_key'")
        print(f" 1. From terminal, run `conda env config vars set google_api_key=YOUR_API_KEY'")
        print(f" 2. You can verify that the key was set by running `conda env config vars list`")
        print(f" 3. You may need to reactivate your environment by running `conda activate gsv-bias-venv`\n")
        return
    else:
        print(f"\nYour Google Maps API key is set to {GOOGLE_API_KEY}\n")

    args = parse_arguments()

    base_output_dir = args.output
    # We try and default to gsv-bias-scraper/data
    if base_output_dir is None:
        base_output_dir = get_default_data_dir(os.getcwd())
        print(f"No output path specified, defaulting to '{base_output_dir}'")

    GSVBias(args.city, base_output_dir, args.grid_height, args.grid_width, args.cell_size)

if __name__ == "__main__":
    main()