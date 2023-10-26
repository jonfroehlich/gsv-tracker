from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome()

#lat_coordinate, lon_coordinate, latest_date are three columns in the CITY_NAME.csv scraped by the command line tool
#pano_id is another response value of our metadata api request. I will change the scraper to scrape that as well

def get_historic_dates(pano_id, lat_coordinate, lon_coordinate, latest_date):

    wait = WebDriverWait(driver, 10)
    translated_latest_date = latest_date.replace("-", "") + "01"
    trivial_view_angle = "3a,75y,16.12h,69.03t"
    implicit_code_1 = "3m7"
    view_mode_1 = "1e1"
    view_mode_2 = "2e0"
    implicit_code_2 = "3m5"
    img_resolution_1 = "7i16384"
    img_resolution_2 = "8i8192"
    url = f"https://www.google.com/maps/@{lat_coordinate},{lon_coordinate},{trivial_view_angle}/data=!{implicit_code_1}!{view_mode_1}!{implicit_code_2}!1s{pano_id}!{view_mode_2}!5s{translated_latest_date}T000000!{img_resolution_1}!{img_resolution_2}?entry=ttu"
    driver.get(url)

    historic_dates = wait.until(EC.visibility_of_all_elements_located((By.XPATH, '//*[@id="bottom-pane"]/div/div/div/div[1]/div/div/div/div[2]/div/div/div/div[2]/div[2]')))
    print(url)
    print(historic_dates[0].text)

get_historic_dates("7dsK70eh62sdUHCzJFw64A", "37.8748726", "-122.2825191", "2022-05")