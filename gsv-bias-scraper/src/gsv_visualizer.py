import matplotlib.pyplot as plt
import pandas as pd
import folium
import os
import numpy as np
import datetime
from geopy.geocoders import Nominatim
import argparse
import json
from utils import get_coordinates, get_default_data_dir, get_filename_with_path, get_bounding_box, add_year_and_color_column

COLORS = {2024: '#000000', 2023: '#000000', 2022: '#006400', 2021: '#009900', 2020: '#00be00', 2019: '#00e300', 2018: '#00ff00', 2017: '#33ff33', 2016: '#66ff66',
        2015: '#99ff99', 2014: '#b3ffb3', 2013: '#ccffcc', 2012: '#d9f7b1', 2011: '#e6ef99', 2010: '#f3e780', 2009: '#ffd966', 2008: '#ffc03f',
        2007: '#ffaa00', 2006: '#ff8c00', 2005: '#ff6600'}

def make_hist_and_pie(df, output_file_path):
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
    df_copy['year'] = df_copy['date'].dt.year
    
    # Set the figure size
    plt.rcParams["figure.figsize"] = [28, 10]
    plt.rcParams["figure.autolayout"] = True

    # Figure and set of subplots
    fig, ax = plt.subplots()
    my_ticks = []
    my_bins = []
    for i in range(2006, 2025):
        my_ticks.append(datetime.datetime(i, 1, 1))
        for j in range(1, 13):
            my_bins.append(datetime.datetime(i, j, 1))

    N, bins, patches = ax.hist(df_copy['date'], bins=my_bins, edgecolor='black', linewidth=1)
    plt.xlim(datetime.datetime(2006, 1, 1), datetime.datetime(2024, 1, 1))

    # Set each bar's color and frequency label on top of the bar
    for i in range(len(patches)):
        patches[i].set_fc(COLORS[2006 + (i // 12)])
        if N[i] != 0:
            ax.text(my_bins[i + 1], N[i], f'{int(N[i])}', ha='right', va='bottom', fontsize=10)

    # Set year labels on x-axis 
    for i in range(len(N)):
        if N[i] != 0 and my_bins[i] not in my_ticks:
            my_ticks.append(my_bins[i])

    mean_value = df_copy['date'].mean()
    median_value = df_copy['date'].median()
    std_value = df_copy['date'].std()

    plt.text(0.02, 0.90, f'Total Counts: {df_copy.shape[0]}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.85, f'Mean: {mean_value}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.80, f'Median: {median_value}', transform=plt.gca().transAxes, verticalalignment='top')
    plt.text(0.02, 0.75, f'Standard Deviation: {std_value}', transform=plt.gca().transAxes, verticalalignment='top')

    plt.xlabel('Date')
    plt.ylabel('Frequency')
    plt.title('Distribution of Data Over Time')
    plt.tight_layout()
    plt.xticks(my_ticks, rotation=90)

    fig.subplots_adjust(left=0.03, right=0.97, top=0.95, bottom=0.11)

    plt.savefig(output_file_path)

def make_bar_chart(df, output_file_path):
    
    # Sample data and preprocessing
    df = add_year_and_color_column(df)
    filtered_df = df[df['year'] != 1900] # Remove rows with no data
    years = np.sort(filtered_df['year'].unique())
    proportions = [((filtered_df['year'] == i).sum() / filtered_df.shape[0] * 100) for i in years]
    colors = [COLORS[i] for i in years]

    # Create a bar chart
    fig, ax = plt.subplots()
    ax.bar(years, proportions, color=colors)

    # Add labels to the bars
    for year, proportion in zip(years, proportions):
        ax.text(year, proportion, f'{np.round(proportion, 2)}%', ha='center', va='bottom', fontsize=14)

    plt.ylim(0, 100)
    plt.xlabel('Year')
    plt.ylabel('Proportion')
    plt.title('Yearly Proportions')
    plt.xticks(years)

    # Save or display the plot
    plt.savefig(output_file_path)


def make_folium_map(df, years, city_center, output_file_path):
    """
    Create a Folium map displaying Google Street View data with colors indicating years.

    Args:
    - df (pd.DataFrame): DataFrame containing Google Street View data with a 'date' column.
    - year (list): A list of years to consider for the scatter plot.
    - city_center (tuple): Tuple of latitude and longitude representing the center of the map.
    - output_file_path (str): Path that stores the data

    Output:
    - An interactive folium map that put the colored map on top of the city's real street map, in output_file_path.
    """
    df = add_year_and_color_column(df)

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

def visualize(city_name, base_input_dir, years=np.arange(2007, datetime.datetime.now().year + 2), grid_height=1000, grid_width=-1, cell_size=30):
    """
    Visualize Google Street View (GSV) data availability in a specified city's bounding area.

    Parameters:
    - `city_name` (`str`): Name of the city you want to make visualizations.
    - `base_input_dir` (`str`): Relative path to store all visualizations, CWD by default, should be the same as the path to `city_name` directory that contains the data CSV.
    - `years` (a set of `int`): Years to consider for visualization, by default from 2007 to now.
    - `height` (`int`): Height of the bounding box to visualize data, by default 1000 meters.
    - `width` (`int`): Width of the bounding box to visualize data, by default equals to `lat_radius_meter`.
    - `skipped` (`int`): Should be the same as the `skipped` of data CSV the user wants to make visualization on, by default 30 meters.

    Outputs:
    1. A histogram showing GSV data distribution over time, including mean, median, and standard deviation.
    2. An interactive folium map that put the colored map on top of the city's real street map.
    """
    try:
        with open(os.path.join(base_input_dir, city_name, "bounding_box.json"), 'r') as json_file:
            data = json.load(json_file)

    except FileNotFoundError:
        print(f"{city_name} has not been scraped yet.")
        
    if grid_width == -1:
        grid_width = grid_height

    ymin, ymax, xmin, xmax = data["ymin"], data["ymax"], data["xmin"], data["xmax"]
    city_center = [(ymax + ymin) / 2, (xmax + xmin) / 2]

    input_filename_with_path = get_filename_with_path(base_input_dir, city_name, grid_height, grid_width, cell_size)
    print("input_filename_with_path: ", input_filename_with_path)

    if not os.path.isfile(input_filename_with_path):
        print("We could not find the input data file {input_filename_with_path}. Please double check your path.}")
        return
    
    df = pd.read_csv(input_filename_with_path, header=None, names=['lat', 'lon', 'query_lat', 'query_lon', 'pano_id', 'date', 'status'])
    in_range_data = []
    for index, row in df.iterrows():
        if row['lat'] < min(ymin, ymax) or row['lat'] > max(ymin, ymax) or row['lon'] < min(xmin, xmax) or row['lon'] > max(xmin, xmax):
            continue
        if not pd.isna(row['date']) and int(row['date'][:4]) < 2005:
            continue
        in_range_data.append(row)
    in_range_df = pd.DataFrame(in_range_data)

    output_dir = os.path.dirname(input_filename_with_path)
    hist_filename_with_path = os.path.join(output_dir, f'{city_name}_hist_{cell_size}_{years}_{grid_height}_{grid_width}.png')
    make_hist_and_pie(in_range_df, hist_filename_with_path)

    folium_filename_with_path = os.path.join(output_dir, f'{city_name}_folium_{cell_size}_{years}_{grid_height}_{grid_width}.html')
    make_folium_map(in_range_df, years, city_center, folium_filename_with_path)

    pie_filename_with_path = os.path.join(output_dir, f'{city_name}_bar_{cell_size}_{years}_{grid_height}_{grid_width}.png')
    make_bar_chart(in_range_df, pie_filename_with_path)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Visualize Google Street View (GSV) data availability in a specified city's bounding area.")
    parser.add_argument("city", type=str, help="Name of the city.")
    parser.add_argument("--data_path", type=str, default=None, help="Data path where the scraped data is stored.")
    parser.add_argument("--years", type=int, nargs="+", default=list(range(2007, datetime.datetime.now().year + 2)), help="Year range of the GSV data to visualize. Defaults to 2007 (year GSV was introduced) to current year.")
    parser.add_argument("--grid_height", type=int, default=1000, help="Height of the visualizaton area (from the city center), in meters. Defaults to 1000.")
    parser.add_argument("--grid_width", type=int, default=-1, help="Width of the visualization area (from the city center), in meters. Defaults to value of height.")
    parser.add_argument("--cell_size", type=int, default=30, help="Cell size to scrape GSV data. Should be the same as the cell_sized used to scrape data.")
    return parser.parse_args()

def main():
    args = parse_arguments()

    base_input_dir = args.data_path
    if base_input_dir is None:
        base_input_dir = get_default_data_dir(os.getcwd())
        print(f"No input path specified, defaulting to '{base_input_dir}'")

    visualize(args.city, base_input_dir, args.years, args.grid_height, args.grid_width, args.cell_size)

if __name__ == "__main__":
    main()