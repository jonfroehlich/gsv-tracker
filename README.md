# GSV Tracker

GSV Tracker is a Python tool for analyzing Google Street View (GSV) coverage and temporal patterns in cities **over time**. It samples geographic grids around city centers, queries the GSV Static API metadata endpoint, and produces dated snapshots per city — computing what changed between snapshots (panoramas added/removed, capture dates updated, coverage deltas) and rendering interactive visualizations of when and where Street View imagery was captured.

This research project began in 2021 by Professor Jon E. Froehlich and was also part of the [UC Berkeley Data Science Discovery Program](https://cdss.berkeley.edu/discovery/projects) in 2023 with students Joseph Chen, Wenjing Yi, and Jingfeng Yang. Here's the [original pitch sheet in Google Docs](https://docs.google.com/document/d/1hfgvS_JHRmhkVtj_LBZ2qd_TO-50L6g0crlV8nTBy9s/edit?tab=t.0). The [v1.0.0 release](https://github.com/jonfroehlich/gsv-tracker/releases/tag/v1.0.0) of this tool supported our [GeoIndustry 2025 paper](https://doi.org/10.1145/3764919.3770883) on GSV coverage and socioeconomic indicators (see also [GSVantage](https://github.com/makeabilitylab/GSVantage)).

## How temporal tracking works

Every collection run of a city produces an immutable dated snapshot
(`{city}_width_W_height_H_step_S_YYYY-MM-DD.csv.gz`). A SQLite catalog
(`data/gsv_tracker.db`) records each city's identity and **frozen grid
geometry** (so future runs sample the exact same points), every run's
stats, and run-to-run diffs. Re-running a city sooner than
`--min-days-since-last-run` (default 80) days is skipped unless you pass
`--force`. A scheduler (see `deploy/README.md`) staggers ~13 cities/day so
the full corpus re-collects roughly quarterly without exceeding API limits.

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

* **`gsv_tracker.py`**: The primary asynchronous data collection script. Each invocation collects one dated snapshot of a city, catalogs it, and diffs it against the previous run.
* **`run_cities.py`**: A batch-processing wrapper that runs `gsv_tracker.py` across multiple cities sequentially by reading configurations from a text file (e.g., `cities.txt`).
* **`python -m gsv_metadata_tracker.scheduler`**: The staggered quarterly scheduler (`status`, `assign`, `run-due` subcommands). See `deploy/README.md` for running it as a systemd timer.

### Data Utilities & Analysis

* **`gsv_compare_data.py`**: Compares two GSV metadata files for the same city and reports panos added/removed, capture-date changes, and coverage transitions.
* **`generate_json.py`**: Generates missing JSON metadata summary files for existing GSV data directories.
* **`check_status_codes.py`**: Analyzes API status-code distributions across data files.
* **`scripts/migrate_to_db.py`**: One-time migration that registers pre-temporal-tracking data files as baseline runs in the catalog (dry-run by default).

## 3. Usage Examples

### Basic Usage

To analyze a city's Street View coverage using default settings (1000m x 1000m grid, 20m steps):

```bash
python gsv_tracker.py "Seattle, WA"
```

### Preview Search Area

Before executing a large download, you can generate an HTML map to preview your search boundary:

```bash
python gsv_tracker.py "Seattle, WA" --check-boundary
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

Each run generates the following files in your designated `--download-dir` (defaults to `./data`), where `{base}` is `{city_id}_width_{W}_height_{H}_step_{S}_{YYYY-MM-DD}`:

* **`{base}.csv.gz`**: The core compressed data file containing all downloaded GSV metadata for this run.
* **`{base}.json.gz`**: A JSON summary (schema v2) with coverage/age statistics, temporal histograms, and the change-vs-previous-run block.
* **`{base}_failed_points.csv`**: A log of coordinates that failed to download after all retry attempts.
* **`{city_id}_diff_{FROM}_to_{TO}.csv.gz`**: Per-pano change detail between two runs (written when changes exist).
* **`cities.json.gz`**: The aggregate consumed by the web frontend — one entry per city with its latest stats, run history, and change summary.
* **`gsv_tracker.db`**: The SQLite catalog (cities, runs, diffs, schedule state). Local only; never published.
* **`vis/{base}.html`**: An interactive map visualization of the run (unless `--no-visual` is passed).

## Other Helpful Tools

Other helpful GSV tools, include:

Starting in 2022, [sv-map](https://sv-map.netlify.app/) archives blue Street View lines from Google Maps daily, so users can compare the evolution of Street View over time. sv-map downloads Street View coverage lines as **images**, up to a certain zoom level. To display historical coverage differences on the website, it highlights the difference in pixels between the images of different dates. 
<img width="1506" height="856" alt="image" src="https://github.com/user-attachments/assets/1fd0b35d-ae57-4a29-90d8-b81be23246fd" />

[Virtual Streets](https://virtualstreets.org/) provides a blog that describes new coverage to Google Street View

## License

Distributed under the MIT License. See `LICENSE` for more information.
