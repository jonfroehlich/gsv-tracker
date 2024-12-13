# gsv_metadata_tracker/vis.py

import folium
import branca.colormap as cm
import pandas as pd
from datetime import datetime
import json
import logging
import seaborn as sns
import matplotlib.colors
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Optional

logger = logging.getLogger(__name__)

def create_visualization_map(df: pd.DataFrame, city_name: str) -> folium.Map:
    """
    Create an interactive map visualization of GSV metadata with temporal histogram.
    
    Args:
        df: DataFrame containing GSV metadata
        city_name: Name of the city being visualized
    
    Returns:
        folium.Map object with the visualization
    """
    # Debug information
    logger.info("Total rows: %d", len(df))
    logger.info("Rows with status 'OK': %d", len(df[df['status'] == 'OK']))

    # Filter for valid data
    valid_rows = df[
        (df['status'] == 'OK') &
        (df['pano_lat'].notna()) &
        (df['pano_lon'].notna())
    ]
    logger.info("Rows with valid coordinates: %d", len(valid_rows))

    # Filter for Google imagery
    valid_rows = valid_rows[valid_rows['copyright_info'].str.contains('Google', na=False)]
    logger.info("Rows with Google imagery: %d", len(valid_rows))

    # Filter for valid dates
    valid_rows = valid_rows.dropna(subset=['capture_date'])
    logger.info("Final valid rows: %d", len(valid_rows))

    if len(valid_rows) == 0:
        logger.warning("No valid data to visualize")
        return folium.Map()

    # Calculate map center
    map_center = [valid_rows['pano_lat'].mean(), valid_rows['pano_lon'].mean()]

    # Create base map
    folium_map = folium.Map(
        location=map_center,
        zoom_start=13,
        tiles=None
    )

    # Add dark theme tile layer
    folium.TileLayer(
        tiles='cartodbdark_matter',
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        opacity=0.8
    ).add_to(folium_map)

    # Create feature group for markers
    fg = folium.FeatureGroup(name="Pano Markers")

    # Create colormap
    oldest_date = valid_rows['capture_date'].min()
    days_since_oldest = (datetime.now() - oldest_date).days
    colormap = cm.linear.YlOrRd_09.scale(0, days_since_oldest)

    # Prepare histogram data
    hist_data = valid_rows.groupby('capture_date').size().reset_index()
    hist_data.columns = ['date', 'count']
    hist_data['date_str'] = hist_data['date'].dt.strftime('%Y-%m')
    hist_data['days_ago'] = (datetime.now() - hist_data['date']).dt.days
    hist_data['color'] = hist_data['days_ago'].apply(lambda x: matplotlib.colors.to_hex(colormap(x)))

    # Add markers
    marker_data = []
    for idx, row in valid_rows.iterrows():
        capture_date = row['capture_date']
        date_str = capture_date.strftime('%Y-%m-%d')
        age_years = (datetime.now() - capture_date).days / 365.25
        recency = (datetime.now() - capture_date).days
        color = matplotlib.colors.to_hex(colormap(recency))

        popup = folium.Popup(f"""
            <div>
                Capture Date: {date_str}
                <br>Age: {age_years:.1f} years
                <br>Copyright: {row['copyright_info']}
            </div>
        """, max_width=300)

        folium.CircleMarker(
            location=[row['pano_lat'], row['pano_lon']],
            radius=2,
            color=color,
            stroke=False,
            fill=True,
            fill_color=color,
            fill_opacity=0.8,
            popup=popup,
            tooltip=f"Capture Date: {date_str}<br>Age: {age_years:.1f} years"
        ).add_to(fg)

        marker_data.append({
            'element_id': f'marker_{idx}',
            'date': date_str
        })

    # Add feature group to map
    fg.add_to(folium_map)

    # Add HTML/CSS for legend and histogram
    legend_and_hist_html = """
    <style>
        .overlay-panel {
            background-color: rgba(255, 255, 255, 0.9);
            padding: 15px;
            border-radius: 6px;
            border: 1px solid #ccc;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
            z-index: 1000;
        }

        .histogram-container {
            position: fixed;
            bottom: 50px;
            right: 50px;
        }

        .histogram-content {
            width: 300px;
            height: 150px;
            margin-top: 10px;
        }

        .legend {
            background-color: rgba(255, 255, 255, 0.9) !important;
            padding: 6px !important;
            border-radius: 4px !important;
            border: 1px solid #ccc !important;
        }

        .leaflet-control-colormap {
            background-color: rgba(255, 255, 255, 0.9) !important;
            padding: 6px !important;
            border-radius: 4px !important;
            border: 1px solid #ccc !important;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2) !important;
        }

        .panel-title {
            font-size: 14px;
            font-weight: bold;
            margin: 0 0 10px 0;
            color: #333;
        }
    </style>
    <div class="overlay-panel histogram-container">
        <div class="panel-title">GSV Coverage Over Time</div>
        <div class="histogram-content">
            <canvas id="histogramCanvas" width="300" height="150"></canvas>
        </div>
    </div>
    """
    folium_map.get_root().html.add_child(folium.Element(legend_and_hist_html))

    # Add required JavaScript libraries
    folium_map.get_root().html.add_child(folium.Element("""
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.7.0/chart.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-datalabels/2.0.0/chartjs-plugin-datalabels.min.js"></script>
    <script>
    Chart.register(ChartDataLabels);
    </script>
    """))

    # Add JavaScript for interactive features
    histogram_js = f"""
    <script>
    var markerData = {json.dumps(marker_data)};
    var histogramData = {json.dumps(hist_data.to_dict('records'), default=str)};
    var currentHighlight = null;

    function highlightDate(targetDate) {{
        if (currentHighlight !== targetDate) {{
            resetHighlight();
        }}

        const targetYearMonth = targetDate.substring(0, 7);
        var markers = document.querySelectorAll('.leaflet-interactive');
        
        markers.forEach(function(marker, index) {{
            if (index < markerData.length) {{
                const markerYearMonth = markerData[index].date.substring(0, 7);
                marker.style.opacity = markerYearMonth === targetYearMonth ? '1' : '0.2';
                marker.style.fillOpacity = markerYearMonth === targetYearMonth ? '1' : '0.2';
            }}
        }});
        
        currentHighlight = targetDate;

        if (window.histogramChart) {{
            window.histogramChart.data.datasets[0].backgroundColor = histogramData.map(d =>
                d.date_str === targetDate ? d.color : fadeColor(d.color, 0.2)
            );
            window.histogramChart.update();
        }}
    }}

    function resetHighlight() {{
        var markers = document.querySelectorAll('.leaflet-interactive');
        markers.forEach(function(marker) {{
            marker.style.opacity = '1';
            marker.style.fillOpacity = '0.7';
        }});
        
        currentHighlight = null;

        if (window.histogramChart) {{
            window.histogramChart.data.datasets[0].backgroundColor = histogramData.map(d => d.color);
            window.histogramChart.update();
        }}
    }}

    function fadeColor(hexColor, opacity) {{
        var r = parseInt(hexColor.slice(1,3), 16);
        var g = parseInt(hexColor.slice(3,5), 16);
        var b = parseInt(hexColor.slice(5,7), 16);
        return `rgba(${{r}},${{g}},${{b}},${{opacity}})`;
    }}

    function createHistogram() {{
        var ctx = document.getElementById('histogramCanvas').getContext('2d');
        const maxCount = Math.max(...histogramData.map(d => d.count));
        const yAxisMax = Math.ceil(maxCount * 1.2);

        window.histogramChart = new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: histogramData.map(d => d.date_str),
                datasets: [{{
                    data: histogramData.map(d => d.count),
                    backgroundColor: histogramData.map(d => d.color),
                    borderColor: 'rgba(0,0,0,0.2)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                layout: {{
                    padding: {{
                        top: 20
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        callbacks: {{
                            title: function(tooltipItems) {{
                                return 'Date: ' + tooltipItems[0].label;
                            }},
                            label: function(context) {{
                                return 'Count: ' + context.raw;
                            }}
                        }}
                    }},
                    datalabels: {{
                        color: '#000',
                        font: {{
                            weight: 'bold',
                            size: 12
                        }},
                        formatter: function(value) {{
                            return value;
                        }},
                        anchor: 'end',
                        align: 'top',
                        offset: 4,
                        clamp: true
                    }}
                }},
                onClick: (event, elements) => {{
                    if (elements.length > 0) {{
                        const index = elements[0].index;
                        highlightDate(histogramData[index].date_str);
                    }} else {{
                        resetHighlight();
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: yAxisMax,
                        title: {{
                            display: true,
                            text: 'Number of Images'
                        }},
                        ticks: {{
                            padding: 5
                        }}
                    }},
                    x: {{
                        display: true,
                        title: {{
                            display: true,
                            text: 'Capture Date'
                        }},
                        ticks: {{
                            maxRotation: 45,
                            minRotation: 45
                        }}
                    }}
                }}
            }}
        }});
    }}

    document.addEventListener('DOMContentLoaded', function() {{
        var checkInterval = setInterval(function() {{
            if (window.Chart) {{
                clearInterval(checkInterval);
                setTimeout(function() {{
                    createHistogram();

                    var markers = document.querySelectorAll('.leaflet-interactive');
                    markers.forEach(function(marker, index) {{
                        if (index < markerData.length) {{
                            marker.addEventListener('click', function(e) {{
                                highlightDate(markerData[index].date);
                            }});
                        }}
                    }});

                    var map = document.querySelector('.folium-map');
                    if (map) {{
                        map.addEventListener('click', function(e) {{
                            if (!e.target.closest('.leaflet-interactive') && 
                                !e.target.closest('#histogramCanvas')) {{
                                resetHighlight();
                            }}
                        }});
                    }}
                }}, 1000);
            }}
        }}, 100);
    }});
    </script>
    """
    folium_map.get_root().html.add_child(folium.Element(histogram_js))

    # Add colormap legend
    colormap.caption = 'Recency (Days)'
    folium_map.add_child(colormap)

    return folium_map

def plot_status_distribution(df: pd.DataFrame, city_name: str, figsize: tuple = (10, 6)) -> None:
    """
    Draw a bar plot showing the distribution of different API response status types.
    
    Args:
        df: DataFrame containing the GSV metadata
        city_name: Name of the city for the plot title
        figsize: Tuple of (width, height) for the plot
    """
    plt.figure(figsize=figsize)
    
    # Create bar plot using seaborn
    ax = sns.countplot(x='status', data=df)
    
    # Customize the plot
    plt.title(f'Distribution of Status Occurrences in {city_name}')
    plt.xlabel('Status')
    plt.ylabel('Count')
    
    # Add count labels on top of bars
    for p in ax.patches:
        ax.annotate(
            f'{int(p.get_height())}',
            (p.get_x() + p.get_width() / 2., p.get_height()),
            ha='center',
            va='bottom'
        )
    
    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    plt.show()

def plot_temporal_distribution(
    df: pd.DataFrame,
    city_name: str,
    figsize: tuple = (12, 6),
    bin_freq: str = 'M',  # 'M' for month, 'Y' for year, etc.
    color: str = 'blue',
    kde: bool = False
) -> None:
    """
    Create a histogram showing the distribution of GSV images over time.
    
    Args:
        df: DataFrame containing the GSV metadata
        city_name: Name of the city for the plot title
        figsize: Tuple of (width, height) for the plot
        bin_freq: Frequency for binning dates ('M' for monthly, 'Y' for yearly)
        color: Color for the histogram bars
        kde: Whether to show the kernel density estimation curve
    """
    # Filter for successful panos with valid dates
    valid_data = df[
        (df['status'] == 'OK') & 
        (df['capture_date'].notna())
    ].copy()
    
    if len(valid_data) == 0:
        logger.warning("No valid data for temporal distribution plot")
        return
    
    # Create figure and axes
    fig, ax = plt.subplots(figsize=figsize)
    
    # Convert capture_date to datetime if it isn't already
    valid_data['capture_date'] = pd.to_datetime(valid_data['capture_date'])
    
    # Create the histogram
    sns.histplot(
        data=valid_data,
        x='capture_date',
        bins=30,
        kde=kde,
        color=color,
        ax=ax
    )
    
    # Customize the plot
    ax.set_title(f'Distribution of Street View Images Over Time in {city_name}')
    ax.set_xlabel('Capture Date')
    ax.set_ylabel('Number of Images')
    
    # Format x-axis to show dates nicely
    if bin_freq == 'M':
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    else:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    
    # Add count labels on top of bars
    for p in ax.patches:
        ax.annotate(
            f'{int(p.get_height())}',
            (p.get_x() + p.get_width() / 2., p.get_height()),
            ha='center',
            va='bottom'
        )
    
    # Rotate and align the tick labels so they look better
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    
    # Use a tight layout to prevent label cutoff
    plt.tight_layout()
    
    plt.show()

def create_summary_visualization(df: pd.DataFrame, city_name: str) -> None:
    """
    Create a comprehensive statistical visualization including status distribution
    and temporal distribution.
    
    Args:
        df: DataFrame containing the GSV metadata
        city_name: Name of the city being analyzed
    """
    # Create a figure with two subplots
    fig = plt.figure(figsize=(15, 6))
    
    # Add status distribution subplot
    plt.subplot(121)
    ax1 = sns.countplot(x='status', data=df)
    plt.title(f'Status Distribution in {city_name}')
    plt.xlabel('Status')
    plt.ylabel('Count')
    plt.xticks(rotation=45, ha='right')
    
    # Add count labels
    for p in ax1.patches:
        ax1.annotate(
            f'{int(p.get_height())}',
            (p.get_x() + p.get_width() / 2., p.get_height()),
            ha='center',
            va='bottom'
        )
    
    # Add temporal distribution subplot
    plt.subplot(122)
    valid_data = df[
        (df['status'] == 'OK') & 
        (df['capture_date'].notna())
    ].copy()
    
    if len(valid_data) > 0:
        sns.histplot(
            data=valid_data,
            x='capture_date',
            bins=30,
            color='blue'
        )
        plt.title(f'Temporal Distribution in {city_name}')
        plt.xlabel('Capture Date')
        plt.ylabel('Number of Images')
        plt.xticks(rotation=45, ha='right')
    
    # Adjust layout
    plt.tight_layout()
    plt.show()

# Example usage:
"""
# Create individual plots
plot_status_distribution(df, "Waunakee")
plot_temporal_distribution(df, "Waunakee")

# Or create a summary visualization
create_summary_visualization(df, "Waunakee")
"""