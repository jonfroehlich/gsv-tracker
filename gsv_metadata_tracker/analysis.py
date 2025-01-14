"""
analysis.py - Module for analyzing and displaying GSV metadata statistics.

This module provides functions for analyzing Google Street View metadata and 
displaying formatted statistics tables. It's designed to be used by multiple
components like json_summarizer.py, check_status_codes.py, and cli.py.
"""

from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
from tabulate import tabulate
from datetime import datetime
import numpy as np
import os
from collections import Counter

def format_status_table(df: pd.DataFrame) -> str:
    """
    Create a formatted table of status code statistics.
    
    Args:
        df: DataFrame containing GSV metadata
        
    Returns:
        Formatted string containing the status code table
    """
    status_counts = Counter(df['status'])
    total_records_cnt = len(df)
    
    # Create rows for the table
    rows = []
    for status, count in sorted(status_counts.items()):
        percentage = (count / total_records_cnt) * 100
        formatted_count = f"{count:,}"
        rows.append([status, formatted_count, f"{percentage:.2f}%"])
    
    # Add total row
    total_records_str = f"{total_records_cnt:,}"
    rows.append(["TOTAL", total_records_str, "100.00%"])
    
    return tabulate(
        rows,
        headers=["Status", "Count", "Percentage"],
        tablefmt="simple ",
        floatfmt=".2f",
        numalign="right",
        stralign="left"
    )

def format_duplicate_stats(stats: Dict[str, Any]) -> str:
    """
    Create a formatted table of panorama duplication statistics.
    
    Args:
        stats: Dictionary containing duplicate statistics
        
    Returns:
        Formatted string containing the duplicates table
    """
    rows = [
        ["Total Unique Panoramas", stats['total_unique_panos']],
        ["Total References", stats['total_pano_references']],
        ["Duplicate References", stats['duplicate_reference_count']],
        ["Most Referenced Count", stats['most_referenced_count']],
        ["Panoramas with Multiple Refs", stats['panos_with_multiple_refs']],
        [f"Average References per Pano", f"{stats['average_references_per_pano']:.2f}"]
    ]
    
    return tabulate(
        rows,
        headers=["Metric", "Value"],
        tablefmt="simple",
        numalign="right",
        stralign="left"
    )

def format_age_stats(age_stats: Dict[str, Any], title: str = "Age Statistics") -> str:
    """
    Create a formatted table of panorama age statistics.
    
    Args:
        age_stats: Dictionary containing age statistics
        title: Optional title for the table
        
    Returns:
        Formatted string containing the age statistics table
    """
    percentiles = age_stats.get('age_percentiles_years', {})
    
    def format_value(value) -> str:
        """Helper to safely format values that might be None"""
        if value is None:
            return "N/A"
        if isinstance(value, (float, int)):
            return f"{value:.2f}"
        return str(value)
    
    rows = [
        ["Total Panoramas", age_stats.get('count', 'N/A')],
        ["Oldest Panorama", age_stats.get('oldest_pano_date', 'N/A')],
        ["Newest Panorama", age_stats.get('newest_pano_date', 'N/A')],
        ["Average Age (years)", format_value(age_stats.get('avg_pano_age_years'))],
        ["Median Age (years)", format_value(age_stats.get('median_pano_age_years'))],
        ["Std Dev Age (years)", format_value(age_stats.get('stdev_pano_age_years'))]
    ]
    
    
    return f"\n{title}\n" + tabulate(
        rows,
        headers=["Metric", "Value"],
        tablefmt="simple",
        numalign="right",
        stralign="left"
    )

def format_coverage_stats(coverage_stats: Dict[str, Any]) -> str:
    """
    Create a formatted table of coverage statistics.
    
    Args:
        coverage_stats: Dictionary containing coverage statistics
        
    Returns:
        Formatted string containing the coverage statistics table
    """
    def format_float(value) -> str:
        """Helper to format floats or None values"""
        if value is None:
            return "N/A"
        return f"{value:.2f}"

    distance_stats = coverage_stats.get('pano_distance_stats', {})

    rows = [
        ["Points with Panoramas", coverage_stats['num_points_with_panos']],
        ["Points with Unique Pano IDs", coverage_stats['num_points_with_unique_pano_ids']],
        ["Points without Panoramas", coverage_stats['num_points_without_panos']],
        ["Points with Errors", coverage_stats['num_points_with_errors']],
        ["Unique Pano IDs / Num Points Queried", f"{coverage_stats['coverage_rate']:.2f}%"],
    ]

    # Handle optional distance statistics
    distance_stats = coverage_stats.get('pano_distance_stats') or {}
    
    # Add distance statistics if they exist
    distance_rows = [
        ["Min Distance (m)", format_float(distance_stats.get('min_meters'))],
        ["Max Distance (m)", format_float(distance_stats.get('max_meters'))],
        ["Avg Distance (m)", format_float(distance_stats.get('avg_meters'))],
        ["Median Distance (m)", format_float(distance_stats.get('median_meters'))]
    ]
    
    rows.extend(distance_rows)
    
    return tabulate(
        rows,
        headers=["Metric", "Value"],
        tablefmt="simple",
        numalign="right",
        stralign="left"
    )

def format_yearly_distribution(histogram: Dict[str, int], title: str = "Yearly Distribution") -> str:
    """
    Create a formatted table showing the distribution of panoramas by year.
    
    Args:
        histogram: Dictionary mapping years to panorama counts
        title: Optional title for the table
        
    Returns:
        Formatted string containing the yearly distribution table
    """
    total_panos = sum(histogram.values())
    
    # Create rows with year, count, and percentage
    rows = []
    for year in sorted(histogram.keys()):
        count = histogram[year]
        percentage = (count / total_panos) * 100
        rows.append([year, count, f"{percentage:.2f}%"])
    
    # Add total row
    rows.append(["TOTAL", total_panos, "100.00%"])
    
    return f"\n{title}\n" + tabulate(
        rows,
        headers=["Year", "Count", "Percentage"],
        tablefmt="simple",
        floatfmt=".2f",
        numalign="right",
        stralign="left"
    )

def calculate_pano_stats(
    df: pd.DataFrame, 
    now: pd.Timestamp,
    copyright_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculate comprehensive panorama statistics from a DataFrame.
    
    This function combines calculations previously spread across multiple modules.
    
    Args:
        df: DataFrame containing GSV metadata
        now: Timestamp to use for age calculations
        copyright_filter: Optional string to filter copyright info (e.g., 'Google')
        
    Returns:
        Dictionary containing calculated statistics
    """
    # Apply copyright filter if specified
    filtered_df = df[df['copyright_info'].str.contains(copyright_filter, na=False)] if copyright_filter else df
    
    # Get successful panoramas
    ok_panos = filtered_df[filtered_df['status'] == 'OK'].copy()
    
    # Calculate duplicate statistics
    pano_id_counts = ok_panos['pano_id'].value_counts()
    duplicate_stats = {
        "total_unique_panos": len(pano_id_counts),
        "total_pano_references": len(ok_panos),
        "duplicate_reference_count": len(ok_panos) - len(pano_id_counts),
        "most_referenced_count": int(pano_id_counts.max()) if not pano_id_counts.empty else 0,
        "panos_with_multiple_refs": int((pano_id_counts > 1).sum()),
        "average_references_per_pano": float(len(ok_panos) / len(pano_id_counts)) if len(pano_id_counts) > 0 else 0
    }
    
    # Calculate age statistics for unique panoramas
    unique_panos = ok_panos.drop_duplicates(subset=['pano_id'])
    
    age_stats = calculate_age_stats(unique_panos, now)
    
    # Calculate coverage statistics
    coverage_stats = calculate_coverage_stats(filtered_df)
    
    # Calculate yearly distribution
    yearly_dist = calculate_histogram_of_capture_dates_by_year(unique_panos)
    daily_dist = calculate_histogram_of_capture_dates_by_day(unique_panos)
    
    return {
        "duplicate_stats": duplicate_stats,
        "age_stats": age_stats,
        "coverage_stats": coverage_stats,
        "yearly_distribution": yearly_dist,
        "daily_distribution": daily_dist
    }

def calculate_age_stats(df: pd.DataFrame, now: pd.Timestamp) -> Dict[str, Any]:
    """Helper function to calculate age statistics for panoramas."""
    now = pd.Timestamp.now()
    
    if len(df) == 0:
        return {
            "count": 0,
            "oldest_pano_date": None,
            "newest_pano_date": None,
            "avg_pano_age_years": None,
            "median_pano_age_years": None,
            "stdev_pano_age_years": None,
            "age_percentiles_years": None
        }
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    valid_dates_mask = df['capture_date'].notna()
    df_with_dates = df[valid_dates_mask]
    
    ages = (now - df_with_dates['capture_date']).dt.total_seconds() / (365.25 * 24 * 3600)
    
    return {
        "count": len(df),
        "oldest_pano_date": df_with_dates['capture_date'].min().isoformat() if len(df_with_dates) > 0 else None,
        "newest_pano_date": df_with_dates['capture_date'].max().isoformat() if len(df_with_dates) > 0 else None,
        "avg_pano_age_years": float(ages.mean()) if len(ages) > 0 else None,
        "median_pano_age_years": float(ages.median()) if len(ages) > 0 else None,
        "stdev_pano_age_years": float(ages.std()) if len(ages) > 0 else None,
        "age_percentiles_years": {
            "p10": float(ages.quantile(0.1)) if len(ages) > 0 else None,
            "p25": float(ages.quantile(0.25)) if len(ages) > 0 else None,
            "p75": float(ages.quantile(0.75)) if len(ages) > 0 else None,
            "p90": float(ages.quantile(0.9)) if len(ages) > 0 else None
        }
    }

def calculate_coverage_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate coverage and distance statistics.
    
    Error types include:
    - ERROR: Generic API error
    - REQUEST_DENIED: API key issues
    - INVALID_REQUEST: Malformed request
    - OVER_QUERY_LIMIT: Rate limiting
    - NO_DATE: Successful pano but missing date
    - UNKNOWN_ERROR: Unclassified errors
    """
    num_total_points = len(df)

    total_points_with_panos = df[df['status'] == 'OK']
    num_points_with_panos = len(total_points_with_panos)
    num_points_without_panos = len(df[df['status'] == 'ZERO_RESULTS'])
    num_points_with_errors = len(df[df['status'].isin([
        'ERROR',
        'REQUEST_DENIED', 
        'INVALID_REQUEST',
        'OVER_QUERY_LIMIT',
        'NO_DATE',
        'UNKNOWN_ERROR'
    ])])

    # Remove duplicates pano id (only count each pano id once)
    successful_df_no_duplicates = total_points_with_panos.drop_duplicates(subset=['pano_id']).copy()
    num_points_with_unique_pano_ids = len(successful_df_no_duplicates)
    num_points_without_unique_pano_ids = num_points_with_panos - len(successful_df_no_duplicates)

    if len(successful_df_no_duplicates) > 0:
        # Calculate distances using loc for assignment
        distances = np.sqrt(
            (successful_df_no_duplicates['query_lat'] - successful_df_no_duplicates['pano_lat'])**2 +
            (successful_df_no_duplicates['query_lon'] - successful_df_no_duplicates['pano_lon'])**2
        ) * 111000  # Approximate conversion to meters
        
        successful_df_no_duplicates.loc[:, 'distance_to_query'] = distances
        
        distance_stats = {
            "min_meters": float(successful_df_no_duplicates['distance_to_query'].min()),
            "max_meters": float(successful_df_no_duplicates['distance_to_query'].max()),
            "avg_meters": float(successful_df_no_duplicates['distance_to_query'].mean()),
            "median_meters": float(successful_df_no_duplicates['distance_to_query'].median()),
            "stdev_meters": float(successful_df_no_duplicates['distance_to_query'].std())
        }
    else:
        distance_stats = None
    
    return {
        "num_points_with_panos": num_points_with_panos,
        "num_points_with_unique_pano_ids": num_points_with_unique_pano_ids,
        "num_points_without_panos": num_points_without_panos + num_points_without_unique_pano_ids,
        "num_points_with_errors": num_points_with_errors,

        # Coverage rate is defined as the number of unique pano ids found over the total number of points searched
        "coverage_rate": (num_points_with_unique_pano_ids / num_total_points) * 100 if num_total_points > 0 else 0,
        "pano_distance_stats": distance_stats
    }

def calculate_and_format_photographer_stats(df: pd.DataFrame) -> str:
    """
    Create a formatted table showing the top 5 photographers by number of unique panoramas.
    
    Args:
        df: DataFrame containing GSV metadata with 'copyright_info' and 'pano_id' columns
        
    Returns:
        Formatted string containing the photographer contribution table
        
    Example:
        >>> photographer_stats = format_photographer_stats(gsv_metadata_df)
        >>> print(photographer_stats)
        Top 5 Photographers by Unique Panoramas
        Photographer               Unique Panos    Percentage
        ------------------------  -------------  ------------
        Google                          15,234        85.23%
        John Smith                       1,523         8.52%
        Jane Doe                           543         3.04%
        Photo Studios Inc                  324         1.81%
        Street View Pro                    251         1.40%
    """
    # Filter for successful panoramas and drop duplicates
    ok_panos = df[df['status'] == 'OK'].drop_duplicates(subset=['pano_id'])
    
    # Count unique pano_ids per photographer
    photographer_counts = ok_panos['copyright_info'].value_counts()
    total_panos = len(ok_panos)
    
    # Create rows for top 5 photographers
    rows = []
    for photographer, count in photographer_counts.head(5).items():
        percentage = (count / total_panos) * 100
        rows.append([
            photographer,
            f"{count:,}",
            f"{percentage:.2f}%"
        ])
    
    return "\nTop 5 Photographers by Unique Panoramas\n" + tabulate(
        rows,
        headers=["Photographer", "Unique Panos", "Percentage"],
        tablefmt="simple",
        floatfmt=".2f",
        numalign="right",
        stralign="left"
    )

def calculate_histogram_of_capture_dates_by_year(df: pd.DataFrame) -> Dict[str, int]:
    """Calculate distribution of panoramas by year."""
    if len(df) == 0:
        return {}
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    # Extract year and count occurrences
    year_counts = df['capture_date'].dt.year.value_counts().sort_index()
    
    return {int(year): int(count) for year, count in year_counts.items()}

def calculate_histogram_of_capture_dates_by_day(df: pd.DataFrame) -> Dict[str, int]:
    """
    Calculate distribution of panoramas by date (YYYY-MM-DD).
    
    Args:
        df: DataFrame containing panorama data with capture_date column
        
    Returns:
        Dictionary mapping dates (YYYY-MM-DD format) to panorama counts
    """
    if len(df) == 0:
        return {}
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    # Use ISO format for dates (YYYY-MM-DD)
    date_counts = df['capture_date'].apply(lambda x: x.date().isoformat()).value_counts().sort_index()
    
    # Convert counts to integers while maintaining ISO date strings as keys
    return {date: int(count) for date, count in date_counts.items()}

def print_df_summary(df: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> None:
    """
    Print a comprehensive summary of download results.
    
    Args:
        df: DataFrame containing the downloaded GSV metadata
    """
    # Use provided timestamp or current time
    timestamp = now if now is not None else pd.Timestamp.now()
    
    # Calculate all statistics
    all_stats = calculate_pano_stats(df, timestamp)
    google_stats = calculate_pano_stats(df, timestamp, copyright_filter='Google')
    
    # Print coverage statistics
    print("\nCoverage Statistics")
    print("=" * 40)
    print("\nAll Panos")
    print(format_coverage_stats(all_stats['coverage_stats']))

    print("\nGoogle Panos Only")
    print(format_coverage_stats(google_stats['coverage_stats']))

    print("\nPhotographer Statistics")
    print(calculate_and_format_photographer_stats(df))
    
    # Print duplicate statistics
    print("\nDuplicate Statistics")
    print("=" * 40)
    print(format_duplicate_stats(all_stats['duplicate_stats']))
    
    # Print age statistics for all panoramas
    print("\nAge Statistics")
    print("=" * 40)
    print(format_age_stats(all_stats['age_stats'], "Age Statistics (All Panoramas)"))
    
    # Print age statistics for Google panoramas
    print(format_age_stats(google_stats['age_stats'], "\nAge Statistics (Google Panoramas Only)"))
    
    # Print yearly distribution
    print(format_yearly_distribution(all_stats['yearly_distribution'], "\nYearly Distribution (All Panoramas)"))
    print(format_yearly_distribution(google_stats['yearly_distribution'], "\nYearly Distribution (Google Panoramas Only)"))

    # Print status code table
    print("\nStatus Code Distribution")
    print("=" * 40)
    print(format_status_table(df))

    print("\nEnd of Summary")
    print("-" * 40)

def analyze_gsv_status(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze GSV metadata status codes in a DataFrame.
    
    Args:
        df: DataFrame containing GSV metadata
        
    Returns:
        Dictionary containing status analysis including counts and percentages
    """
    # Get the status column
    status_cols = [col for col in df.columns if 'status' in col.lower()]
    if not status_cols:
        raise ValueError("No status column found in DataFrame")
    status_col = status_cols[0]
    
    # Calculate status statistics
    status_counts = Counter(df[status_col])
    total_records = len(df)
    
    return {
        "total_records": total_records,
        "status_counts": dict(status_counts),
        "status_percentages": {
            status: (count/total_records * 100) 
            for status, count in status_counts.items()
        }
    }

def format_record_counts_table(valid_records: int, malformed_count: int) -> str:
    """Format a table showing record counts."""
    total = valid_records + malformed_count
    
    rows = [
        ["Valid Records", f"{valid_records:,}"],
        ["Malformed Lines", f"{malformed_count:,}"],
        ["Total Lines", f"{total:,}"]
    ]
    
    return tabulate(rows, 
                    headers=["Category", "Count"], 
                    tablefmt="simple",
                    numalign="right",
                    stralign="left")

def format_query_limit_table(files_with_limit: List[Tuple[str, int]]) -> str:
    """Format a table showing files with query limits exceeded."""
    if not files_with_limit:
        return ""
        
    # Sort by count in descending order
    sorted_files = sorted(files_with_limit, key=lambda x: x[1], reverse=True)
    
    rows = [(os.path.basename(filepath), f"{count:,}") 
            for filepath, count in sorted_files]
    
    return tabulate(
        rows,
        headers=["Filename", "OVER_QUERY_LIMIT Count"],
        tablefmt="simple",
        numalign="right",
        stralign="left"
    )