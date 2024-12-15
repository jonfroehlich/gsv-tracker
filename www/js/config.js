/**
 * Configuration settings for the GSV Coverage Visualization application
 */
const CONFIG = {
    // GitHub repository information
    repo: {
        owner: 'jonfroehlich',
        name: 'gsv_metadata_tracker',
        branch: 'main'
    },

    // API endpoints
    urls: {
        // Functions to generate URLs for data fetching
        getCitiesJson() {
            return `https://raw.githubusercontent.com/${this.repo.owner}/${this.repo.name}/${this.repo.branch}/data/available_cities.json`;
        },
        getCityData(filename) {
            return `https://raw.githubusercontent.com/${this.repo.owner}/${this.repo.name}/${this.repo.branch}/data/${filename}`;
        }
    },

    // Map configuration
    map: {
        defaultZoom: 2,
        defaultCenter: [0, 0],
        minZoom: 2,
        maxZoom: 19,
        tileLayer: {
            url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            opacity: 0.8
        },
        boundsPadding: 50
    },

    // Visualization settings
    visualization: {
        // Marker appearance
        marker: {
            defaultRadius: 2,
            minRadius: 2,
            maxRadius: 8,
            zoomRadiusOffset: 8, // Subtracted from zoom level for radius calculation
            opacity: 0.8,
            highlightOpacity: 1.0,
            dimOpacity: 0.1,
            strokeWidth: 1
        },

        // Color scheme
        colorScale: {
            hue: 200, // Blue hue
            saturation: 80,
            minLightness: 20,
            maxLightness: 80
        },

        // Histogram settings
        histogram: {
            minWidth: 300,
            widthPerBar: 30,
            height: 150,
            maxWidthPercent: 80, // Maximum width as percentage of viewport
            fadeOpacity: 0.2,
            position: {
                bottom: 50,
                right: 50
            },
            margins: {
                top: 20,
                right: 10,
                bottom: 25,
                left: 40
            },
            animation: {
                duration: 200
            }
        },

        // Chart.js common settings
        chart: {
            scales: {
                y: {
                    beginAtZero: true,
                    grace: '10%', // Add 10% padding to max value
                    title: {
                        display: true,
                        text: 'GSV Images'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Capture Date',
                        padding: { top: 10 }
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            },
            plugins: {
                tooltip: {
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    titleColor: '#000',
                    bodyColor: '#000',
                    borderColor: '#ccc',
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 4
                }
            }
        }
    },

    // UI settings
    ui: {
        // Loading overlay
        loading: {
            backgroundColor: 'rgba(255, 255, 255, 0.8)',
            textColor: '#333',
            fontSize: '24px',
            zIndex: 2000
        },

        // Overlay panels
        panels: {
            backgroundColor: 'rgba(255, 255, 255, 0.95)',
            borderRadius: '6px',
            borderColor: '#ccc',
            shadowColor: 'rgba(0, 0, 0, 0.2)',
            zIndex: 1000
        },

        // Fonts
        fonts: {
            primary: 'Arial, sans-serif',
            sizes: {
                small: '12px',
                normal: '14px',
                large: '16px',
                title: '18px'
            }
        }
    },

    // Debug settings
    debug: {
        enabled: false,
        logLevel: 'warn', // 'debug' | 'info' | 'warn' | 'error'
        showPerformanceMetrics: false
    }
};

// Freeze the configuration object to prevent modifications
Object.freeze(CONFIG);

// Export for use in other modules
export default CONFIG;