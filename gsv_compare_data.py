#!/usr/bin/env python3
"""
GSV Metadata Comparison Tool.

This script compares two Google Street View (GSV) metadata files to verify data consistency
between different collection methods (e.g., single-threaded vs async downloads).

Key features:
- Handles gzipped CSV files
- Compares coordinate data with appropriate floating-point tolerance
- Accounts for different row orders by sorting
- Provides both summary and detailed comparison options
- Handles NULL values appropriately across all columns

Usage:
    python gsv_compare_data.py file1.gz file2.gz [--verbose]

Arguments:
    file1.gz        First GSV metadata file (gzipped CSV)
    file2.gz        Second GSV metadata file (gzipped CSV)
    --verbose, -v   Show detailed differences including status counts

Exit codes:
    0: Files contain equivalent data
    1: Files contain differences
    2: Error occurred during comparison

Example:
    python gsv_compare_data.py async_seattle.gz simple_seattle.gz --verbose
"""

import pandas as pd
import gzip
import logging
from pathlib import Path
import argparse
from typing import Tuple, List

def load_gsv_data(file_path: str) -> pd.DataFrame:
    """Load GSV data from a gzipped CSV file."""
    with gzip.open(file_path, 'rt') as f:
        df = pd.read_csv(f, parse_dates=['capture_date'])
    return df

def compare_dataframes(df1: pd.DataFrame, df2: pd.DataFrame) -> Tuple[bool, List[str]]:
    """
    Compare two GSV metadata DataFrames for equality.
    
    Returns:
        Tuple of (is_equal, list of differences)
    """
    differences = []
    
    # Check number of rows
    if len(df1) != len(df2):
        differences.append(f"Row count mismatch: {len(df1)} vs {len(df2)}")
        return False, differences
    
    # Sort both DataFrames by query coordinates to ensure comparable order
    df1 = df1.sort_values(['query_lat', 'query_lon']).reset_index(drop=True)
    df2 = df2.sort_values(['query_lat', 'query_lon']).reset_index(drop=True)
    
    # Compare each column
    columns_to_compare = [
        'query_lat', 'query_lon', 'pano_lat', 'pano_lon',
        'pano_id', 'status'
    ]
    
    for col in columns_to_compare:
        if col in ['query_lat', 'query_lon', 'pano_lat', 'pano_lon']:
            # Compare floating point values with tolerance
            if not (df1[col].fillna(-999).round(6) == df2[col].fillna(-999).round(6)).all():
                differences.append(f"Differences found in {col}")
        else:
            # Compare other columns exactly
            if not (df1[col].fillna('') == df2[col].fillna('')).all():
                differences.append(f"Differences found in {col}")
    
    return len(differences) == 0, differences

def main():
    parser = argparse.ArgumentParser(description='Compare two GSV metadata files')
    parser.add_argument('file1', help='Path to first GSV metadata file (.gz)')
    parser.add_argument('file2', help='Path to second GSV metadata file (.gz)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed differences')
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    try:
        # Load both files
        logging.info(f"Loading {args.file1}...")
        df1 = load_gsv_data(args.file1)
        logging.info(f"Loading {args.file2}...")
        df2 = load_gsv_data(args.file2)
        
        # Compare the DataFrames
        is_equal, differences = compare_dataframes(df1, df2)
        
        if is_equal:
            print("✅ Files contain equivalent data")
            return 0
        else:
            print("❌ Files contain differences:")
            for diff in differences:
                print(f"  - {diff}")
            if args.verbose:
                print("\nDetailed comparison:")
                print(f"File 1 ({args.file1}):")
                print(f"  - Total rows: {len(df1)}")
                print(f"  - Status counts:\n{df1['status'].value_counts()}")
                print(f"\nFile 2 ({args.file2}):")
                print(f"  - Total rows: {len(df2)}")
                print(f"  - Status counts:\n{df2['status'].value_counts()}")
            return 1
            
    except Exception as e:
        logging.error(f"Error comparing files: {str(e)}")
        return 2

if __name__ == '__main__':
    sys.exit(main())