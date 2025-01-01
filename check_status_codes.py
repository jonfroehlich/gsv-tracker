import pandas as pd
import gzip
from collections import Counter
import argparse
import sys
import os
from pathlib import Path

def is_gzipped(filepath):
    """
    Check if a file is gzipped based on its extension.
    """
    return filepath.lower().endswith('.gz')

def should_process_file(filepath):
    """
    Check if the file should be processed based on its extension.
    """
    # Exclude .json.gz files
    if filepath.endswith('.json.gz'):
        return False
    
    extensions = {'.gz', '.csv', '.downloading'}
    return Path(filepath).suffix.lower() in extensions

def find_files_to_process(directory):
    """
    Find all files in directory (and subdirectories) that should be processed.
    
    Args:
        directory (str): Path to the directory to scan
    
    Returns:
        list: List of file paths to process
    """
    files_to_process = []
    
    # Walk through directory and all subdirectories
    for root, _, files in os.walk(directory):
        for file in files:
            filepath = os.path.join(root, file)
            if should_process_file(filepath):
                files_to_process.append(filepath)
    
    return sorted(files_to_process)

def analyze_status_codes(filepath):
    """
    Analyze status codes in a CSV file (gzipped or not).
    """
    malformed_lines = []
    
    try:
        # Custom handler for bad lines
        def bad_line_handler(bad_line):
            malformed_lines.append(bad_line)
            return None

        # Read the file with appropriate compression based on extension
        compression = 'gzip' if is_gzipped(filepath) else None
        df = pd.read_csv(filepath, compression=compression, on_bad_lines=bad_line_handler, engine='python')
        
        # Get the status code column name (assuming it exists)
        status_cols = [col for col in df.columns if 'status' in col.lower()]
        
        if not status_cols:
            raise ValueError("No status code column found in the CSV file")
            
        status_col = status_cols[0]
        
        # Get unique status codes and their counts
        status_counts = Counter(df[status_col])
        total_records = len(df)
        
        # Calculate percentages
        status_stats = {
            'unique_codes': sorted(status_counts.keys()),
            'counts': dict(status_counts),
            'percentages': {code: (count/total_records * 100) 
                          for code, count in status_counts.items()},
            'total_records': total_records,
            'malformed_count': len(malformed_lines)
        }
        
        return status_stats, malformed_lines
        
    except Exception as e:
        print(f"Error analyzing file: {str(e)}")
        return None, malformed_lines

def print_status_analysis(stats, malformed_lines, show_malformed=True):
    """
    Print the status code analysis in a readable format.
    """
    if not stats:
        return
        
    print("\nStatus Code Analysis:")
    print("-" * 50)
    print(f"Total Records Processed: {stats['total_records']:,}")
    print(f"Malformed Lines: {stats['malformed_count']:,}")
    print(f"Total Lines: {stats['total_records'] + stats['malformed_count']:,}")
    
    # Calculate the maximum width needed for the code column
    max_code_width = max(len(str(code)) for code in stats['unique_codes'])
    max_code_width = max(max_code_width, len("Code"))  # Account for header
    
    # Calculate max width for count column
    max_count_width = max(len(f"{stats['counts'][code]:,}") for code in stats['unique_codes'])
    max_count_width = max(max_count_width, len("Count"))
    
    # Format the headers and separator with dynamic widths
    print("\nStatus Code Distribution:")
    print("-" * (max_code_width + max_count_width + 20))
    print(f"{'Code':<{max_code_width}}  {'Count':<{max_count_width}}  {'Percentage'}")
    print("-" * (max_code_width + max_count_width + 20))
    
    # Print each row with proper alignment
    for code in sorted(stats['unique_codes']):
        count = stats['counts'][code]
        percentage = stats['percentages'][code]
        print(f"{str(code):<{max_code_width}}  {count:>{max_count_width},}  {percentage:>8.2f}%")
    
    if show_malformed and malformed_lines:
        print("\nMalformed Lines:")
        print("-" * 50)
        for i, line in enumerate(malformed_lines, 1):
            print(f"Line {i}: {line.strip()}")

def main():
    parser = argparse.ArgumentParser(
        description='Analyze status codes in CSV files (gzipped or not) from files and/or directories.')
    parser.add_argument('paths', nargs='+', 
                       help='Paths to files and/or directories to analyze')
    parser.add_argument('--hide-malformed', action='store_true', 
                       help='Hide content of malformed lines')
    
    args = parser.parse_args()
    
    files_to_process = []
    
    # Process each provided path
    for path in args.paths:
        if not os.path.exists(path):
            print(f"Error: Path not found: {path}")
            continue
            
        if os.path.isdir(path):
            dir_files = find_files_to_process(path)
            if not dir_files:
                print(f"No matching files found in directory: {path}")
            files_to_process.extend(dir_files)
        else:
            if should_process_file(path) or path.lower().endswith(('.gz', '.csv', '.downloading')):
                files_to_process.append(path)
            else:
                print(f"Skipping file with unsupported extension: {path}")
                
    if not files_to_process:
        print("No files to process!")
        sys.exit(1)
        
    # Remove duplicates and sort
    files_to_process = sorted(set(files_to_process))
    
    # Process each file
    for file_path in files_to_process:
        print(f"\nAnalyzing file: {file_path}")
        print("=" * 50)
        
        stats, malformed_lines = analyze_status_codes(file_path)
        print_status_analysis(stats, malformed_lines, not args.hide_malformed)

        print(f"\nFinished analysis of: {file_path}")
        print("-" * 50)

if __name__ == "__main__":
    main()