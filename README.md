# GSV Tracker

GSV Tracker is a Python tool for analyzing Google Street View (GSV) coverage and temporal patterns in cities. It creates interactive visualizations showing when and where Street View imagery was captured by efficiently sampling geographic grids and querying the GSV Static API.

This research project began in 2021 by Professor Jon E. Froehlich and was also part of the [UC Berkeley Data Science Discovery Program](https://cdss.berkeley.edu/discovery/projects) in 2023 with students Joseph Chen, Wenjing Yi, and Jingfeng Yang. Here's the [original pitch sheet in Google Docs](https://docs.google.com/document/d/1hfgvS_JHRmhkVtj_LBZ2qd_TO-50L6g0crlV8nTBy9s/edit?tab=t.0).

## 1. Setup and Installation

We recommend using a standard Python virtual environment (`.venv`) to manage dependencies.

1. **Clone the repository:**

```bash
git clone https://github.com/yourusername/gsv-tracker.git
cd gsv-tracker
```

2. **Create a virtual environment:**

```bash
python -m venv .venv
```

3. **Activate the environment:**

**Mac/Linux:**

```bash
source .venv/bin/activate
```

**Windows:**

```cmd
.venv\Scripts\activate
```

4. **Install dependencies:**

```bash
pip install -r requirements.txt
```

## 2. Available Scripts

The repository includes several scripts divided into core data collection tools and data utility scripts.

### Core Data Collection Tools

* **`gsv_tracker.py`**: The primary asynchronous data collection script. It is highly efficient and designed for large geographic areas.
* **`gsv_tracker_single.py`**: A single-threaded version of the tracker. It is slower but ideal for testing, debugging, baseline comparisons, or running on systems with limited resources.
* **`run_cities.py`**: A batch-processing wrapper that allows you to run `gsv_tracker.py` across multiple cities sequentially by reading configurations from a text file (e.g., `cities.txt`).

### Data Utilities & Analysis

* **`gsv_compare_data.py`**: Compares two GSV metadata files (e.g., outputs from the async vs. single-threaded trackers) to verify data consistency and pinpoint differences.
* **`generate_json.py`**: Generates missing JSON metadata summary files for existing GSV data directories.
* **`update_json_histograms.py`**: Updates existing city `JSON.gz` files to append new daily histogram statistics calculated from the raw CSV data.

## 3. Usage Examples

### Basic Usage

To analyze a city's Street View coverage using default settings (1000m x 1000m grid, 20m steps):

```bash
python gsv_tracker.py "Seattle, WA"
```

### Preview Search Area

Before executing a large download, you can generate an HTML map to preview your search boundary:

```bash
python gsv_tracker.py "Seattle, WA" --width 2000 --height 2000 --check-boundary
```

### Tuning Concurrency (For Large Areas)

For larger queries, you can adjust the batch size and connection limits to optimize network usage against the Google API (500 requests/second limit):

```bash
python gsv_tracker.py "Portland, OR" --batch-size 200 --connection-limit 100
```

### Batch Processing Multiple Cities

Create a `cities.txt` file where each line is a standard command configuration:

```text
# cities.txt
Seattle, WA --width 2000 --height 2000 --step 25
Portland, OR --width 1500 --height 1500
Vancouver, BC
```

Then run the batch script:

```bash
python run_cities.py cities.txt --continue-on-error
```

## 4. Output Files

Depending on your parameters, the tool generates the following files in your designated `--download-dir` (defaults to `./data`):

* **`{city_name}_{width}x{height}_step{step}.csv.gz`**: The core compressed data file containing all downloaded GSV metadata.
* **`{city_name}_{width}x{height}_step{step}.json.gz`**: A JSON summary of the metadata and temporal histograms.
* **`{city_name}_{width}x{height}_step{step}_failed_points.csv`**: A log of coordinates that failed to download after all retry attempts.
* **`{city_name}_{width}x{height}_step{step}.html`**: An interactive map visualization of the coverage (unless `--no-visual` is passed).
* **`{city_name}_{width}x{height}_step{step}_search_boundary.html`**: A preview map generated when using the `--check-boundary` flag.

## Other Helpful Tools

Other helpful GSV tools, include:

Starting in 2022, [sv-map](https://sv-map.netlify.app/) archives blue Street View lines from Google Maps daily, so users can compare the evolution of Street View over time. sv-map downloads Street View coverage lines as **images**, up to a certain zoom level. To display historical coverage differences on the website, it highlights the difference in pixels between the images of different dates. 
<img width="1506" height="856" alt="image" src="https://github.com/user-attachments/assets/1fd0b35d-ae57-4a29-90d8-b81be23246fd" />

[Virtual Streets](https://virtualstreets.org/) provides a blog that describes new coverage to Google Street View

## License

Distributed under the MIT License. See `LICENSE` for more information.
