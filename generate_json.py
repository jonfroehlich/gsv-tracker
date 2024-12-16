def find_missing_json_files(data_dir: str) -> List[str]:
    """
    Find all csv.gz files that don't have corresponding JSON files.
    
    Args:
        data_dir: Directory to search for files
        
    Returns:
        List of paths to csv.gz files needing JSON metadata
    """
    # Find all csv.gz files
    csv_files = glob.glob(os.path.join(data_dir, "**/*.csv.gz"), recursive=True)
    
    # Filter to those without corresponding JSON
    missing_json = []
    for csv_file in csv_files:
        json_file = csv_file.rsplit('.csv.gz', 1)[0] + '.json'
        if not os.path.exists(json_file):
            missing_json.append(csv_file)
    
    return missing_json

def generate_missing_json_files(data_dir: str) -> None:
    """
    Generate missing JSON metadata files for all csv.gz files in directory.
    
    Args:
        data_dir: Directory containing the GSV metadata files
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Scanning {data_dir} for csv.gz files missing JSON metadata...")
    
    # Find files needing metadata
    missing_files = find_missing_json_files(data_dir)
    
    if not missing_files:
        logger.info("No missing metadata files found.")
        return
    
    logger.info(f"Found {len(missing_files)} files needing metadata.")
    
    # Process each file
    for csv_path in tqdm(missing_files, desc="Generating metadata files"):
        try:
            # Parse filename to get parameters
            city_name, width, height, step = parse_filename(csv_path)
            
            # Read the CSV file
            df = pd.read_csv(
                csv_path,
                dtype=METADATA_DTYPES,
                parse_dates=['capture_date'],
                compression='gzip'
            )
            
            # Calculate center coordinates for country inference
            center_lat = float(df['query_lat'].mean())
            center_lon = float(df['query_lon'].mean())
            
            # Try to infer country
            country_name = infer_country(city_name, center_lat, center_lon)
            
            # Generate metadata file
            save_download_stats(
                csv_gz_path=csv_path,
                df=df,
                city_name=city_name,
                country_name=country_name,
                grid_width=width,
                grid_height=height,
                step_length=step
            )
            
            logger.debug(f"Generated metadata for {csv_path} (Country: {country_name})")
            
        except Exception as e:
            logger.error(f"Error processing {csv_path}: {str(e)}")
            continue
    
    logger.info("Metadata generation complete.")

def main():
    """
    Command-line entry point for metadata generation.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate missing JSON metadata files for GSV data'
    )
    
    parser.add_argument(
        '--data-dir',
        type=str,
        required=True,
        help='Directory containing GSV metadata files'
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.data_dir):
        print(f"Error: Directory {args.data_dir} does not exist")
        return 1
        
    generate_missing_json_files(args.data_dir)

    # TODO: update main .json file that combines all .json files into one
    return 0

if __name__ == '__main__':
    main()