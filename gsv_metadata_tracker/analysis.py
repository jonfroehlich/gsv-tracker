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
    
    rows = [
        ["Total Panoramas", age_stats['count']],
        ["Oldest Panorama", age_stats['oldest_pano_date']],
        ["Newest Panorama", age_stats['newest_pano_date']],
        ["Average Age (years)", f"{age_stats['avg_pano_age_years']:.2f}"],
        ["Median Age (years)", f"{age_stats['median_pano_age_years']:.2f}"],
        ["Std Dev Age (years)", f"{age_stats['stdev_pano_age_years']:.2f}"],
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
    distance_stats = coverage_stats.get('pano_distance_stats', {})
    
    rows = [
        ["Points with Panoramas", coverage_stats['points_with_panos']],
        ["Points without Panoramas", coverage_stats['points_without_panos']],
        ["Points with Errors", coverage_stats['points_with_errors']],
        ["Coverage Rate", f"{coverage_stats['coverage_rate']:.2f}%"],
        ["Min Distance (m)", f"{distance_stats.get('min_meters', 'N/A'):.2f}"],
        ["Max Distance (m)", f"{distance_stats.get('max_meters', 'N/A'):.2f}"],
        ["Avg Distance (m)", f"{distance_stats.get('avg_meters', 'N/A'):.2f}"],
        ["Median Distance (m)", f"{distance_stats.get('median_meters', 'N/A'):.2f}"]
    ]
    
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
    coverage_stats = calculate_coverage_stats(df)
    
    # Calculate yearly distribution
    yearly_dist = calculate_yearly_distribution(unique_panos)
    
    return {
        "duplicate_stats": duplicate_stats,
        "age_stats": age_stats,
        "coverage_stats": coverage_stats,
        "yearly_distribution": yearly_dist
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
    total_points = len(df)
    points_with_panos = len(df[df['status'] == 'OK'])
    points_without_panos = len(df[df['status'] == 'ZERO_RESULTS'])
    points_with_errors = len(df[df['status'].isin([
        'ERROR',
        'REQUEST_DENIED', 
        'INVALID_REQUEST',
        'OVER_QUERY_LIMIT',
        'NO_DATE',
        'UNKNOWN_ERROR'
    ])])
    
    # Calculate distance statistics for successful panos
    successful_df = df[df['status'] == 'OK'].copy()
    if len(successful_df) > 0:
        successful_df['distance_to_query'] = np.sqrt(
            (successful_df['query_lat'] - successful_df['pano_lat'])**2 +
            (successful_df['query_lon'] - successful_df['pano_lon'])**2
        ) * 111000  # Approximate conversion to meters
        
        distance_stats = {
            "min_meters": float(successful_df['distance_to_query'].min()),
            "max_meters": float(successful_df['distance_to_query'].max()),
            "avg_meters": float(successful_df['distance_to_query'].mean()),
            "median_meters": float(successful_df['distance_to_query'].median()),
            "stdev_meters": float(successful_df['distance_to_query'].std())
        }
    else:
        distance_stats = None
    
    return {
        "points_with_panos": points_with_panos,
        "points_without_panos": points_without_panos,
        "points_with_errors": points_with_errors,
        "coverage_rate": (points_with_panos / total_points) * 100 if total_points > 0 else 0,
        "pano_distance_stats": distance_stats
    }

def calculate_yearly_distribution(df: pd.DataFrame) -> Dict[str, int]:
    """Calculate distribution of panoramas by year."""
    if len(df) == 0:
        return {}
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    # Extract year and count occurrences
    year_counts = df['capture_date'].dt.year.value_counts().sort_index()
    
    return {str(year): int(count) for year, count in year_counts.items()}

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
    print(format_coverage_stats(all_stats['coverage_stats']))
    
    # Print duplicate statistics
    print("\nDuplicate Statistics")
    print("=" * 40)
    print(format_duplicate_stats(all_stats['duplicate_stats']))
    
    # Print age statistics for all panoramas
    print("\nAge Statistics")
    print("=" * 40)
    print(format_age_stats(all_stats['age_stats'], "\nAge Statistics (All Panoramas)"))
    
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