from itertools import product
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import argparse
import os
from utils import get_coordinates, get_default_data_dir, get_filename_with_path, get_bounding_box, add_year_and_color_column
import pandas as pd

TRIVIAL_VIEW_ANGLES = ["3a,75y,16.12h,69.03t"]
IMPLICIT_CODE_1S = ["3m7"]
VIEW_MODE_1S = ["1e1"]
VIEW_MODE_2S = ["2e0"]
IMPLICIT_CODE_2S = ["3m5"]
IMG_RESOLUTION_1S = ["7i16384"]
IMG_RESOLUTION_2S = ["8i8192"]


driver = webdriver.Chrome()

def scraper(pano_id, lat_coordinate, lon_coordinate, latest_date):

    wait = WebDriverWait(driver, 10)

    translated_latest_date = latest_date.replace("-", "") + "01"
    parameter_combinations = product(TRIVIAL_VIEW_ANGLES, IMPLICIT_CODE_1S, VIEW_MODE_1S, VIEW_MODE_2S, IMPLICIT_CODE_2S, IMG_RESOLUTION_1S, IMG_RESOLUTION_2S)

    # Iterate over all combinations
    for parameters in parameter_combinations:
        # Unpack the parameters
        trivial_view_angle, implicit_code_1, view_mode_1, view_mode_2, implicit_code_2, img_resolution_1, img_resolution_2 = parameters

        # Construct the URL using the current values of parameters
        url = f"https://www.google.com/maps/@{lat_coordinate},{lon_coordinate},{trivial_view_angle}/data=!{implicit_code_1}!{view_mode_1}!{implicit_code_2}!1s{pano_id}!{view_mode_2}!5s{translated_latest_date}T000000!{img_resolution_1}!{img_resolution_2}?entry=ttu"
        try: 
            driver.get(url)
            if "Server Error" not in driver.page_source:
                break
        except Exception as e:
            continue

    historic_dates = wait.until(EC.visibility_of_all_elements_located((By.XPATH, '//*[@id="bottom-pane"]/div/div/div/div[1]/div/div/div/div[2]/div/div/div/div[2]/div[2]')))
    return historic_dates[0].text

def get_historic_dates(city_name, base_input_dir, grid_height=1000, grid_width=-1, cell_size=30):
    input_filename_with_path = get_filename_with_path(base_input_dir, city_name, grid_height, grid_width, cell_size)
    print("input_filename_with_path: ", input_filename_with_path)

    if not os.path.isfile(input_filename_with_path):
        print("We could not find the input data file {input_filename_with_path}. Please double check your path.}")
        return

    df = pd.read_csv(input_filename_with_path, header=None, names=['lat', 'lon', 'query_lat', 'query_lon', 'pano_id', 'date', 'status'])
    df['historic_dates'] = df.apply(lambda row: scraper(row['pano_id'], row['lat'], row['lon'], row['date']), axis=1)

    df.to_csv(input_filename_with_path, index=False)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Scrape Google Street View (GSV) historic dates data in a specified city's bounding area.")
    parser.add_argument("city", type=str, help="Name of the city.")
    parser.add_argument("--data_path", type=str, default=None, help="Data path where the scraped data is stored.")
    parser.add_argument("--grid_height", type=int, default=1000, help="Height of the scraping area (from the city center), in meters. Defaults to 1000.")
    parser.add_argument("--grid_width", type=int, default=-1, help="Width of the scraping area (from the city center), in meters. Defaults to value of height.")
    parser.add_argument("--cell_size", type=int, default=30, help="Cell size to scrape GSV data. Should be the same as the cell_sized used to scrape data.")
    return parser.parse_args()

def main():
    args = parse_arguments()

    base_input_dir = args.data_path
    if base_input_dir is None:
        base_input_dir = get_default_data_dir(os.getcwd())
        print(f"No input path specified, defaulting to '{base_input_dir}'")

    get_historic_dates(args.city, base_input_dir, args.grid_height, args.grid_width, args.cell_size)

if __name__ == "__main__":
    main()