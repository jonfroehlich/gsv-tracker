
## Introduction

Google Street View has become a primary scientific instrument in studying the physical world, from urban forestry to computer vision. However, little work examines where Google Street View exists and how frequently the GSV pano dataset is updated.

The `scrape` command is designed to scrap the availability of Google Street View (GSV) data in a specified city's bounding area by dividing the specified area into a discretized grid and make API request at every intersection in the grid. 

The `visualize` command is designed to visualize the availability of Google Street View (GSV) data in a specified city's bounding area. It showcases the distribution of GSV data both temporally (over time) and spatially (across the specified region).


## Step 1: Clone or download this repository to your local machine:

## Step 2: Navigate to the repository directory:

## Step 3: Create a virtual environment by using `anaconda3`

```conda env create -f environment.yml```

This might take a few mins but should end with something like

```
done
#
# To activate this environment, use
#
#     $ conda activate gsv-bias-venv
#
# To deactivate an active environment, use
#
#     $ conda deactivate
```

## Step 4: Activate the virtual environment

```conda activate gsv-bias-venv```

## Step 5: Install the command entry points:

```pip3 install .``` 

## Step 6: Set the environment variable key in `environment.yml`  as your own Google API key:

```API_KEY: "Your Goolge API Key"``` 

## Step 7: Call the command line tools:

The command line tool contains one required argument `city_name`,

```scrape Berkeley```

and four optional arguments:

```scrape Berkeley --output / --height 1500 --length 1500 --skipped 30```

- `city_name`: Name of the city to get coordinates for.
- `output`: Relative path to store all GSV data and visualization results, CWD by default.
- `height`: Half of height of the bounding box to scrap data, by default 1000 meters.
- `width`: Half of width of the bounding box to scrap data, by default equals to `lat_radius_meter`.
- `skipped`: Distance between two intersections on the gird, by default 30 meters.

if you want to make visualization based on scraper data (make sure to scrap the specific area with certain skipped step before visualize its GSV availability), use:

```visualize Berkeley --output / --years 2021 --height 1500 --length 1500 --skipped 30```

- `city_name`: Name of the city you want to make visualizations.
- `output`: Relative path to store all visualizations, CWD by default, should be the same as the path to `city_name` directory that contains the data CSV.
- `years`: Years to consider for visualization, by default from 2007 to now.
- `height`: Half of height of the bounding box to visualize data, by default 1000 meters.
- `width`: Half of width of the bounding box to visualize data, by default equals to `lat_radius_meter`.
- `skipped`: Should be the same as the `skipped` of the scraped data CSV that the user wants to make visualization on, by default 30 meters.


## Dependencies:

1. `NumPy`
2. `Folium`
4. `tqdm`
5. `Matplotlib`
6. `Pandas`
10. `httpx`
11. `tenacity`
12. `nest-asyncio`


## Key Functions and Descriptions:

1. **`get_coordinates(city_name: str) -> tuple`**

   - **Purpose**: To fetch the latitude and longitude of a specified city.
   - **Parameters**: 
     - `city_name` (`str`): Name of the city to get coordinates for.
   - **Return**: A tuple containing the latitude and longitude of the city or `None` if the city is not found.

2. **`send_maps_request(async_client, i, combined_df, pbar, sem) -> dictionary`**

   - **Purpose**: Send an asynchronous request to Google Maps API to retrieve metadata for specified coordinates.
   - **Parameters**:
      - `async_client (httpx.AsyncClient)`: An asynchronous HTTP client.
      - `i` (`int`): Index for accessing coordinates in the DataFrame.
      - `combined_df` (`pd.DataFrame`): DataFrame containing latitude and longitude coordinates.
      - `pbar` (`tqdm.tqdm`): Progress bar for tracking the progress of requests.
      - `sem` (`asyncio.Semaphore`): Semaphore for controlling concurrency.
   - **Return**: A dictionary containing latitude, longitude, and date retrieved from one API call.
   
4. **`get_dates(combined_df, max_concurrent_requests=500) -> list`**

   - **Purpose**: Asynchronously fetch Google Street View dates for a DataFrame of coordinates.
   - **Parameters**:
      - `combined_df` (`pd.DataFrame`): DataFrame containing latitude and longitude coordinates.
      - `max_concurrent_requests` (`int`): Maximum concurrent requests, by defaults 500.
   - **Return**: list: A list of rows, each row contains a lat, a lon, a date.

5. **`scrap(lats, lons, years)`**

   - **Purpose**: Fetch GSV data for a given city within specified coordinates.
   - **Parameters**: Lists of latitudes and longitudes, output path.
      - `lats` (`np.ndarray`): An array of latitudes that is going to scrap
      - `lons` (`np.ndarray`): An array of longitutdes that is going to scrap
      - `output_file_path` (`str`): Absolute path to store GSV data file (in .csv format).
   - **Outputs**: Writing a csv containing GSV availability in `output_file_path`.


6. **`make_hist(df, output_file_path)`**

   - **Purpose**: Display a histogram representing the GSV data distribution over time.
   - **Parameters**: 
     - `df` (`pd.DataFrame`): Dataframe with GSV data.
     - `output_file_path` (`str`): Absolute path to store the visualization.
   - **Outputs**: A histogram showing GSV data distribution over time, including mean, median, and standard deviation.

7. **`make_geo_graph(df, years, height, width, output_file_path)`**

   - **Purpose**: Visualize GSV data distribution in a region with year-specific colors.
   - **Parameters**:
      - `df` (`pd.DataFrame`): DataFrame containing Google Street View data.
      - `years` (a set of `int`): Years to consider for visualization.
      - `height` (`int`): Half of height of the bounding box.
      - `width` (`int`): Half of width of the bounding box.
      - `output_file_path` (`str`): Absolute path to store the visualization.
   - **Outputs**: A colored map visualizing the spatial distribution of GSV data in the city's bounding area, each color indicating different years.

8. **`make_folium_map(df, years, city_center, output_file_path)`**

   - **Purpose**: Create a Folium map displaying Google Street View data with colors indicating years.
   - **Parameters**: 
      - `df` (`pd.DataFrame`): DataFrame containing Google Street View data.
      - `years` (a set of `int`): Years to consider for visualization.
      - `city_center` (`tuple`): Tuple of latitude and longitude representing the center of the map.
      - `output_file_path` (`str`): Absolute path to store the visualization.
   - **Outputs**: An interactive folium map that put the colored map on top of the city's real street map.

9. **`GSVBias(city_name, output, height, width, skipped)`**

   - **Purpose**: The main function to scrap GSV data in a specified region.
   - **Parameters**:
      - `city_name` (`str`): Name of the city to get coordinates for.
      - `output` (`str`): Relative path to store the data CSV, CWD by default.
      - `height` (`int`): Half of height of the bounding box to scrap data, by default 1000 meters.
      - `width` (`int`): Half of width of the bounding box to scrap data, by default equals to `lat_radius_meter`.
      - `skipped` (`int`): Distance between two intersections on the gird, by default 30 meters.
   - **Outputs**: A CSV containing all GSV availability data, stored in the directory called `city_name` in `output`, uniquely defined by city name and skipped meters.

10. **`visualize(city_name, output, years, height, width, skipped)`**

   - **Purpose**: The main function to analyze and visualize GSV data in a specified region.
   - **Parameters**:
      - `city_name` (`str`): Name of the city you want to make visualizations.
      - `output` (`str`): Relative path to store all visualizations, CWD by default, should be the same as the path to `city_name` directory that contains the data CSV.
      - `years` (a set of `int`): Years to consider for visualization, by default from 2007 to now.
      - `height` (`int`): Half of height of the bounding box to visualize data, by default 1000 meters.
      - `width` (`int`): Half of width of the bounding box to visualize data, by default equals to `lat_radius_meter`.
      - `skipped` (`int`): Should be the same as the `skipped` of the scraped data CSV that the user wants to make visualization on, by default 30 meters.
   - **Outputs**: Making a histogram, a colored geo map, and a folium map based on the CSV data the user scrapped.