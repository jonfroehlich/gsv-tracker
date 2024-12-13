import argparse
import sys
import logging
import os
from typing import Optional
from . import (
    load_config, 
    download_gsv_metadata,  
    get_city_coordinates, 
    get_city_bounding_box,
    create_visualization_map
)
from .geoutils import get_search_dimensions

def parse_args():
    parser = argparse.ArgumentParser(
        description='GSV Metadata Tracker',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        'city', 
        help='City name to analyze'
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
        help='Step size in meters'
    )
    
    parser.add_argument(
        '--visualize',
        action='store_false',  # This makes --visualize flag turn visualization OFF
        default=True,
        help='Generate visualizations (default: True)'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        default='WARNING',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set the logging level (default: WARNING)'
    )
    
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Configure logging with command line argument
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    try:
        config = load_config()
        location = get_city_coordinates(args.city)
        
        if not location:
            logging.error(f"Could not find coordinates for {args.city}")
            sys.exit(1)
        
        width, height = get_search_dimensions(
            args.city,
            args.width,
            args.height,
            args.force_size
        )
            
        logging.info(f"Analyzing {args.city} at {location.latitude}, {location.longitude}")
        
        df = download_gsv_metadata(
            args.city,
            location.latitude,
            location.longitude,
            width,
            height,
            args.step,
            config['api_key'],
            config['download_path']
        )
        
        # if args.visualize:
        #     # Get base file path from the CSV path
        #     csv_path, _, _ = get_data_file_paths(
        #         args.city,
        #         width,
        #         height,
        #         args.step,
        #         config['download_path']
        #     )
            
        #     # Generate file paths for visualizations
        #     base_name = os.path.splitext(csv_path)[0]
        #     map_path = f"{base_name}.html"
        #     graph_path = f"{base_name}.png"
            
        #     # Create and save visualizations
        #     map_obj = create_visualization_map(df, args.city)
        #     map_obj.save(map_path)
        #     logging.info(f"Map visualization saved to {map_path}")
            
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()