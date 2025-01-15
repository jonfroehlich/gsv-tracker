"""
analysis.py - Module for analyzing and displaying GSV metadata statistics.

This module provides functions and classes for analyzing Google Street View metadata and 
displaying formatted statistics tables. It's designed to be used by multiple
components like json_summarizer.py, check_status_codes.py, and cli.py.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple, ClassVar
import pandas as pd
from tabulate import tabulate
from datetime import datetime
import numpy as np
import os
from collections import Counter

@dataclass
class DistanceStats:
    """Statistics about distances between query points and panoramas."""
    min_meters: float
    max_meters: float
    avg_meters: float
    median_meters: float
    stdev_meters: float

    # Class variable mapping internal field names to human-readable labels
    FIELD_LABELS: ClassVar[Dict[str, str]] = {
        'min_meters': 'Min Distance (m)',
        'max_meters': 'Max Distance (m)',
        'avg_meters': 'Avg Distance (m)',
        'median_meters': 'Median Distance (m)',
        'stdev_meters': 'Std Dev Distance (m)'
    }

    def to_rows(self) -> List[List[str]]:
        """Convert stats to formatted rows for tabulation."""
        return [
            [self.FIELD_LABELS[field], f"{getattr(self, field):.2f}"]
            for field in self.FIELD_LABELS.keys()
        ]

@dataclass
class CoverageStats:
    """Statistics about GSV coverage for queried points."""
    num_points_with_panos: int
    num_points_with_unique_pano_ids: int
    num_points_with_errors: int
    num_points_without_panos: int
    coverage_rate: float
    pano_distance_stats: Optional[DistanceStats] = None

    FIELD_LABELS: ClassVar[Dict[str, str]] = {
        'num_points_with_panos': 'Points with Panoramas',
        'num_points_with_unique_pano_ids': 'Points with Unique Pano IDs',
        'num_points_without_panos': 'Points without Panoramas',
        'num_points_with_errors': 'Points with Errors',
        'coverage_rate': 'Unique Pano IDs / Num Points Queried'
    }

    def to_rows(self) -> List[List[str]]:
        """Convert stats to formatted rows for tabulation."""
        rows = [
            [self.FIELD_LABELS[field], 
             f"{getattr(self, field):.2f}%" if field == 'coverage_rate' else str(getattr(self, field))]
            for field in self.FIELD_LABELS.keys()
        ]
        
        if self.pano_distance_stats:
            rows.extend(self.pano_distance_stats.to_rows())
            
        return rows

    def format_table(self) -> str:
        """Create a formatted table representation."""
        return tabulate(
            self.to_rows(),
            headers=["Metric", "Value"],
            tablefmt="simple",
            numalign="right",
            stralign="left"
        )

@dataclass
class AgeStats:
    """Statistics about panorama ages."""
    count: int
    oldest_pano_date: Optional[str]
    newest_pano_date: Optional[str]
    avg_pano_age_years: Optional[float]
    median_pano_age_years: Optional[float]
    stdev_pano_age_years: Optional[float]
    age_percentiles_years: Optional[Dict[str, float]]

    FIELD_LABELS: ClassVar[Dict[str, str]] = {
        'count': 'Total Panoramas',
        'oldest_pano_date': 'Oldest Panorama',
        'newest_pano_date': 'Newest Panorama',
        'avg_pano_age_years': 'Average Age (years)',
        'median_pano_age_years': 'Median Age (years)',
        'stdev_pano_age_years': 'Std Dev Age (years)'
    }

    def format_field_value(self, field: Any) -> str:
        """Helper to safely format field values that might be None."""
        value = getattr(self, field)

        if value is None:
            return "N/A"
        if field == "count":
            return f"{value:,}"
        if isinstance(value, (float, int)):
            return f"{value:.1f}"
        return str(value)

    def to_rows(self) -> List[List[str]]:
        """Convert stats to formatted rows for tabulation."""
        return [
            [self.FIELD_LABELS[field], self.format_field_value(field)]
            for field in self.FIELD_LABELS.keys()
        ]

    def format_table(self, title: str = "Age Statistics") -> str:
        """Create a formatted table representation."""
        return f"\n{title}\n" + tabulate(
            self.to_rows(),
            headers=["Metric", "Value"],
            tablefmt="simple",
            numalign="right",
            stralign="left"
        )

def calculate_age_stats(df: pd.DataFrame, now: pd.Timestamp) -> AgeStats:
    """Helper function to calculate age statistics for panoramas."""
    if len(df) == 0:
        return AgeStats(
            count=0,
            oldest_pano_date=None,
            newest_pano_date=None,
            avg_pano_age_years=None,
            median_pano_age_years=None,
            stdev_pano_age_years=None,
            age_percentiles_years=None
        )
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    valid_dates_mask = df['capture_date'].notna()
    df_with_dates = df[valid_dates_mask]
    
    ages = (now - df_with_dates['capture_date']).dt.total_seconds() / (365.25 * 24 * 3600)
    
    return AgeStats(
        count=len(df),
        oldest_pano_date=df_with_dates['capture_date'].min().isoformat() if len(df_with_dates) > 0 else None,
        newest_pano_date=df_with_dates['capture_date'].max().isoformat() if len(df_with_dates) > 0 else None,
        avg_pano_age_years=float(ages.mean()) if len(ages) > 0 else None,
        median_pano_age_years=float(ages.median()) if len(ages) > 0 else None,
        stdev_pano_age_years=float(ages.std()) if len(ages) > 0 else None,
        age_percentiles_years={
            "p10": float(ages.quantile(0.1)) if len(ages) > 0 else None,
            "p25": float(ages.quantile(0.25)) if len(ages) > 0 else None,
            "p75": float(ages.quantile(0.75)) if len(ages) > 0 else None,
            "p90": float(ages.quantile(0.9)) if len(ages) > 0 else None
        }
    )

def calculate_coverage_stats(df: pd.DataFrame) -> CoverageStats:
    """Calculate coverage and distance statistics."""
    num_total_points = len(df)

    total_points_with_panos = df[df['status'] == 'OK']
    num_points_with_panos = len(total_points_with_panos)
    num_points_without_panos = len(df[df['status'] == 'ZERO_RESULTS'])
    num_points_with_errors = len(df[df['status'].isin([
        'ERROR', 'REQUEST_DENIED', 'INVALID_REQUEST',
        'OVER_QUERY_LIMIT', 'NO_DATE', 'UNKNOWN_ERROR'
    ])])

    successful_df_no_duplicates = total_points_with_panos.drop_duplicates(subset=['pano_id']).copy()
    num_points_with_unique_pano_ids = len(successful_df_no_duplicates)
    num_points_without_unique_pano_ids = num_points_with_panos - len(successful_df_no_duplicates)

    distance_stats = None
    if len(successful_df_no_duplicates) > 0:
        distances = np.sqrt(
            (successful_df_no_duplicates['query_lat'] - successful_df_no_duplicates['pano_lat'])**2 +
            (successful_df_no_duplicates['query_lon'] - successful_df_no_duplicates['pano_lon'])**2
        ) * 111000  # Approximate conversion to meters
        
        successful_df_no_duplicates.loc[:, 'distance_to_query'] = distances
        
        distance_stats = DistanceStats(
            min_meters=float(successful_df_no_duplicates['distance_to_query'].min()),
            max_meters=float(successful_df_no_duplicates['distance_to_query'].max()),
            avg_meters=float(successful_df_no_duplicates['distance_to_query'].mean()),
            median_meters=float(successful_df_no_duplicates['distance_to_query'].median()),
            stdev_meters=float(successful_df_no_duplicates['distance_to_query'].std())
        )
    
    return CoverageStats(
        num_points_with_panos=num_points_with_panos,
        num_points_with_unique_pano_ids=num_points_with_unique_pano_ids,
        num_points_without_panos=num_points_without_panos + num_points_without_unique_pano_ids,
        num_points_with_errors=num_points_with_errors,
        coverage_rate=(num_points_with_unique_pano_ids / num_total_points) * 100 if num_total_points > 0 else 0,
        pano_distance_stats=distance_stats
    )

@dataclass
class DuplicateStats:
    """Statistics about panorama duplications."""
    total_unique_panos: int
    total_pano_references: int
    duplicate_reference_count: int
    most_referenced_count: int
    panos_with_multiple_refs: int
    average_references_per_pano: float

    FIELD_LABELS: ClassVar[Dict[str, str]] = {
        'total_unique_panos': 'Total Unique Panoramas',
        'total_pano_references': 'Total References',
        'duplicate_reference_count': 'Duplicate References',
        'most_referenced_count': 'Most Referenced Count',
        'panos_with_multiple_refs': 'Panoramas with Multiple Refs',
        'average_references_per_pano': 'Average References per Pano'
    }

    def to_rows(self) -> List[List[str]]:
        """Convert stats to formatted rows for tabulation."""
        return [
            [self.FIELD_LABELS[field], 
             f"{getattr(self, field):.2f}" if field == 'average_references_per_pano' 
             else str(getattr(self, field))]
            for field in self.FIELD_LABELS.keys()
        ]

    def format_table(self) -> str:
        """Create a formatted table representation."""
        return tabulate(
            self.to_rows(),
            headers=["Metric", "Value"],
            tablefmt="simple",
            numalign="right",
            stralign="left"
        )

@dataclass
class YearlyDistribution:
    """Distribution of panoramas by year."""
    counts: Dict[int, int]

    def to_rows(self) -> List[List[str]]:
        """Convert distribution to formatted rows for tabulation."""
        total_panos = sum(self.counts.values())
        rows = []
        
        for year in sorted(self.counts.keys()):
            count = self.counts[year]
            percentage = (count / total_panos) * 100
            rows.append([str(year), str(count), f"{percentage:.2f}%"])
        
        # Add total row
        rows.append(["TOTAL", str(total_panos), "100.00%"])
        return rows

    def format_table(self, title: str = "Yearly Distribution") -> str:
        """Create a formatted table representation."""
        return f"\n{title}\n" + tabulate(
            self.to_rows(),
            headers=["Year", "Count", "Percentage"],
            tablefmt="simple",
            floatfmt=".2f",
            numalign="right",
            stralign="left"
        )

@dataclass
class DailyDistribution:
    """Distribution of panoramas by day."""
    counts: Dict[str, int]  # Maps ISO date strings (YYYY-MM-DD) to counts

    def to_rows(self) -> List[List[str]]:
        """Convert distribution to formatted rows for tabulation."""
        total_panos = sum(self.counts.values())
        rows = []
        
        for date in sorted(self.counts.keys()):
            count = self.counts[date]
            percentage = (count / total_panos) * 100
            rows.append([date, str(count), f"{percentage:.2f}%"])
        
        # Add total row
        rows.append(["TOTAL", str(total_panos), "100.00%"])
        return rows

    def format_table(self, title: str = "Daily Distribution") -> str:
        """Create a formatted table representation."""
        return f"\n{title}\n" + tabulate(
            self.to_rows(),
            headers=["Date", "Count", "Percentage"],
            tablefmt="simple",
            floatfmt=".2f",
            numalign="right",
            stralign="left"
        )

@dataclass
class PhotographerStats:
    """Statistics about photographer contributions."""
    photographer_counts: Dict[str, int]  # Maps photographer name to unique pano count
    top_n: int = 5  # Number of top photographers to show

    def to_rows(self) -> List[List[str]]:
        """Convert stats to formatted rows for tabulation."""
        total_panos = sum(self.photographer_counts.values())
        rows = []
        
        # Sort by count and take top N
        sorted_photographers = sorted(
            self.photographer_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:self.top_n]
        
        for photographer, count in sorted_photographers:
            percentage = (count / total_panos) * 100
            rows.append([
                photographer,
                f"{count:,}",
                f"{percentage:.2f}%"
            ])
            
        return rows

    def format_table(self, title: str = "Top Photographers by Unique Panoramas") -> str:
        """Create a formatted table representation."""
        return f"\n{title}\n" + tabulate(
            self.to_rows(),
            headers=["Photographer", "Unique Panos", "Percentage"],
            tablefmt="simple",
            floatfmt=".2f",
            numalign="right",
            stralign="left"
        )

@dataclass
class GSVAnalysisResults:
    """Complete set of GSV metadata analysis results."""
    duplicate_stats: DuplicateStats
    age_stats: AgeStats
    coverage_stats: CoverageStats
    yearly_distribution: YearlyDistribution
    daily_distribution: DailyDistribution
    photographer_stats: PhotographerStats

    def print_summary(self, title: str = "GSV Analysis Summary") -> None:
        """Print a comprehensive summary of the analysis results."""
        print(f"\n{title}")
        print("=" * 40)

        print("\nCoverage Statistics")
        print(self.coverage_stats.format_table())

        print("\nDuplicate Statistics")
        print(self.duplicate_stats.format_table())

        print(self.age_stats.format_table())
        
        print("\nPhotographer Statistics")
        print(self.photographer_stats.format_table())
        
        print("\nYearly and Daily Distributions")
        print(self.yearly_distribution.format_table())
        print(self.daily_distribution.format_table())

def calculate_daily_distribution(df: pd.DataFrame) -> DailyDistribution:
    """
    Calculate distribution of panoramas by date (YYYY-MM-DD).
    
    Args:
        df: DataFrame containing panorama data with capture_date column
        
    Returns:
        DailyDistribution object containing date-wise counts
    """
    if len(df) == 0:
        return DailyDistribution(counts={})
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    # Use ISO format for dates (YYYY-MM-DD)
    date_counts = df['capture_date'].apply(lambda x: x.date().isoformat()).value_counts().sort_index()
    
    # Convert counts to integers while maintaining ISO date strings as keys
    return DailyDistribution(
        counts={date: int(count) for date, count in date_counts.items()}
    )

def calculate_photographer_stats(df: pd.DataFrame) -> PhotographerStats:
    """
    Calculate photographer contribution statistics.
    
    Args:
        df: DataFrame containing GSV metadata with 'copyright_info' and 'pano_id' columns
        
    Returns:
        PhotographerStats containing photographer contribution analysis
    """
    # Filter for successful panoramas and drop duplicates
    ok_panos = df[df['status'] == 'OK'].drop_duplicates(subset=['pano_id'])
    
    # Count unique pano_ids per photographer
    photographer_counts = ok_panos['copyright_info'].value_counts().to_dict()
    
    return PhotographerStats(photographer_counts=photographer_counts)

def calculate_pano_stats(
    df: pd.DataFrame, 
    now: pd.Timestamp,
    copyright_filter: Optional[str] = None
) -> GSVAnalysisResults:
    """
    Calculate comprehensive panorama statistics from a DataFrame.
    
    Args:
        df: DataFrame containing GSV metadata
        now: Timestamp to use for age calculations
        copyright_filter: Optional string to filter copyright info (e.g., 'Google')
        
    Returns:
        GSVAnalysisResults containing all calculated statistics
        
    Example:
        >>> df = pd.read_csv('gsv_metadata.csv')
        >>> now = pd.Timestamp.now()
        >>> results = calculate_pano_stats(df, now)
        >>> results.print_summary("Analysis Results")
    """
    # Apply copyright filter if specified
    filtered_df = df[df['copyright_info'].str.contains(copyright_filter, na=False)] if copyright_filter else df
    
    # Get successful panoramas
    ok_panos = filtered_df[filtered_df['status'] == 'OK'].copy()
    
    # Calculate duplicate statistics
    pano_id_counts = ok_panos['pano_id'].value_counts()
    duplicate_stats = DuplicateStats(
        total_unique_panos=len(pano_id_counts),
        total_pano_references=len(ok_panos),
        duplicate_reference_count=len(ok_panos) - len(pano_id_counts),
        most_referenced_count=int(pano_id_counts.max()) if not pano_id_counts.empty else 0,
        panos_with_multiple_refs=int((pano_id_counts > 1).sum()),
        average_references_per_pano=float(len(ok_panos) / len(pano_id_counts)) if len(pano_id_counts) > 0 else 0
    )
    
    # Calculate age statistics for unique panoramas
    unique_panos = ok_panos.drop_duplicates(subset=['pano_id'])
    age_stats = calculate_age_stats(unique_panos, now)
    
    # Calculate coverage statistics
    coverage_stats = calculate_coverage_stats(filtered_df)
    
    # Calculate distributions and photographer stats
    yearly_dist = calculate_yearly_distribution(unique_panos)
    daily_dist = calculate_daily_distribution(unique_panos)
    photographer_stats = calculate_photographer_stats(filtered_df)
    
    return GSVAnalysisResults(
        duplicate_stats=duplicate_stats,
        age_stats=age_stats,
        coverage_stats=coverage_stats,
        yearly_distribution=yearly_dist,
        daily_distribution=daily_dist,
        photographer_stats=photographer_stats
    )

def calculate_yearly_distribution(df: pd.DataFrame) -> YearlyDistribution:
    """Calculate distribution of panoramas by year."""
    if len(df) == 0:
        return YearlyDistribution(counts={})
    
    # Convert capture_date to datetime if necessary
    if not pd.api.types.is_datetime64_any_dtype(df['capture_date']):
        df['capture_date'] = pd.to_datetime(df['capture_date'])
    
    # Extract year and count occurrences
    year_counts = df['capture_date'].dt.year.value_counts().sort_index()
    
    return YearlyDistribution(
        counts={int(year): int(count) for year, count in year_counts.items()}
    )

def analyze_gsv_status(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze GSV metadata status codes in a DataFrame.
    
    Args:
        df: DataFrame containing GSV metadata
        
    Returns:
        Dictionary containing status analysis including counts and percentages
        
    Raises:
        ValueError: If no status column is found in the DataFrame
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

def print_df_summary(df: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> None:
    """
    Print a comprehensive summary of download results.
    
    Args:
        df: DataFrame containing the downloaded GSV metadata
        now: Optional timestamp for age calculations (defaults to current time)
    """
    # Use provided timestamp or current time
    timestamp = now if now is not None else pd.Timestamp.now()
    
    # Calculate statistics for all panoramas and Google panoramas
    all_stats = calculate_pano_stats(df, timestamp)
    google_stats = calculate_pano_stats(df, timestamp, copyright_filter='Google')
    
    # Print summaries
    print("\nAll Panoramas")
    print("=" * 40)
    all_stats.print_summary()
    
    print("\nGoogle Panoramas Only")
    print("=" * 40)
    google_stats.print_summary()