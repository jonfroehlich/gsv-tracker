import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from typing import Tuple, Dict, Any
import logging
import argparse


logger = logging.getLogger(__name__)

map_state_to_capital = {
    'Alabama': 'Montgomery', 'Alaska': 'Juneau', 'Arizona': 'Phoenix', 'Arkansas': 'Little Rock',
    'California': 'Sacramento', 'Colorado': 'Denver', 'Connecticut': 'Hartford', 'Delaware': 'Dover',
    'Florida': 'Tallahassee', 'Georgia': 'Atlanta', 'Hawaii': 'Honolulu', 'Idaho': 'Boise',
    'Illinois': 'Springfield', 'Indiana': 'Indianapolis', 'Iowa': 'Des Moines', 'Kansas': 'Topeka',
    'Kentucky': 'Frankfort', 'Louisiana': 'Baton Rouge', 'Maine': 'Augusta', 'Maryland': 'Annapolis',
    'Massachusetts': 'Boston', 'Michigan': 'Lansing', 'Minnesota': 'St. Paul', 'Mississippi': 'Jackson',
    'Missouri': 'Jefferson City', 'Montana': 'Helena', 'Nebraska': 'Lincoln', 'Nevada': 'Carson City',
    'New Hampshire': 'Concord', 'New Jersey': 'Trenton', 'New Mexico': 'Santa Fe', 'New York': 'Albany',
    'North Carolina': 'Raleigh', 'North Dakota': 'Bismarck', 'Ohio': 'Columbus', 'Oklahoma': 'Oklahoma City',
    'Oregon': 'Salem', 'Pennsylvania': 'Harrisburg', 'Rhode Island': 'Providence', 'South Carolina': 'Columbia',
    'South Dakota': 'Pierre', 'Tennessee': 'Nashville', 'Texas': 'Austin', 'Utah': 'Salt Lake City',
    'Vermont': 'Montpelier', 'Virginia': 'Richmond', 'Washington': 'Olympia', 'West Virginia': 'Charleston',
    'Wisconsin': 'Madison', 'Wyoming': 'Cheyenne'
}

def setup_logger(log_level):
    """
    Sets up global logging to both console and file.
    
    Args:
        log_level (str): Desired logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    
    logger.setLevel(numeric_level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    
    # Create file handler
    file_handler = logging.FileHandler('us_census_city_selection.log')
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

def extract_city_state(geo_area):
    """
    Extracts city and state from geographic area string, removing classification suffixes.
    
    Args:
        geo_area (str): Geographic area string (e.g., "Albany city, New York")
        
    Returns:
        pd.Series: Series containing cleaned city name and state
    """
    try:
        # Split on the last comma
        parts = geo_area.rsplit(', ', 1)
        if len(parts) != 2:
            logger.warning(f"Could not split city and state for: {geo_area}")
            return pd.Series([geo_area, None])
        
        city, state = parts[0], parts[1]
        
        # List of lowercase suffixes to remove
        suffixes = [
            ' charter township',
            ' unified government',
            ' consolidated government',
            ' metro township',
            ' municipality',
            ' borough',
            ' village',
            ' township',
            ' city',
            ' town'
        ]
        
        # Handle parenthetical cases first
        if '(' in city and ')' in city:
            # Extract content within parentheses and rest of the name
            main_part = city.split('(')[0].strip()
            paren_part = city.split('(')[1].split(')')[0].strip()
            # Use the parenthetical part if it exists, otherwise use main part
            city = paren_part if paren_part else main_part
            logger.debug(f"Extracted '{city}' from parenthetical format in '{geo_area}'")
        
        # Remove suffixes if they appear at the end of the city name
        # Only match exact lowercase suffixes
        original_city = city
        for suffix in suffixes:
            if city.endswith(suffix):
                city = city[:-len(suffix)]
                logger.debug(f"Removed suffix '{suffix}' from '{original_city}' to get '{city}'")
                break
        
        return pd.Series([city.strip(), state])
        
    except Exception as e:
        logger.exception(f"Error processing {geo_area}: {str(e)}")
        return pd.Series([None, None])

def clean_and_prepare_data(file_path):
    """
    Reads and prepares census data from Excel file for analysis.
    Logs parsing errors and problematic entries.
    
    Args:
        file_path (str): Path to the census Excel file
        
    Returns:
        pd.DataFrame: Cleaned and prepared DataFrame
    """
    logger.info("Starting data cleaning process...")
    
    # Skip the first 4 rows and use custom column names
    df = pd.read_excel(
        file_path, 
        skiprows=4,
        names=['Geographic Area', 'Est_Base', '2020', '2021', '2022', '2023']
    )
    
    initial_rows = len(df)
    logger.info(f"Initially loaded {initial_rows} rows")
    
    # Check for missing data and report specifics
    for col in ['Geographic Area', '2023']:
        missing = df[df[col].isna()]
        if not missing.empty:
            logger.warning(f"\nFound {len(missing)} rows with missing {col}:")
            for idx, row in missing.iterrows():
                # Get the row number in Excel (accounting for header rows and 0-based index)
                excel_row = idx + 5  # 4 header rows + 1 for 1-based Excel rows
                if col == 'Geographic Area' and not pd.isna(row['2023']):
                    logger.warning(f"Row {excel_row}: Missing city/state but has 2023 population of {row['2023']}")
                elif col == '2023' and not pd.isna(row['Geographic Area']):
                    logger.warning(f"Row {excel_row}: Missing 2023 population for {row['Geographic Area']}")
                else:
                    logger.warning(f"Row {excel_row}: Complete empty row")
    
    # Clean up any potential missing data
    df = df.dropna(subset=['Geographic Area', '2023'])
    rows_after_na = len(df)
    if rows_after_na < initial_rows:
        logger.info(f"\nRemoved {initial_rows - rows_after_na} rows with missing essential data")
    
    # Apply the city/state extraction
    df[['City', 'State']] = df['Geographic Area'].apply(extract_city_state)
    
    # Remove any rows where we couldn't extract state properly
    rows_before_state = len(df)
    df = df.dropna(subset=['State'])
    rows_after_state = len(df)
    
    if rows_before_state > rows_after_state:
        logger.warning(f"Removed {rows_before_state - rows_after_state} rows with invalid state data")
    
    # Convert population columns to numeric, handling any potential non-numeric values
    for col in ['2020', '2021', '2022', '2023']:
        try:
            numeric_series = pd.to_numeric(df[col], errors='coerce')
            invalid_rows = df[numeric_series.isna() & df[col].notna()]
            if not invalid_rows.empty:
                for idx, row in invalid_rows.iterrows():
                    logger.warning(
                        f"Non-numeric value in {col} for {row['Geographic Area']}: {row[col]}"
                    )
            df[col] = numeric_series
        except Exception as e:
            logger.error(f"Error converting {col} to numeric: {str(e)}")
    
    # Print final statistics
    logger.info(f"\nFinal dataset contains {len(df)} rows")
    logger.info(f"States found: {', '.join(sorted(df['State'].unique()))}")
    
    return df

def select_study_cities(df: pd.DataFrame, cities_per_quartile: int = 5) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Selects cities for study using a stratified sampling approach:
    - Automatically includes state capital and largest city
    - Randomly samples additional cities from each population quartile
    
    Args:
        df (pd.DataFrame): Prepared census DataFrame with City, State, and population columns
        cities_per_quartile (int): Number of cities to randomly select from each quartile
        
    Returns:
        pd.DataFrame: Selected cities with their selection method and quartile
        dict: Statistics about the selection process
    """

    if cities_per_quartile < 1:
        raise ValueError("cities_per_quartile must be at least 1")
    
    # Create empty DataFrame to store selections
    selected_cities = pd.DataFrame()
    selection_stats = {}
    
    for state in df['State'].unique():
        state_df = df[df['State'] == state].copy()
        logger.info(f"Selecting cities for {state}...")

        state_df = state_df.reset_index(drop=True)  # Reset index for state DataFrame
        
        # Skip if insufficient data
        min_cities_required = 4 * cities_per_quartile + 2
        if len(state_df) < min_cities_required: 
            logger.warning(f"Warning: Insufficient data for {state} ({len(state_df)} cities)."
                  f"With {cities_per_quartile} cities per quartile, need at least {min_cities_required} cities per state.")
            continue
            
        state_selections = pd.DataFrame()
        
        # 1. Add state capital
        capital_city_name = map_state_to_capital.get(state) 
        if capital_city_name: 
            capital_city = state_df[state_df['City'] == capital_city_name] 
            capital_city = capital_city.assign(selection_method='capital')
            state_selections = pd.concat([state_selections, capital_city], ignore_index=True)  # Reset index during concat
            state_df = state_df[state_df['City'] != capital_city_name].reset_index(drop=True)  # Reset index after filtering
        
        # 2. Add largest city by population
        top_2_cities = state_df.nlargest(2, '2023').copy()
        
        # Check if capital was found and is the largest city
        if not capital_city.empty and capital_city.index[0] == top_2_cities.index[0]:
            largest_city = top_2_cities.iloc[[1]]
        else:
            largest_city = top_2_cities.iloc[[0]]
    
        largest_city = largest_city.assign(selection_method='largest' if not capital_city.empty and capital_city.index[0] != top_2_cities.index[0] else 'largest (2nd)')
        state_selections = pd.concat([state_selections, largest_city], ignore_index=True)  # Reset index during concat
        
        # 3. Calculate quartiles for remaining cities
        remaining_cities = state_df[~state_df.index.isin(largest_city.index)].copy()
        remaining_cities = remaining_cities.reset_index(drop=True)  # Reset index after filtering
        remaining_cities['population_quartile'] = pd.qcut(
            remaining_cities['2023'], 
            q=4, 
            labels=['Q1', 'Q2', 'Q3', 'Q4']
        )
        
        # 4. Sample from each quartile
        for quartile in ['Q1', 'Q2', 'Q3', 'Q4']:
            quartile_cities = remaining_cities[
                remaining_cities['population_quartile'] == quartile
            ]
            
            # Sample cities (or take all if fewer than requested)
            sample_size = min(cities_per_quartile, len(quartile_cities))
            if sample_size > 0:
                sampled = quartile_cities.sample(n=sample_size).copy()
                sampled = sampled.assign(selection_method=f'random_{quartile}')
                state_selections = pd.concat([state_selections, sampled], ignore_index=True)  # Reset index during concat
        
        # Store statistics
        selection_stats[state] = {
            'total_selected': len(state_selections),
            'largest_city': largest_city['City'].iloc[0],
            'quartile_counts': state_selections['selection_method'].value_counts().to_dict()
        }
        
        # Add to main selection DataFrame
        selected_cities = pd.concat([selected_cities, state_selections], ignore_index=True)  # Reset index during final concat
    
    return selected_cities, selection_stats

def analyze_selection_coverage(selected_cities, original_df):
    """
    Analyzes the coverage and representativeness of selected cities.
    Provides detailed statistics per state including capital and largest city populations,
    and quartile statistics.
    
    Args:
        selected_cities (pd.DataFrame): DataFrame of selected cities
        original_df (pd.DataFrame): Original complete DataFrame
        
    Returns:
        dict: Analysis metrics including detailed state-by-state analysis
    """
    analysis = {}
    
    # Calculate population coverage
    total_pop = original_df['2023'].sum()
    selected_pop = selected_cities['2023'].sum()
    
    analysis['population_coverage'] = {
        'total_population': total_pop,
        'selected_population': selected_pop,
        'coverage_percentage': (selected_pop / total_pop) * 100
    }
    
    # Analyze geographic distribution
    analysis['geographic_distribution'] = {
        'cities_per_state': selected_cities['State'].value_counts().to_dict(),
        'total_states': len(selected_cities['State'].unique())
    }
    
    # Analyze population size distribution
    analysis['size_distribution'] = {
        'mean_pop': selected_cities['2023'].mean(),
        'median_pop': selected_cities['2023'].median(),
        'min_pop': selected_cities['2023'].min(),
        'max_pop': selected_cities['2023'].max()
    }
    
    # Add detailed state analysis
    analysis['state_details'] = {}
    
    for state in selected_cities['State'].unique():
        state_selections = selected_cities[selected_cities['State'] == state]
        
        # Get capital city info
        capital_city = state_selections[state_selections['selection_method'] == 'capital']
        capital_pop = capital_city['2023'].iloc[0] if not capital_city.empty else None
        
        # Get largest/second largest city info
        largest_city = state_selections[
            state_selections['selection_method'].isin(['largest', 'largest (2nd)'])
        ]
        largest_pop = largest_city['2023'].iloc[0] if not largest_city.empty else None
        largest_name = largest_city['City'].iloc[0] if not largest_city.empty else None
        largest_type = largest_city['selection_method'].iloc[0] if not largest_city.empty else None
        
        # Calculate quartile statistics
        quartile_stats = {}
        for quartile in ['Q1', 'Q2', 'Q3', 'Q4']:
            quartile_cities = state_selections[
                state_selections['selection_method'] == f'random_{quartile}'
            ]
            if not quartile_cities.empty:
                quartile_stats[quartile] = {
                    'avg': quartile_cities['2023'].mean(),
                    'median': quartile_cities['2023'].median(),
                    'std': quartile_cities['2023'].std(),
                    'count': len(quartile_cities)
                }
        
        analysis['state_details'][state] = {
            'capital': {
                'name': capital_city['City'].iloc[0] if not capital_city.empty else None,
                'population': capital_pop
            },
            'largest_city': {
                'name': largest_name,
                'population': largest_pop,
                'type': largest_type
            },
            'quartile_stats': quartile_stats
        }
    
    return analysis

def print_selection_analysis(analysis):
    """
    Prints a formatted analysis of city selection coverage and statistics.
    
    Args:
        analysis (dict): Analysis dictionary from analyze_selection_coverage()
        
    Example:
        analysis = analyze_selection_coverage(selected_df, original_df)
        print_selection_analysis(analysis)
    """
    # Helper function for number formatting
    def format_num(n):
        if n is None:
            return "N/A"
        return f"{n:,.0f}"
    
    # Print overall coverage
    print("\n=== POPULATION COVERAGE ===")
    cov = analysis['population_coverage']
    print(f"Total Population:     {format_num(cov['total_population'])}")
    print(f"Selected Population:  {format_num(cov['selected_population'])}")
    print(f"Coverage Percentage:  {cov['coverage_percentage']:.1f}%")

    # Print size distribution
    print("\n=== CITY SIZE DISTRIBUTION ===")
    size = analysis['size_distribution']
    print(f"Mean Population:   {format_num(size['mean_pop'])}")
    print(f"Median Population: {format_num(size['median_pop'])}")
    print(f"Minimum:          {format_num(size['min_pop'])}")
    print(f"Maximum:          {format_num(size['max_pop'])}")

    # Print geographic distribution
    print("\n=== GEOGRAPHIC DISTRIBUTION ===")
    print(f"Total States Covered: {analysis['geographic_distribution']['total_states']}")
    
    # Print state details
    print("\n=== STATE-BY-STATE ANALYSIS ===")
    for state, details in sorted(analysis['state_details'].items()):
        print(f"\n{state}")
        
        # Capital info
        cap = details['capital']
        print(f"  Capital: {cap['name'] or 'N/A'} ({format_num(cap['population'])})")
        
        # Largest city info
        largest = details['largest_city']
        if largest['name']:
            print(f"  {largest['type'].title()}: {largest['name']} ({format_num(largest['population'])})")
        
        # Quartile stats
        if details['quartile_stats']:
            print("  Quartile Statistics:")
            for q, stats in details['quartile_stats'].items():
                print(f"    {q}: {stats['count']} cities, "
                      f"avg={format_num(stats['avg'])}, "
                      f"median={format_num(stats['median'])}")

def analyze_state_statistics(df):
    """
    Calculates key statistics for each state from census data.
    
    Args:
        df (pd.DataFrame): Prepared census DataFrame
        
    Returns:
        dict: Dictionary containing statistical analysis by state
    """
    stats_by_state = {}
    
    for state in df['State'].unique():
        state_data = df[df['State'] == state].copy()  # Create a copy to avoid SettingWithCopyWarning
        
        # Skip if no data for state
        if len(state_data) == 0:
            continue
            
        # Calculate 2020-2023 growth rates
        state_data['growth_rate'] = ((state_data['2023'] - state_data['2020']) / state_data['2020']) * 100
        
        stats_by_state[state] = {
            'num_cities': len(state_data),
            'avg_population_2023': state_data['2023'].mean(),
            'median_population_2023': state_data['2023'].median(),
            'std_population_2023': state_data['2023'].std(),
            'total_population_2023': state_data['2023'].sum(),
            'largest_city': {
                'name': state_data.loc[state_data['2023'].idxmax(), 'City'],
                'population': state_data['2023'].max()
            },
            'smallest_city': {
                'name': state_data.loc[state_data['2023'].idxmin(), 'City'],
                'population': state_data['2023'].min()
            },
            'avg_growth_rate': state_data['growth_rate'].mean(),
            'fastest_growing': {
                'name': state_data.loc[state_data['growth_rate'].idxmax(), 'City'],
                'rate': state_data['growth_rate'].max()
            }
        }
    
    return stats_by_state

def write_selected_cities(selected_cities: pd.DataFrame, output_file: str = 'selected_cities.txt'):
    """
    Writes selected cities to a text file, one city per line in 'city, state' format.
    
    Args:
        selected_cities (pd.DataFrame): DataFrame containing selected cities with City and State columns
        output_file (str): Path to output text file (default: 'selected_cities.txt')
    """
    logger.info(f"Writing selected cities to {output_file}")
    
    try:
        with open(output_file, 'w') as f:
            # Sort by state then city for consistent output
            sorted_cities = selected_cities.sort_values(['State', 'City'])
            for _, row in sorted_cities.iterrows():
                f.write(f"{row['City']}, {row['State']}\n")
        logger.info(f"Successfully wrote {len(selected_cities)} cities to {output_file}")
    except Exception as e:
        logger.error(f"Error writing to {output_file}: {str(e)}")

# Main execution
if __name__ == "__main__":
    """Main entry point for the script."""
    # Set up command line argument parsing
    # file_path = "SUB-IP-EST2023-POP.xlsx"

    parser = argparse.ArgumentParser(description='Process US Census data with configurable logging.')
    
    parser.add_argument(
        '--input-file', 
        default='SUB-IP-EST2023-POP.xlsx',
        help='Path to the census Excel file (default: SUB-IP-EST2023-POP.xlsx)'
    )

    parser.add_argument(
        '--log-level', 
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set the logging level'
    )
    
    args = parser.parse_args()
    
    # Set up logging
    setup_logger(args.log_level)
    
    # Prepare data
    df = clean_and_prepare_data(args.input_file)
    
    # Calculate statistics
    # stats = analyze_state_statistics(df)
    
    # # Print statistics for each state
    # for state, state_stats in stats.items():
    #     print(f"\n{'='*50}")
    #     print(f"Statistics for {state}:")
    #     print(f"{'='*50}")
    #     print(f"Number of cities: {state_stats['num_cities']}")
    #     print(f"Average population (2023): {state_stats['avg_population_2023']:,.0f}")
    #     print(f"Median population (2023): {state_stats['median_population_2023']:,.0f}")
    #     print(f"Population standard deviation: {state_stats['std_population_2023']:,.0f}")
    #     print(f"Total population (2023): {state_stats['total_population_2023']:,.0f}")
    #     print(f"\nLargest city: {state_stats['largest_city']['name']} "
    #           f"({state_stats['largest_city']['population']:,.0f} people)")
    #     print(f"Smallest city: {state_stats['smallest_city']['name']} "
    #           f"({state_stats['smallest_city']['population']:,.0f} people)")
    #     print(f"\nAverage growth rate (2020-2023): {state_stats['avg_growth_rate']:.2f}%")
    #     print(f"Fastest growing city: {state_stats['fastest_growing']['name']} "
    #           f"({state_stats['fastest_growing']['rate']:.2f}%)")

    # Select study cities
    selected_cities, selection_stats = select_study_cities(df)
    analysis = analyze_selection_coverage(selected_cities, df)
    print_selection_analysis(analysis)

    # Write selected cities to file
    write_selected_cities(selected_cities)
    
    # Create visualizations
    # create_visualizations(df)