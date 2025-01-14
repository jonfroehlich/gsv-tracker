"""
Command-line interface for the GSV Metadata Tracker tool.

This script implements concurrent API requests using two key parameters:

1. batch_size: How many API requests we prepare and queue up at once
   - Example: batch_size=200 means we prepare 200 requests in one batch
   - These get processed based on available connections
   - Larger batch sizes mean more memory usage but better throughput

2. connection_limit: Maximum number of concurrent connections to the API
   - Example: connection_limit=100 means only 100 requests can be in-flight at once
   - Additional requests from the batch wait until a connection becomes available
   - This helps prevent overwhelming the network or API
   
Think of batch_size like loading a magazine and connection_limit like the number
of actual workers sending the requests. You might load 200 requests (batch_size)
but only have 100 workers (connection_limit) sending them at a time.
"""

import argparse
import sys
import logging
import os
import asyncio
import aiohttp
from typing import Optional
from .fileutils import get_default_vis_dir
from .json_summarizer import generate_city_metadata_summary_as_json, generate_aggregate_summary_as_json
from .paths import get_default_data_dir, get_default_vis_dir
from .analysis import print_df_summary

from . import (
    load_config,
    get_city_location_data,
    get_search_dimensions,
    create_visualization_map,
    display_search_area,
    download_gsv_metadata_async,
    generate_base_filename,
    open_in_browser
)

def parse_args():
    """
    Parse and validate command line arguments.
    
    The concurrent processing is controlled by two key parameters:
    
    1. batch_size: Number of requests to prepare and queue at once
       - Larger batches use more memory but can be more efficient
       - Should be >= connection_limit
       - Default: 200 requests per batch
    
    2. connection_limit: Maximum number of concurrent connections
       - Limits actual simultaneous requests to the API
       - Helps prevent overwhelming network/API
       - Default: 100 concurrent connections
       
    For the Google Street View Static API (30,000 requests/minute limit):
    - Conservative: batch_size=100, connection_limit=50
    - Moderate: batch_size=200, connection_limit=100
    - Aggressive: batch_size=400, connection_limit=200
    
    Returns:
        argparse.Namespace: Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description='GSV Metadata Tracker',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        'city', 
        help='City name to analyze'
    )

    # Optional arguments for download directory
    parser.add_argument(
        '--download-dir',
        type=str,
        help='Dir to save downloaded data (defaults to ./data)',
        default=get_default_data_dir()
    )
    
    parser.add_argument(
        '--width', 
        type=float, 
        default=1000,
        help='Search grid width in meters (default used if city boundary inference fails)'
    )
    
    parser.add_argument(
        '--height', 
        type=float, 
        default=1000,
        help='Search grid height in meters (default used if city boundary inference fails)'
    )
    
    parser.add_argument(
        '--force-size', 
        action='store_true',
        help='Force using provided width and height instead of inferred city boundaries'
    )
    
    parser.add_argument(
        '--step', 
        type=float, 
        default=20,
        help='Step size in meters between sample points in the grid'
    )
    
    # Parameters controlling concurrent processing
    concurrency_group = parser.add_argument_group('Concurrency Control')
    concurrency_group.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='''Number of requests to prepare and queue at once. 
             Should be >= connection-limit. Higher values use more memory 
             but can be more efficient. API limit is 500/second.'''
    )
    
    concurrency_group.add_argument(
        '--connection-limit',
        type=int,
        default=50,
        help='''Maximum number of concurrent connections to the API.
             Controls how many requests are actually in-flight at once.
             Should be <= batch-size. Conservative values prevent overwhelming
             the network or API.'''
    )
    
    parser.add_argument(
        '--timeout',
        type=float,
        default=30.0,
        help='Timeout in seconds for each individual API request'
    )

    # Add new boundary check argument
    parser.add_argument(
        '--check-boundary',
        action='store_true',
        help='Generate visualization of search area without downloading data. '
             'Useful for verifying the area before starting a download.'
    )
    
    parser.add_argument(
        '--no-visual',
        action='store_true',
        help='Skip generating visualizations of the results'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        default='WARNING',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set the logging level for output messages'
    )
    
    args = parser.parse_args()
    
    # Validate concurrent processing parameters
    if args.connection_limit > args.batch_size:
        parser.error("connection-limit cannot be larger than batch-size")
    
    return args

async def async_main():
    """
    Main async function that coordinates the GSV metadata download process.
    
    Concurrent processing is controlled by:
    - args.batch_size: How many requests to prepare at once
    - args.connection_limit: Maximum simultaneous connections
    
    Example flow:
    1. If batch_size=200 and connection_limit=100:
       - 200 requests are prepared in memory
       - Only 100 can be actively downloading at once
       - As connections complete, new ones start until batch is done
    2. Then the next batch of 200 is prepared
    """
    args = parse_args()
    
    # Configure logging - this is sync but only happens once at startup
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create the data directory if it doesn't exist
    os.makedirs(args.download_dir, exist_ok=True)
    logging.info(f"Using download directory: {args.download_dir}")
    
    try:
        config = load_config()
        city_loc_data = get_city_location_data(args.city)

        vis_path = get_default_vis_dir()
        os.makedirs(vis_path, exist_ok=True)
        
        if not city_loc_data:
            logging.error(f"Could not find coordinates for {args.city}")
            sys.exit(1)

        search_grid_width, search_grid_height = get_search_dimensions(
            args.city,
            args.width,
            args.height,
            args.force_size
        )

        print(f"The search dimensions for {args.city} are {search_grid_width:.1f}m x {search_grid_height:.1f}m")

        # If checking boundaries, create and save visualization then exit
        if args.check_boundary:
            base_name = generate_base_filename(args.city, search_grid_width, search_grid_height, args.step)
            boundary_vis_full_path = os.path.join(vis_path, f"{base_name}_search_boundary.html")
            
            # Create preview map using your display_search_area function
            search_area_map = display_search_area(
                args.city,
                city_loc_data.latitude,
                city_loc_data.longitude,
                search_grid_width,
                search_grid_height,
                args.step
            )
            search_area_map.save(boundary_vis_full_path)
            
            print(f"\nSearch area preview saved to: {boundary_vis_full_path}")
            print("Review the visualization and adjust parameters if needed.")
            print("\nTo download data with these parameters, run the same command without --check-boundary")
            
            # Auto-open the visualization
            success, error_msg = open_in_browser(boundary_vis_full_path)
            if not success:
                logging.warning(f"Could not automatically open visualization: {error_msg}")
                print(f"Please open {boundary_vis_full_path} in your web browser to view the visualization.")
            
            return 0
            
        logging.info(f"Analyzing {args.city} at {city_loc_data.latitude}, {city_loc_data.longitude}")
        logging.info(f"Using batch_size={args.batch_size}, connection_limit={args.connection_limit}")
        
        # Pass both concurrency parameters to the download function
        dict_results = await download_gsv_metadata_async(
            city_name=args.city,
            center_lat=city_loc_data.latitude,
            center_lon=city_loc_data.longitude,
            grid_width=search_grid_width,
            grid_height=search_grid_height,
            step_length=args.step,
            api_key=config['api_key'],
            download_path=args.download_dir,
            batch_size=args.batch_size,
            connection_limit=args.connection_limit,
            request_timeout=args.timeout
        )
        df = dict_results["df"]

        # Print the download summary
        print("\nDownload Summary for", args.city)
        print("=" * 50)
        print_df_summary(df)

        # Create .json summary file
        logging.debug(f"The DataFrame has {len(df)} rows with types {df.dtypes}")
        csv_filename_with_path = dict_results["filename_with_path"]
        generate_city_metadata_summary_as_json(csv_filename_with_path, df,
                                               city_loc_data.city,
                                               city_loc_data.state,
                                               city_loc_data.country,
                                               search_grid_width, search_grid_height, 
                                               args.step)
        
        generate_aggregate_summary_as_json(args.download_dir)

        if not args.no_visual:
            base_name = generate_base_filename(args.city, search_grid_width, search_grid_height, args.step)
            map_path = os.path.join(vis_path, f"{base_name}.html")
            
            map_obj = create_visualization_map(df, args.city)

            print(f"Saving map visualization to {map_path}")
            map_obj.save(map_path)
            logging.info(f"Map visualization saved to {map_path}")
            
    except Exception as e:
        logging.exception(f"Error: {str(e)}")
        sys.exit(1)

def main():
    """
    Entry point for the command line interface.
    
    Sets up the async environment and manages the lifecycle of:
    - Async event loop
    - Connection pools
    - Batch processing
    """
    
    # Windows and Unix-like systems handle async I/O differently at the OS level
    # Windows has two event loop implementations:
    # 1. ProactorEventLoop (default): Good for subprocess/pipes but can have issues with some async operations
    # 2. SelectorEventLoop: More compatible with networking operations like what we're doing
    # So, on Windows, we explicitly set the event loop to use SelectorEventLoop
    if sys.platform.startswith('win'):
        # Override default Windows event loop policy to ensure compatibility
        # with aiohttp's async networking operations
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logging.exception(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()