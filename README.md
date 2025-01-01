# GSV Tracker

GSV Tracker is a Python tool for analyzing Google Street View coverage and temporal patterns in cities. It creates interactive visualizations showing when and where Street View imagery was captured, using asynchronous operations for efficient data collection.

This research project began in 2021 by Professor Jon E. Froehlich and was also part of the [UC Berkeley Data Science Discovery Program](https://cdss.berkeley.edu/discovery/projects) in 2023 with students Joseph Chen, Wenjing Yi, and Jingfeng Yang.

## Installation

We use Mamba rather than Conda for environment management because Mamba is significantly faster at resolving dependencies and installing packages. 

1. Clone the repository:
```bash
git clone https://github.com/yourusername/gsv-tracker.git
cd gsv-tracker
```

2. Install mamba (if you haven't already):
```bash
conda install mamba -n base -c conda-forge
```

3. Create and activate the environment using mamba:
```bash
mamba env create -f environment.yml
conda activate gsv-tracker
```

If you need to update your environment later, use:
```bash
mamba env update -f environment.yml
```

### Why Mamba?

This project recommends using Mamba instead of Conda for environment management. While both tools serve the same purpose, Mamba offers the following advantages:

- **Speed**: Mamba's C++ implementation is substantially faster than Conda's Python implementation, often resolving dependencies 5-10x faster ([source](https://github.com/mamba-org/mamba#the-fast-cross-platform-package-manager)).
- **Memory Efficiency**: Mamba uses less memory when solving environments ([benchmark results](https://prefix.dev/blog/conda_vs_mamba)).
- **Better Solver**: Mamba's dependency solver is more robust and less likely to get stuck in dependency conflicts ([documentation](https://mamba.readthedocs.io/en/latest/installation.html#why-mamba)).
- **Drop-in Replacement**: Mamba is fully compatible with Conda environments and packages, making it a seamless alternative ([Anaconda blog](https://www.anaconda.com/blog/a-faster-conda-for-a-growing-community)).

For more details on Mamba's advantages, see the [official Mamba documentation](https://mamba.readthedocs.io/en/latest/index.html) and this [performance comparison](https://prefix.dev/blog/conda_vs_mamba).

While we use mamba for creating and updating the environment, we still use conda commands for environment activation and setting environment variables.

## Usage

### Basic Usage

Analyze a city's Street View coverage:
```bash
gsv-tracker "City Name"
```

### Preview Search Area

Before downloading data, you can preview the search area:
```bash
gsv-tracker "City Name" --check-boundary
```
This will generate and open a visualization of the intended search area without downloading any data.

### Command Line Options

Basic Options:
- `city`: Name of the city to analyze (required)
- `--width`: Search grid width in meters (default: 1000)
- `--height`: Search grid height in meters (default: 1000)
- `--step`: Distance between sample points in meters (default: 20)
- `--force-size`: Force using provided dimensions instead of inferring from city boundaries
- `--check-boundary`: Preview search area without downloading data
- `--no-visual`: Skip generating visualizations
- `--log-level`: Set logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL)

Concurrency Control:
- `--batch-size`: Number of requests to prepare and queue at once (default: 200)
  - Should be >= connection-limit
  - Higher values use more memory but can be more efficient
  - Google Street View Static API limit is 500 requests/second
- `--connection-limit`: Maximum concurrent connections to the API (default: 100)
  - Controls how many requests are actually in-flight at once
  - Should be <= batch-size
  - Conservative values prevent overwhelming the network/API
- `--timeout`: Request timeout in seconds (default: 30)

Recommended Concurrency Settings:
- Conservative: `--batch-size 100 --connection-limit 50`
- Moderate: `--batch-size 200 --connection-limit 100`
- Aggressive: `--batch-size 400 --connection-limit 200`

### Output Files

The tool generates several files:
- `{city_name}_{width}x{height}_step{step}.csv.gz`: Compressed data file containing all GSV metadata
- `{city_name}_{width}x{height}_step{step}_failed_points.csv`: List of points that failed to download after all retries
- `{city_name}_{width}x{height}_step{step}.html`: Interactive map visualization (if not skipped)
- `{city_name}_{width}x{height}_step{step}_search_boundary.html`: Search area preview (when using --check-boundary)

### Error Handling

- Failed requests are automatically retried with exponential backoff
- Points that fail after all retries are logged to a separate file for later analysis
- Intermediate results are saved regularly, allowing for safe interruption and resumption
- File operations use locking to prevent data corruption in case of concurrent access
- Cross-platform compatibility ensured for Windows and Unix-like systems

## License

Distributed under the MIT License. See `LICENSE` for more information.

## Acknowledgments

- Google Street View Static API
- OpenStreetMap and CARTO for map tiles
- [Folium](https://python-visualization.github.io/folium/) for map visualization
- [Chart.js](https://www.chartjs.org/) for interactive charts
- [aiohttp](https://docs.aiohttp.org/) for asynchronous HTTP requests
- [backoff](https://github.com/litl/backoff) for retry functionality
- Some of this code was written with the assistance of Anthropic Claude and VSCode Copilot
