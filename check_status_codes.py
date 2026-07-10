import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from tabulate import tabulate

from gsv_metadata_tracker.analysis import analyze_gsv_status


def format_status_table(df: pd.DataFrame) -> str:
    """Format status code counts and percentages as a table."""
    stats = analyze_gsv_status(df)
    rows = [
        [status, f"{count:,}", f"{stats['status_percentages'][status]:.1f}%"]
        for status, count in sorted(
            stats["status_counts"].items(), key=lambda x: x[1], reverse=True
        )
    ]
    return tabulate(
        rows, headers=["Status", "Count", "Percent"], tablefmt="simple", numalign="right"
    )


def format_record_counts_table(valid_records: int, malformed_count: int) -> str:
    """Format valid/malformed record counts as a table."""
    rows = [
        ["Valid records", f"{valid_records:,}"],
        ["Malformed lines", f"{malformed_count:,}"],
    ]
    return tabulate(rows, headers=["Metric", "Count"], tablefmt="simple", numalign="right")


def format_query_limit_table(files_with_limits: list[tuple[str, int]]) -> str:
    """Format files containing OVER_QUERY_LIMIT statuses as a table."""
    rows = [[path, f"{count:,}"] for path, count in files_with_limits]
    return tabulate(
        rows, headers=["File", "OVER_QUERY_LIMIT count"], tablefmt="simple", numalign="right"
    )


def read_csv_file(filepath: str) -> tuple[pd.DataFrame | None, list[str]]:
    """
    Read a GSV metadata file (CSV/gzipped CSV) and handle malformed lines.

    Args:
        filepath: Path to the file to read

    Returns:
        Tuple of (DataFrame or None if error, list of malformed lines)
    """
    malformed_lines = []

    try:
        # Custom handler for bad lines
        def bad_line_handler(bad_line):
            malformed_lines.append(bad_line)
            return None

        # Read the file with appropriate compression based on extension
        compression = "gzip" if filepath.lower().endswith(".gz") else None
        df = pd.read_csv(
            filepath, compression=compression, on_bad_lines=bad_line_handler, engine="python"
        )

        return df, malformed_lines

    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return None, malformed_lines


def should_process_file(filepath: str) -> bool:
    """Check if the file should be processed based on its extension."""
    if filepath.endswith(".json.gz"):
        return False

    extensions = {".gz", ".csv", ".downloading"}
    return Path(filepath).suffix.lower() in extensions


def find_files_to_process(directory: str) -> list[str]:
    """Find all GSV metadata files in directory and subdirectories."""
    files_to_process = []

    for root, _, files in os.walk(directory):
        for file in files:
            filepath = os.path.join(root, file)
            if should_process_file(filepath):
                files_to_process.append(filepath)

    return sorted(files_to_process)


def print_malformed_lines(malformed_lines: list[str]) -> None:
    """Print malformed lines in a readable format."""
    if not malformed_lines:
        return

    print("\nMalformed Lines:")
    print("-" * 50)
    for i, line in enumerate(malformed_lines, 1):
        print(f"Line {i}: {line.strip()}")


def main():
    parser = argparse.ArgumentParser(description="Analyze status codes in GSV metadata files.")
    parser.add_argument("paths", nargs="+", help="Paths to files and/or directories to analyze")
    parser.add_argument(
        "--hide-malformed", action="store_true", help="Hide content of malformed lines"
    )

    args = parser.parse_args()

    # Find all files to process
    files_to_process = []
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
            if should_process_file(path):
                files_to_process.append(path)
            else:
                print(f"Skipping file with unsupported extension: {path}")

    if not files_to_process:
        print("No files to process!")
        sys.exit(1)

    # Remove duplicates and sort
    files_to_process = sorted(set(files_to_process))

    # Track overall statistics
    overall_data = []
    files_with_query_limit = []
    total_malformed = 0
    total_files = len(files_to_process)

    # Process each file
    for i, file_path in enumerate(files_to_process, 1):
        print(f"\nAnalyzing file {i} of {total_files}: {file_path}")
        print("=" * 50)

        df, malformed_lines = read_csv_file(file_path)

        if df is not None:
            # Analyze and print status distribution
            print("\nStatus Code Distribution Across Queries:")
            print(format_status_table(df))

            # Print record counts
            print("\nRecord Counts:")
            print(
                format_record_counts_table(
                    valid_records=len(df), malformed_count=len(malformed_lines)
                )
            )

            # Track statistics for overall summary
            overall_data.append(df)
            total_malformed += len(malformed_lines)

            # Track files with OVER_QUERY_LIMIT
            limit_count = len(df[df["status"] == "OVER_QUERY_LIMIT"])
            if limit_count > 0:
                files_with_query_limit.append((file_path, limit_count))

            # Show malformed lines if requested
            if not args.hide_malformed:
                print_malformed_lines(malformed_lines)

    # Print overall summary if we processed multiple files
    if len(files_to_process) > 1 and overall_data:
        print("\nOVERALL SUMMARY")
        print("=" * 50)

        # Combine all DataFrames
        combined_df = pd.concat(overall_data, ignore_index=True)

        print(f"\nProcessed Files: {total_files}")

        # Print overall record counts
        print("\nTotal Record Counts:")
        print(
            format_record_counts_table(
                valid_records=len(combined_df), malformed_count=total_malformed
            )
        )

        # Print overall status distribution
        print("\nOverall Status Code Distribution:")
        print(format_status_table(combined_df))

        # Print files with query limits
        if files_with_query_limit:
            print("\nFiles with OVER_QUERY_LIMIT status:")
            print(format_query_limit_table(files_with_query_limit))


if __name__ == "__main__":
    main()
