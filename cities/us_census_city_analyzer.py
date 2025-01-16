import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np


def clean_and_prepare_data(file_path):
    """
    Reads and prepares census data from Excel file for analysis.
    Logs parsing errors and problematic entries.
    
    Args:
        file_path (str): Path to the census Excel file
        
    Returns:
        pd.DataFrame: Cleaned and prepared DataFrame
    """
    print("Starting data cleaning process...")
    
    # Skip the first 4 rows and use custom column names
    df = pd.read_excel(
        file_path, 
        skiprows=4,
        names=['Geographic Area', 'Est_Base', '2020', '2021', '2022', '2023']
    )
    
    initial_rows = len(df)
    print(f"Initially loaded {initial_rows} rows")
    
    # Check for missing data and report specifics
    missing_data = []
    
    # Check each required column
    for col in ['Geographic Area', '2023']:
        missing = df[df[col].isna()]
        if not missing.empty:
            print(f"\nRows with missing {col}:")
            for idx, row in missing.iterrows():
                # Get the row number in Excel (accounting for header rows and 0-based index)
                excel_row = idx + 5  # 4 header rows + 1 for 1-based Excel rows
                missing_info = f"Row {excel_row}: "
                
                # If Geographic Area is missing but we have other data
                if col == 'Geographic Area' and not pd.isna(row['2023']):
                    missing_info += f"Missing city/state but has 2023 population of {row['2023']}"
                # If 2023 is missing but we have Geographic Area
                elif col == '2023' and not pd.isna(row['Geographic Area']):
                    missing_info += f"Missing 2023 population for {row['Geographic Area']}"
                # If both are missing
                else:
                    missing_info += "Complete empty row"
                
                print(missing_info)
                missing_data.append(missing_info)
    
    # Clean up any potential missing data
    df = df.dropna(subset=['Geographic Area', '2023'])
    rows_after_na = len(df)
    if rows_after_na < initial_rows:
        print(f"\nRemoved {initial_rows - rows_after_na} rows with missing essential data")
    
    # Extract city and state more reliably
    parsing_errors = []
    
    def extract_city_state(geo_area):
        try:
            # Split on the last comma
            parts = geo_area.rsplit(', ', 1)
            if len(parts) == 2:
                return pd.Series([parts[0], parts[1]])
            parsing_errors.append(f"Could not split city and state for: {geo_area}")
            return pd.Series([geo_area, None])
        except Exception as e:
            parsing_errors.append(f"Error processing {geo_area}: {str(e)}")
            return pd.Series([None, None])
    
    # Apply the extraction
    df[['City', 'State']] = df['Geographic Area'].apply(extract_city_state)
    
    # Remove any rows where we couldn't extract state properly
    rows_before_state = len(df)
    df = df.dropna(subset=['State'])
    rows_after_state = len(df)
    
    if rows_before_state > rows_after_state:
        print(f"Removed {rows_before_state - rows_after_state} rows with invalid state data")
    
    # Convert population columns to numeric, handling any potential non-numeric values
    numeric_conversion_errors = []
    for col in ['2020', '2021', '2022', '2023']:
        try:
            numeric_series = pd.to_numeric(df[col], errors='coerce')
            invalid_rows = df[numeric_series.isna() & df[col].notna()]
            if not invalid_rows.empty:
                for idx, row in invalid_rows.iterrows():
                    numeric_conversion_errors.append(
                        f"Non-numeric value in {col} for {row['Geographic Area']}: {row[col]}"
                    )
            df[col] = numeric_series
        except Exception as e:
            print(f"Error converting {col} to numeric: {str(e)}")
    
    # Print parsing errors if any
    if parsing_errors:
        print("\nParsing Errors Found:")
        for error in parsing_errors:
            print(f"- {error}")
    
    # Print numeric conversion errors if any
    if numeric_conversion_errors:
        print("\nNumeric Conversion Errors Found:")
        for error in numeric_conversion_errors:
            print(f"- {error}")
    
    # Print final statistics
    print(f"\nFinal dataset contains {len(df)} rows")
    print(f"States found: {', '.join(sorted(df['State'].unique()))}")
    
    return df

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

def create_visualizations(df):
    """
    Creates visualizations for census data analysis.
    
    Args:
        df (pd.DataFrame): Prepared census DataFrame
    """
    # Set style
    plt.style.use('seaborn')
    
    # 1. Population Distribution (Box Plot)
    plt.figure(figsize=(15, 8))
    sns.boxplot(x='State', y='2023', data=df)
    plt.xticks(rotation=45, ha='right')
    plt.title('City Population Distribution by State (2023)')
    plt.ylabel('Population')
    plt.tight_layout()
    plt.show()
    
    # 2. Growth Rate Analysis
    df['growth_rate'] = ((df['2023'] - df['2020']) / df['2020']) * 100
    
    plt.figure(figsize=(15, 8))
    sns.barplot(x='State', y='growth_rate', 
                data=df.groupby('State')['growth_rate'].mean().reset_index(),
                color='skyblue')
    plt.xticks(rotation=45, ha='right')
    plt.title('Average City Population Growth Rate by State (2020-2023)')
    plt.ylabel('Growth Rate (%)')
    plt.tight_layout()
    plt.show()
    
    # 3. City Size Distribution
    df['size_category'] = pd.cut(df['2023'], 
                                bins=[0, 1000, 5000, 10000, 50000, float('inf')],
                                labels=['Very Small', 'Small', 'Medium', 'Large', 'Very Large'])
    
    plt.figure(figsize=(12, 6))
    df['size_category'].value_counts().plot(kind='bar')
    plt.title('Distribution of City Sizes (2023)')
    plt.xlabel('City Size Category')
    plt.ylabel('Number of Cities')
    plt.tight_layout()
    plt.show()

# Main execution
if __name__ == "__main__":
    file_path = "SUB-IP-EST2023-POP.xlsx"
    
    # Prepare data
    df = clean_and_prepare_data(file_path)
    
    # Calculate statistics
    stats = analyze_state_statistics(df)
    
    # Print statistics for each state
    for state, state_stats in stats.items():
        print(f"\n{'='*50}")
        print(f"Statistics for {state}:")
        print(f"{'='*50}")
        print(f"Number of cities: {state_stats['num_cities']}")
        print(f"Average population (2023): {state_stats['avg_population_2023']:,.0f}")
        print(f"Median population (2023): {state_stats['median_population_2023']:,.0f}")
        print(f"Population standard deviation: {state_stats['std_population_2023']:,.0f}")
        print(f"Total population (2023): {state_stats['total_population_2023']:,.0f}")
        print(f"\nLargest city: {state_stats['largest_city']['name']} "
              f"({state_stats['largest_city']['population']:,.0f} people)")
        print(f"Smallest city: {state_stats['smallest_city']['name']} "
              f"({state_stats['smallest_city']['population']:,.0f} people)")
        print(f"\nAverage growth rate (2020-2023): {state_stats['avg_growth_rate']:.2f}%")
        print(f"Fastest growing city: {state_stats['fastest_growing']['name']} "
              f"({state_stats['fastest_growing']['rate']:.2f}%)")
    
    # Create visualizations
    # create_visualizations(df)