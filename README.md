# GSV Metadata Tracker

GSV Metadata Tracker is a Python tool for analyzing Google Street View coverage and temporal patterns in cities. It creates interactive visualizations showing when and where Street View imagery was captured.

## Features

- Automatic city boundary detection
- Interactive map visualization with temporal filtering
- Statistical analysis of Street View coverage
- Resumable data collection
- Automatic data compression
- Progress tracking with status updates

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/gsv-metadata-tracker.git
cd gsv-metadata-tracker
```

2. Create and activate the conda environment:
```bash
conda env create -f environment.yml
conda activate gsv-metadata-tracker
```

3. Set your Google Street View API key:
```bash
conda env config vars set gmaps_api_key=YOUR_API_KEY
```

4. Reactivate your conda environment
```bash
conda activate gsv-metadata-tracker
```

5. Install the package in development mode:
```bash
pip install -e .
```

## Usage

### Basic Usage

Analyze a city's Street View coverage:
```bash
gsv-tracker "City Name"
```

### Command Line Options

- `city`: Name of the city to analyze (required)
- `--width`: Search grid width in meters (default: 1000)
- `--height`: Search grid height in meters (default: 1000)
- `--step`: Distance between sample points in meters (default: 20)
- `--force-size`: Force using provided dimensions instead of inferring from city boundaries
- `--output`: Output file path for visualizations
- `--skip-map`: Skip generating the interactive map
- `--skip-stats`: Skip generating the statistical visualization

## License

Distributed under the MIT License. See `LICENSE` for more information.

## Acknowledgments

- Google Street View Static API
- OpenStreetMap and CARTO for map tiles
- [Folium](https://python-visualization.github.io/folium/) for map visualization
- [Chart.js](https://www.chartjs.org/) for interactive charts
- Some of this code was written with the assistance of Anthropic Claude and VSCode Copilot